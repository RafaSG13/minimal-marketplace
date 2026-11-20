"""Files touched: files read, edited and written this session, with added/removed line counts."""

from __future__ import annotations

import functools
import os

from minimal.api import WIDGET_AREAS

__version__ = "1.6"
__api__ = "2.3"
__tags__ = ["context", "ui"]

DEFAULT_GLYPHS = {"added": "A", "modified": "M", "read": "R", "bar": "█", "bar_empty": "·", "minus": "−"}
"""Marker letters (a file created, modified, only read), the diff-bar cell, its empty filler and the minus sign."""

MARKER_STYLES = {"A": "success", "M": "warning", "R": "muted"}

DEFAULTS = {
    "enabled": True,
    "title": "FILES",
    "area": "sidebar",
    "order": 0,
    "rows": 12,
    "name_width": 14,
    "counts_width": 8,
    "bar_width": 5,
    "show_reads": True,
    "sort": "recent",
    "glyphs": DEFAULT_GLYPHS,
}

SCHEMA = {
    "enabled": {"description": "Show the panel; false registers nothing."},
    "title": {"description": "Heading above the panel (empty: no heading)."},
    "area": {"description": "Where the panel goes by default (/ui move changes it).", "enum": list(WIDGET_AREAS)},
    "order": {"description": "Position among the panels of the area (lower first)."},
    "rows": {"description": "Most files listed.", "min": 1, "max": 200},
    "name_width": {"description": "Columns for a file name; longer names lose their start.", "min": 6, "max": 120},
    "counts_width": {"description": "Columns for '+added -removed' so the bars line up.", "min": 0, "max": 30},
    "bar_width": {"description": "Cells of the added/removed bar (0: no bar).", "min": 0, "max": 30},
    "show_reads": {"description": "List files that were only read, not changed."},
    "sort": {"description": "Row order: most recently touched or biggest change first.", "enum": ["recent", "size"]},
    "glyphs": {
        "description": "Glyphs by key: added, modified, read (marker letters), bar, bar_empty, minus. "
        "Keys you leave out keep their default."
    },
}


def merge_glyphs(user: dict) -> dict[str, str]:
    """The default glyphs with the user's non-empty string overrides; ``ValueError`` for an unknown key or value."""
    glyphs = dict(DEFAULT_GLYPHS)
    for key, value in user.items():
        if key not in DEFAULT_GLYPHS:
            raise ValueError(f"glyphs: unknown key {key!r} (known: {', '.join(DEFAULT_GLYPHS)})")
        if not isinstance(value, str) or not value or not value.isprintable():
            raise ValueError(f"glyphs.{key} must be a short printable string")
        glyphs[key] = value
    return glyphs


