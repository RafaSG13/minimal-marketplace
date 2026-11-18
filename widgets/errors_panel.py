"""Errors panel: the session's last tool errors and provider errors with a count each; /errors clear empties it."""

from __future__ import annotations

__version__ = "1.1"
__api__ = "2"
__tags__ = ["diagnostics", "ui"]

DEFAULTS = {"max": 5, "width": 30}
"""``max``: errors listed; ``width``: columns of one row (the sidebar's usable width is 34)."""


KEEP = 200
"""Characters of a message kept; a row shows fewer."""


def clean(text: object) -> str:
    """``text`` as one printable line: control characters (escape sequences, newlines) become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def record(entries: list[dict], source: str, message: object, limit: int) -> None:
    """Note an error of ``source`` (a tool name or ``provider``) in ``entries``, most recent last.

    The same source and message as the latest entry only raises its count. Past ``limit`` the oldest
    entries are dropped; the order of the rest is kept.
    """
    message = clean(message)[:KEEP]
    if entries and entries[-1]["source"] == source and entries[-1]["message"] == message:
        entries[-1]["count"] += 1
        return
    entries.append({"source": source, "message": message, "count": 1})
    del entries[: max(0, len(entries) - max(1, limit))]


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(1, width - 1)].rstrip() + "…"


def format_rows(entries: list[dict], limit: int, width: int) -> list:
    """Panel lines, newest first, at most ``limit`` and each at most ``width`` columns; ``None`` if empty."""
    if not entries:
        return None
    width = max(10, width)
    lines = [[("ERRORS", "bold error"), (f"  {sum(e['count'] for e in entries)}", "dim")]]
    for entry in reversed(entries[-max(1, limit) :]):
        count = f" ×{entry['count']}" if entry["count"] > 1 else ""
        head = clean(entry["source"])
        room = max(1, width - len(head) - len(count) - 1)
        lines.append([(head, "error"), (count, "dim"), " " + _clip(entry["message"], room)])
    return lines


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS)
    entries: list[dict] = []

    @minimal.on("tool_result")
    def tool_result(event):
        if event["is_error"]:
            record(entries, event["name"], event["output"], settings["max"])

    @minimal.on("provider_error")
    def provider_error(event):
        error = event["error"]
        record(entries, "provider", f"{type(error).__name__}: {error}", settings["max"])

    minimal.on("session_switch", lambda event: entries.clear())
    minimal.register_panel("errors", lambda ctx: format_rows(entries, settings["max"], settings["width"]))

    @minimal.command(description="errors clear: forget the errors listed in the sidebar")
    def errors(args, ctx):
        if args.strip() != "clear":
            print(f"{len(entries)} error(s) listed. Use /errors clear to forget them.")
            return
        entries.clear()
        print("Errors cleared.")
