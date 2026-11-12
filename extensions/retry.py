"""Retries model requests that fail with rate limits, overloads or network errors, with backoff and an optional fallback provider.

A request that fails with a retryable error (HTTP 408, 409, 425, 429, 5xx overloads, a dropped
connection or a timeout) is sent again after an exponential backoff, or after the
``Retry-After`` the provider asked for, capped at ``max_delay``. After ``max_attempts`` retries it
switches once to ``fallback`` (``"provider"`` or ``"provider/model"``), if set. Any other error
ends the turn as before. Settings in settings.json::

    {"extensions": {"settings": {"retry": {"max_attempts": 5, "base_delay": 2.0,
                                           "max_delay": 60.0, "fallback": "openai/gpt-4.1"}}}}

Install it with ``/ext``.
"""

__version__ = "1.0"
__api__ = "1.1"

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


def _status(error):
    """The HTTP status the SDK attached to ``error``, or ``None``."""
    for value in (getattr(error, "status_code", None), getattr(error, "code", None)):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def retryable(error) -> bool:
    """Whether ``error`` is a rate limit, an overload or a network failure that may pass if retried."""
    return (
        _status(error) in RETRYABLE_STATUS
        or isinstance(error, (ConnectionError, TimeoutError))
        or type(error).__name__ in NETWORK_ERRORS
        or "overloaded" in str(error).lower()
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

    Up to ``max_attempts`` retries wait ``base_delay * 2 ** (attempt - 1)`` seconds, or the
    ``Retry-After`` the provider sent, never more than ``max_delay``. Then, once, the ``fallback``
    provider: minimal keeps counting ``attempt`` after the switch, so the next failure finds
    ``provider`` equal to the fallback and gives up.
    """
    if not retryable(error):
        return None
    if attempt <= settings["max_attempts"]:
        after = _retry_after(error)
        if after is None:
            after = settings["base_delay"] * 2 ** (attempt - 1)
        return {"retry_after": min(settings["max_delay"], after)}
    if settings["fallback"]:
        name, _, model = settings["fallback"].partition("/")
        if name != provider:
            return {"provider": name, **({"model": model} if model else {})}
    return None


def register(minimal):
    settings = minimal.declare_settings({"max_attempts": 5, "base_delay": 2.0, "max_delay": 60.0, "fallback": ""})

    @minimal.on("provider_error")
    def retry(event):
        v = verdict(event["error"], event["attempt"], event["provider"], settings)
        if v is None:
            return None
        if "retry_after" in v:
            message = (
                f"retry: {type(event['error']).__name__} ({event['attempt']}/{settings['max_attempts']}), "
                f"again in {v['retry_after']:.0f}s"
            )
        else:
            message = f"retry: switching to {settings['fallback']}"
        try:
            event["ctx"].notify(message, "warning")
        except Exception:  # a frontend without notifications must not stop the retry
            pass
        return v