def clean(text: object) -> str:
    """``text`` as one printable line: control characters (escape sequences, newlines) become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def _diff_bar(added: int, removed: int, cells: int, glyphs: dict[str, str]) -> list:
    """``cells`` blocks split between added (green) and removed (red) lines, as pieces."""
    if cells <= 0:
        return []
    total = added + removed
    if not total:
        return [(glyphs["bar_empty"] * cells, "dim")]
    plus = round(cells * added / total)
    return [(glyphs["bar"] * plus, "diff_added"), (glyphs["bar"] * (cells - plus), "diff_removed")]


def _join(cwd: str, path: str) -> str:
    """``path`` made absolute against ``cwd`` and normalised, with no filesystem access."""
    return os.path.normpath(os.path.join(cwd, path))


def _name(path: str, cwd: str, home: str, width: int) -> str:
    """``path`` relative to ``cwd`` when under it, else absolute with ``~`` for home; cut to ``width``."""
    if path == cwd or path.startswith(cwd.rstrip(os.sep) + os.sep):
        name = os.path.relpath(path, cwd)
    elif home and path.startswith(home.rstrip(os.sep) + os.sep):
        name = "~" + path[len(home.rstrip(os.sep)) :]
    else:
        name = path
    name = clean(name)
    return name if len(name) <= width else "…" + name[-(width - 1) :]


@functools.lru_cache(maxsize=512)
def _edit_counts(old: str, new: str) -> tuple[int, int]:
    """``(added, removed)`` line counts of replacing ``old`` with ``new``."""
    from difflib import SequenceMatcher

    added = removed = 0
    matcher = SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("delete", "replace"):
            removed += i2 - i1
        if tag in ("insert", "replace"):
            added += j2 - j1
    return added, removed


def _files(messages: list[dict], cwd: str, live: dict[str, bool]) -> dict[str, dict]:
    """Stats per normalised path of every successful read/edit/write; ``live`` maps call ids to ``is_error``."""
    errors: dict[str, bool] = {}
    for message in messages:
        if message.get("role") == "user" and isinstance(message.get("content"), list):
            for block in message["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    errors[block.get("tool_use_id")] = bool(block.get("is_error"))
    errors.update(live)
    files: dict[str, dict] = {}
    for index, message in enumerate(messages):
        if message.get("role") != "assistant" or not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            if not isinstance(block, dict):
                continue
            name, inp = block.get("name"), block.get("input") or {}
            if block.get("type") != "tool_use" or name not in ("read", "edit", "write"):
                continue
            if errors.get(block.get("id"), True) or not isinstance(inp.get("path"), str):
                continue
            stats = files.setdefault(
                _join(cwd, inp["path"]),
                {"first": name, "reads": 0, "edits": 0, "writes": 0, "added": 0, "removed": 0, "last": 0},
            )
            stats["last"] = index
            if name == "read":
                stats["reads"] += 1
            elif name == "edit":
                stats["edits"] += 1
                # One replacement (old_string/new_string) or, since minimal 0.5, several (edits).
                replacements = inp["edits"] if isinstance(inp.get("edits"), list) else [inp]
                for e in replacements:
                    if isinstance(e, dict):
                        added, removed = _edit_counts(str(e.get("old_string", "")), str(e.get("new_string", "")))
                        stats["added"] += added
                        stats["removed"] += removed
            else:
                stats["writes"] += 1
                stats["added"] += len(str(inp.get("content", "")).splitlines())
    return files


def _marker(stats: dict) -> str:
    """``A`` created by a write, ``M`` edited or rewritten after a read, ``R`` only read."""
    if stats["edits"] or (stats["writes"] and stats["first"] != "write"):
        return "M"
    return "A" if stats["writes"] else "R"


class FilesTouched:
    """Panel: the session's files with a change marker and added/removed lines, cached per transcript state."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.glyphs = merge_glyphs(settings["glyphs"])
        self.errors: dict[str, bool] = {}
        self.version = 0
        self._key: tuple | None = None
        self._lines: list | None = None

    def live(self, ctx, event: dict) -> None:
        if event["kind"] == "start":
            changed = bool(self.errors)
            self.errors.clear()
        elif event["kind"] == "tool_result":
            changed = True
            self.errors[event["call"]["id"]] = bool(event["result"].get("is_error"))
        else:
            return
        if changed:
            self.version += 1

    def render(self, ctx):
        messages = ctx.messages
        key = (
            id(messages),
            len(messages),
            id(messages[0]) if messages else 0,
            id(messages[-1]) if messages else 0,
            ctx.cwd,
            self.version,
        )
        if key != self._key:
            self._lines = self._build(ctx)
            self._key = key
        return self._lines

    def _build(self, ctx):
        s = self.settings
        cwd = os.path.abspath(ctx.cwd or ".")
        files = _files(ctx.messages, cwd, self.errors)
        if not s["show_reads"]:
            files = {path: stats for path, stats in files.items() if _marker(stats) != "R"}
        if not files:
            return None
        minus = self.glyphs["minus"]
        total_added = sum(stats["added"] for stats in files.values())
        total_removed = sum(stats["removed"] for stats in files.values())
        lines = [[(f"{len(files)} · +{total_added} {minus}{total_removed}", "dim")]]
        if s["sort"] == "size":
            key = lambda item: (item[1]["added"] + item[1]["removed"], item[1]["last"])  # noqa: E731
        else:
            key = lambda item: item[1]["last"]  # noqa: E731
        home = os.path.expanduser("~")
        for path, stats in sorted(files.items(), key=key, reverse=True)[: s["rows"]]:
            marker = _marker(stats)
            glyph = self.glyphs[{"A": "added", "M": "modified", "R": "read"}[marker]]
            row = [(glyph, MARKER_STYLES[marker]), f" {_name(path, cwd, home, s['name_width']).ljust(s['name_width'])} "]
            if marker == "R":
                row.append((f"read ×{stats['reads']}", "dim"))
            else:
                counts = f"+{stats['added']} {minus}{stats['removed']}"
                row += [
                    (f"+{stats['added']}", "diff_added"),
                    " ",
                    (f"{minus}{stats['removed']}", "diff_removed"),
                    " " * max(1, s["counts_width"] + 1 - len(counts)),
                    *_diff_bar(stats["added"], stats["removed"], s["bar_width"], self.glyphs),
                ]
            lines.append(row)
        return lines


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    panel = FilesTouched(settings)
    minimal.register_panel(
        "files_touched",
        panel.render,
        area=settings["area"],
        live=panel.live,
        order=settings["order"],
        title=settings["title"] or None,
        collapsible=True,
    )
