"""Web search tool for the model, using the Brave Search API (needs BRAVE_API_KEY).

Create a key at https://api-dashboard.search.brave.com/app/keys and export it as
``BRAVE_API_KEY`` before starting minimal. Several searches in one model reply run side by side. Settings
(``/ext settings web_search``): ``count`` and ``max_count`` (results), ``timeout`` (seconds), ``clip`` (longest
snippet, 0 for whole), ``max_chars`` (longest output, the rest is cut and counted), ``user_agent``, ``endpoint`` and
``key_env`` (another Brave-compatible API or key variable), ``country``, ``language`` and ``safesearch`` (sent to the
API when set) and ``progress``.

Install it with ``/ext``.
"""

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

__version__ = "1.5"
__api__ = "2.4"
__tags__ = ["workflow"]

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
KEYS_URL = "https://api-dashboard.search.brave.com/app/keys"
DEFAULT_COUNT = 5
MAX_COUNT = 20
"""Most results the API returns per request."""
TIMEOUT_S = 20

DEFAULTS = {
    "count": DEFAULT_COUNT,
    "max_count": MAX_COUNT,
    "timeout": TIMEOUT_S,
    "clip": 0,
    "max_chars": 30000,
    "user_agent": "",
    "endpoint": ENDPOINT,
    "key_env": "BRAVE_API_KEY",
    "country": "",
    "language": "",
    "safesearch": "",
    "progress": True,
}

SCHEMA = {
    "count": {"description": "Results when the model does not say.", "min": 1, "max": 100},
    "max_count": {"description": "The most results a call may ask for.", "min": 1, "max": 100},
    "timeout": {"description": "Seconds to wait for the API.", "min": 1, "max": 300},
    "clip": {"description": "Longest snippet in characters, cut with an ellipsis (0: whole).", "min": 0, "max": 5000},
    "max_chars": {"description": "Longest output in characters; the rest is cut and counted.", "min": 1000, "max": 1000000},
    "user_agent": {"description": "User-Agent header to send (empty: Python's default)."},
    "endpoint": {"description": "Search API URL (Brave-compatible)."},
    "key_env": {"description": "Environment variable that holds the API key."},
    "country": {"description": "Two-letter country code sent as `country` (empty: none)."},
    "language": {"description": "Language code sent as `search_lang` (empty: none)."},
    "safesearch": {"description": "Adult-content filter sent as `safesearch` (empty: API default).", "enum": ["", "off", "moderate", "strict"]},
    "progress": {"description": "Show the query next to the working indicator while searching."},
}


def _clean(text):
    """``text`` without the tags Brave marks matches with (``<strong>``) and with entities decoded."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def web_search(input, ctx, settings=DEFAULTS):
    """Search the web; return numbered results as ``title``, ``url`` and ``description`` lines.

    Raises:
        ValueError: if the API key variable is not set, the query is empty or ``count`` is not a number.
        RuntimeError: if the API cannot be reached, times out, rejects the key, answers with another HTTP error or
            does not answer with JSON; each message says what to do.
    """
    key_env = settings["key_env"]
    key = os.environ.get(key_env)
    if not key:
        raise ValueError(
            f"{key_env} is not set; create a key at {KEYS_URL} and export it before starting minimal "
            f"(export {key_env}=<key>), or name another variable in the key_env setting"
        )
    query = input.get("query")
    query = query.strip() if isinstance(query, str) else ""
    if not query:
        raise ValueError("query is empty; pass the words to search for as a non-empty string")
    try:
        count = max(1, min(settings["max_count"], int(input.get("count", settings["count"]))))
    except (TypeError, ValueError):
        raise ValueError(f"count must be a whole number from 1 to {settings['max_count']}") from None
    params = {"q": query, "count": count}
    for name, setting in (("country", "country"), ("search_lang", "language"), ("safesearch", "safesearch")):
        if settings[setting]:
            params[name] = settings[setting]

    headers = {"Accept": "application/json", "X-Subscription-Token": key}
    if settings["user_agent"]:
        headers["User-Agent"] = settings["user_agent"]
    request = urllib.request.Request(f"{settings['endpoint']}?{urllib.parse.urlencode(params)}", headers=headers)
    if settings["progress"]:
        ctx.progress(f"searching: {query}")
    source = "Brave Search" if settings["endpoint"] == ENDPOINT else urllib.parse.urlsplit(settings["endpoint"]).netloc
    try:
        with urllib.request.urlopen(request, timeout=settings["timeout"]) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code in (401, 403):
            raise RuntimeError(
                f"{source} rejected the API key in {key_env} (HTTP {e.code}); check or create a key at {KEYS_URL}, "
                f"export it again before starting minimal, or name another variable in the key_env setting"
            ) from e
        if e.code == 429:
            raise RuntimeError(
                f"{source} refused the search: rate limit or quota reached (HTTP 429); wait a moment and retry, "
                f"or check your plan at {KEYS_URL}"
            ) from e
        raise RuntimeError(f"{source} returned HTTP {e.code}: {body[:200]}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, TimeoutError):
            raise RuntimeError(
                f"{source} did not answer within {settings['timeout']} s; retry, or raise the timeout setting"
            ) from e
        raise RuntimeError(
            f"could not reach {source}: {reason}; check the network connection or the endpoint setting"
        ) from e
    except ValueError as e:  # not UTF-8 or not JSON
        raise RuntimeError(f"{source} did not answer with JSON ({e}); check the endpoint setting") from e
    finally:
        if settings["progress"]:
            ctx.progress(None)

    results = (data.get("web") or {}).get("results") or [] if isinstance(data, dict) else []
    if not results:
        return "No results"
    text = "\n\n".join(
        f"{i}. {_clean(r.get('title', ''))}\n{r.get('url', '')}\n{_clip(_clean(r.get('description', '')), settings['clip'])}"
        for i, r in enumerate(results, 1)
    )
    if len(text) > settings["max_chars"]:
        cut = len(text) - settings["max_chars"]
        text = f"{text[: settings['max_chars']]}\n[clipped {cut} chars; ask for fewer results with count or set the clip setting]"
    return text


def _clip(text, limit):
    """``text`` cut to ``limit`` characters with an ellipsis; whole when ``limit`` is 0."""
    return text if not limit or len(text) <= limit else text[: limit - 1].rstrip() + "…"


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if settings["count"] > settings["max_count"]:
        minimal.report_problem(
            f"setting count ({settings['count']}) is above max_count ({settings['max_count']}); "
            f"using {settings['max_count']}: lower count or raise max_count"
        )
        settings = {**settings, "count": settings["max_count"]}
    minimal.register_tool(
        name="web_search",
        run=lambda input, ctx: web_search(input, ctx, settings),
        read_only=True,
        description=(
            "Search the web with Brave Search. Returns numbered results: title, URL and snippet. Prefer it to "
            "`bash` with curl for finding pages: it takes a query, needs no URL, prompts for no permission and several "
            "searches in one reply run side by side. To read a page itself, use `bash` (curl) or a fetch tool when "
            "the snippet is not enough."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query; operators such as site: and quotes work"},
                "count": {"type": "integer", "description": f"Number of results (default {settings['count']}, max {settings['max_count']})"},
            },
            "required": ["query"],
        },
    )
