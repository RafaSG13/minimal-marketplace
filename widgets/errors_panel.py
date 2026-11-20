"""Errors panel: the session's last tool errors and provider errors with a count each; /errors clear empties it."""

from __future__ import annotations

import re

from minimal.api import WIDGET_AREAS

__version__ = "1.2"
__api__ = "2.3"
__tags__ = ["diagnostics", "ui"]

DEFAULTS = {
    "enabled": True,
    "title": "ERRORS",
    "area": "sidebar",
    "order": 0,
    "max": 5,
    "width": 30,
    "keep": 200,
    "include_provider": True,
    "newest_first": True,
    "ignore": [],
}

SCHEMA = {
    "enabled": {"description": "Show the panel and record errors; false registers nothing."},
    "title": {"description": "Heading above the panel (empty: no heading)."},
    "area": {"description": "Where the panel goes by default (/ui move changes it).", "enum": list(WIDGET_AREAS)},
    "order": {"description": "Position among the panels of the area (lower first)."},
    "max": {"description": "Errors listed (and remembered).", "min": 1, "max": 100},
    "width": {"description": "Columns of one row (the sidebar's usable width is 34).", "min": 10, "max": 200},
    "keep": {"description": "Characters of an error message remembered; a row shows fewer.", "min": 10, "max": 2000},
    "include_provider": {"description": "Also list provider errors (rate limits, network failures)."},
    "newest_first": {"description": "List the newest error first (false: oldest first)."},
    "ignore": {
        "description": "Regular expressions (case-insensitive): a tool error whose '<tool> <message>' matches one "
        "is not listed, e.g. ['denied']."
    },
}


def clean(text: object) -> str:
    """``text`` as one printable line: control characters (escape sequences, newlines) become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def compile_ignore(patterns: list) -> list[re.Pattern]:
    """The ``ignore`` patterns compiled; ``ValueError`` naming the pattern that is not a valid regular expression."""
    compiled = []
    for pattern in patterns:
        if not isinstance(pattern, str):
            raise ValueError(f"ignore: {pattern!r} is not a string")
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as error:
            raise ValueError(f"ignore: {pattern!r} is not a valid regular expression ({error})") from None
    return compiled


def record(entries: list[dict], source: str, message: object, limit: int, keep: int = 200) -> None:
    """Note an error of ``source`` (a tool name or ``provider``) in ``entries``, most recent last.

    The same source and message as an earlier entry only raises its count and moves it last. Past ``limit`` the
    oldest entries are dropped; the order of the rest is kept. ``keep`` characters of the message are kept.
    """
    source = clean(source)
    message = clean(message)[: max(1, keep)]
    for index, entry in enumerate(entries):
        if entry["source"] == source and entry["message"] == message:
            entry["count"] += 1
            entries.append(entries.pop(index))
            return
    entries.append({"source": source, "message": message, "count": 1})
    del entries[: max(0, len(entries) - max(1, limit))]


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(1, width - 1)].rstrip() + "…"


def format_rows(entries: list[dict], limit: int, width: int, newest_first: bool = True) -> list | None:
    """Panel lines, at most ``limit`` and each at most ``width`` columns; ``None`` if empty."""
    if not entries:
        return None
    width = max(10, width)
    total = sum(e["count"] for e in entries)
    lines = [[(f"{total} error{'' if total == 1 else 's'}", "dim")]]
    shown = entries[-max(1, limit) :]
    for entry in reversed(shown) if newest_first else shown:
        count = f" ×{entry['count']}" if entry["count"] > 1 else ""
        head = clean(entry["source"])
        room = max(1, width - len(head) - len(count) - 1)
        lines.append([(head, "error"), (count, "dim"), " " + _clip(entry["message"], room)])
    return lines


def _poke(ctx) -> None:
    invalidate = getattr(ctx, "invalidate", None)
    if invalidate is not None:
        invalidate()


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    ignore = compile_ignore(settings["ignore"])
    entries: list[dict] = []

    @minimal.on("tool_result")
    def tool_result(event):
        if event["is_error"]:
            text = f"{event['name']} {clean(event['output'])}"
            if not any(pattern.search(text) for pattern in ignore):
                record(entries, event["name"], event["output"], settings["max"], settings["keep"])
                _poke(event.get("ctx"))

    @minimal.on("provider_error")
    def provider_error(event):
        if settings["include_provider"]:
            error = event["error"]
            record(entries, "provider", f"{type(error).__name__}: {error}", settings["max"], settings["keep"])
            _poke(event.get("ctx"))

    minimal.on("session_switch", lambda event: entries.clear())
    minimal.register_panel(
        "errors",
        lambda ctx: format_rows(entries, settings["max"], settings["width"], settings["newest_first"]),
        area=settings["area"],
        order=settings["order"],
        title=settings["title"] or None,
        collapsible=True,
    )

    @minimal.command(description="errors clear: forget the errors listed in the sidebar")
    def errors(args, ctx):
        if args.strip() != "clear":
            print(f"{len(entries)} error(s) listed. Use /errors clear to forget them.")
            return
        entries.clear()
        print("Errors cleared.")
