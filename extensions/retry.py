"""Retries model requests that fail with rate limits, overloads or network errors, with backoff and an optional fallback provider.

A request that fails with a retryable error (HTTP 408, 409, 425, 429, 5xx overloads, a dropped
connection or a timeout) is sent again after an exponential backoff, or after the
``Retry-After`` the provider asked for, capped at ``max_delay``. After ``max_attempts`` retries it
switches once to ``fallback`` (``"provider"`` or ``"provider/model"``), if set. Any other error
ends the turn as before. Everything is a setting (``/ext settings retry``): the backoff
(``max_attempts``, ``base_delay``, ``factor``, ``max_delay``, ``respect_retry_after``), what counts
as retryable (``statuses``, ``network_errors``, ``match``), the toast (``notify``, ``retry_message``,
``fallback_message``) and ``progress``, a live countdown next to the working indicator::

    {"extensions": {"settings": {"retry": {"max_attempts": 5, "base_delay": 2.0,
                                           "max_delay": 60.0, "fallback": "openai/gpt-4.1"}}}}

Install it with ``/ext``.
"""

import time

__version__ = "1.4"
__api__ = "2.4"
__tags__ = ["provider"]

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
"""HTTP statuses worth another try: timeouts, conflicts, rate limits and server overloads."""

NETWORK_ERRORS = {
    "APIConnectionError",
    "APITimeoutError",
    "RemoteProtocolError",
    "ReadTimeout",
    "ConnectTimeout",
    "ReadError",
    "ConnectError",
}
"""Names of the SDK and httpx exceptions for a dropped connection or a timeout."""

RETRY_MESSAGE = "retry: {error} ({attempt}/{max_attempts}), again in {delay:.0f}s"
FALLBACK_MESSAGE = "retry: switching to {fallback}"

DEFAULTS = {
    "max_attempts": 5,
    "base_delay": 2.0,
    "factor": 2.0,
    "max_delay": 60.0,
    "respect_retry_after": True,
    "fallback": "",
    "statuses": sorted(RETRYABLE_STATUS),
    "network_errors": sorted(NETWORK_ERRORS),
    "match": ["overloaded"],
    "notify": True,
    "retry_message": RETRY_MESSAGE,
    "fallback_message": FALLBACK_MESSAGE,
    "progress": False,
}

SCHEMA = {
    "max_attempts": {
        "description": "Retries of one request before the fallback (or giving up); 0 retries only through the fallback.",
        "min": 0,
        "max": 100,
    },
    "base_delay": {"description": "Seconds before the first retry.", "min": 0, "max": 3600},
    "factor": {"description": "The wait grows by this factor with each retry (1: always base_delay).", "min": 1, "max": 100},
    "max_delay": {"description": "The longest wait in seconds, Retry-After included.", "min": 0, "max": 3600},
    "respect_retry_after": {"description": "Wait the Retry-After seconds the provider sent instead of the backoff."},
    "fallback": {
        "description": "Provider (or provider/model) to switch to once the retries ran out; empty for none.",
    },
    "statuses": {"description": "HTTP status codes worth a retry."},
    "network_errors": {"description": "Class names of dropped-connection and timeout errors worth a retry."},
    "match": {"description": "Text (any case) in an error message that makes it worth a retry."},
    "notify": {"description": "Show a toast for each retry and for the switch to the fallback."},
    "retry_message": {
        "description": "The toast of a retry; fields {error} (class name), {attempt}, {max_attempts}, {delay} (seconds)."
    },
    "fallback_message": {"description": "The toast of the switch to the fallback; field {fallback}."},
    "progress": {
        "description": "Count down the wait next to the working indicator (it stays interruptible with Esc)."
    },
}

PROGRESS_STEP = 1.0
"""Seconds between two updates of the countdown."""


