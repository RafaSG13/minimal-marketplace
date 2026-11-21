"""Web search tool for the model, using the Brave Search API (needs BRAVE_API_KEY).

Create a key at https://api-dashboard.search.brave.com and export it as
``BRAVE_API_KEY``. Several searches in one model reply run side by side. Settings (``/ext settings web_search``):
``count`` and ``max_count`` (results), ``timeout`` (seconds), ``clip`` (longest snippet, 0 for whole), ``user_agent``,
``endpoint`` and ``key_env`` (another Brave-compatible API or key variable), ``country``, ``language`` and
``safesearch`` (sent to the API when set) and ``progress``.

Install it with ``/ext``.
"""

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

__version__ = "1.3"
__api__ = "2.3"
__tags__ = ["workflow"]

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_COUNT = 5
MAX_COUNT = 20
"""Most results the API returns per request."""
TIMEOUT_S = 20

DEFAULTS = {
    "count": DEFAULT_COUNT,
    "max_count": MAX_COUNT,
    "timeout": TIMEOUT_S,
    "clip": 0,
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
        ValueError: if the API key variable is not set or the query is empty.
        RuntimeError: if the API answers with an HTTP error.
    """
    key_env = settings["key_env"]
    key = os.environ.get(key_env)
    if not key:
        raise ValueError(
            f"{key_env} is not set; create a key at https://api-dashboard.search.brave.com and export it "
            "(or name another variable in the key_env setting)"
        )
    query = input["query"].strip()
    if not query:
        raise ValueError("query is empty")
    count = max(1, min(settings["max_count"], int(input.get("count", settings["count"]))))
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
    try:
        with urllib.request.urlopen(request, timeout=settings["timeout"]) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Brave Search returned HTTP {e.code}: {body[:200]}") from e
    finally:
        if settings["progress"]:
            ctx.progress(None)

    results = (data.get("web") or {}).get("results") or []
    if not results:
        return "No results"
    return "\n\n".join(
        f"{i}. {_clean(r.get('title', ''))}\n{r.get('url', '')}\n{_clip(_clean(r.get('description', '')), settings['clip'])}"
        for i, r in enumerate(results, 1)
    )


def _clip(text, limit):
    """``text`` cut to ``limit`` characters with an ellipsis; whole when ``limit`` is 0."""
    return text if not limit or len(text) <= limit else text[: limit - 1].rstrip() + "…"


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if settings["count"] > settings["max_count"]:
        raise ValueError(
            f"web_search: setting count ({settings['count']}) is above max_count ({settings['max_count']}); "
            "lower count or raise max_count"
        )
    minimal.register_tool(
        name="web_search",
        run=lambda input, ctx: web_search(input, ctx, settings),
        read_only=True,
        description=(
            "Search the web with Brave Search. Returns numbered results: title, URL and snippet. "
            "Fetch a page with bash (curl) when the snippet is not enough."
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