def check_settings(settings):
    """``(settings, problems)``: ``settings`` as a dict where each key the schema cannot check is back to its default when
    it is inconsistent, and one text per fix."""
    fixed, problems = dict(settings), []

    def reset(key, why):
        problems.append(f"{key} {why}; the default is used until you fix it")
        fixed[key] = DEFAULTS[key]

    for key in ("statuses", "network_errors", "match"):
        if not all(isinstance(v, (int if key == "statuses" else str)) and not isinstance(v, bool) for v in fixed[key]):
            reset(key, f"must be a list of {'whole numbers' if key == 'statuses' else 'strings'}")
    for code in fixed["statuses"]:
        if isinstance(code, int) and not 100 <= code <= 599:
            reset("statuses", f"has {code}, which is not an HTTP status (100-599)")
            break
    fallback = fixed["fallback"]
    if fallback:
        name, _, model = fallback.partition("/")
        if not name.strip() or name != name.strip() or (fallback.count("/") and not model.strip()):
            reset("fallback", f"{fallback!r} must be \"provider\" or \"provider/model\"")
    for key, fields in (
        ("retry_message", {"error": "", "attempt": 0, "max_attempts": 0, "delay": 0.0}),
        ("fallback_message", {"fallback": ""}),
    ):
        try:
            fixed[key].format(**fields)
        except (KeyError, IndexError, ValueError) as e:
            names = ", ".join("{" + f + "}" for f in fields)
            reset(key, f"is not a valid template ({type(e).__name__}: {e}); it may use {names}")
    return fixed, problems


def _get(settings, key):
    """``settings[key]``, or its default for a ``settings`` without it (a caller that predates the setting)."""
    return settings[key] if key in settings else DEFAULTS[key]


def _status(error):
    """The HTTP status the SDK attached to ``error``, or ``None``."""
    for value in (getattr(error, "status_code", None), getattr(error, "code", None)):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def retryable(error, settings=DEFAULTS) -> bool:
    """Whether ``error`` is a rate limit, an overload or a network failure that may pass if retried."""
    text = str(error).lower()
    return (
        _status(error) in _get(settings, "statuses")
        or isinstance(error, (ConnectionError, TimeoutError))
        or type(error).__name__ in _get(settings, "network_errors")
        or any(word.lower() in text for word in _get(settings, "match") if word)
    )


def _retry_after(error) -> float | None:
    """The seconds of the response's ``Retry-After`` header, or ``None`` if it has none usable."""
    headers = getattr(getattr(error, "response", None), "headers", None)
    if headers is None:
        return None
    try:
        seconds = float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def verdict(error, attempt, provider, settings) -> dict | None:
    """What to do about the failed request number ``attempt`` to ``provider``: a ``provider_error`` result, or ``None`` to give up.

    Up to ``max_attempts`` retries wait ``base_delay * factor ** (attempt - 1)`` seconds, or the
    ``Retry-After`` the provider sent, never more than ``max_delay``. Then, once, the ``fallback``
    provider: minimal keeps counting ``attempt`` after the switch, so the next failure finds
    ``provider`` equal to the fallback and gives up.
    """
    if not retryable(error, settings):
        return None
    if attempt <= _get(settings, "max_attempts"):
        after = _retry_after(error) if _get(settings, "respect_retry_after") else None
        if after is None:
            after = _get(settings, "base_delay") * _get(settings, "factor") ** (attempt - 1)
        return {"retry_after": min(_get(settings, "max_delay"), after)}
    if _get(settings, "fallback"):
        name, _, model = _get(settings, "fallback").partition("/")
        if name != provider:
            return {"provider": name, **({"model": model} if model else {})}
    return None


def _count_down(ctx, seconds, label):
    """Show ``label`` and the seconds left next to the working indicator until ``seconds`` passed.

    Raises:
        TurnInterrupted: if the user interrupts the wait.
    """
    end = time.monotonic() + seconds
    try:
        while (left := end - time.monotonic()) > 0:
            ctx.check_cancelled()
            ctx.progress(f"{label} again in {left:.0f}s")
            time.sleep(min(PROGRESS_STEP, left))
        ctx.check_cancelled()
    finally:
        ctx.progress(None)


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    settings, problems = check_settings(settings)
    for problem in problems:
        minimal.report_problem(f"extensions.settings.retry.{problem}")

    @minimal.on("provider_error")
    def retry(event):
        ctx, error = event["ctx"], event["error"]
        v = verdict(error, event["attempt"], event["provider"], settings)
        if v is None:
            return None
        if "retry_after" in v:
            fields = {
                "error": type(error).__name__,
                "attempt": event["attempt"],
                "max_attempts": settings["max_attempts"],
            }
            message = settings["retry_message"].format(**fields, delay=v["retry_after"])
        else:
            message = settings["fallback_message"].format(fallback=settings["fallback"])
        if settings["notify"] and message:
            try:
                ctx.notify(message, "warning")
            except Exception:  # a frontend without notifications must not stop the retry
                pass
        if settings["progress"] and v.get("retry_after"):
            _count_down(ctx, v["retry_after"], f"retry: {fields['error']} ({fields['attempt']}/{fields['max_attempts']}),")
            return {"retry_after": 0}
        return v
