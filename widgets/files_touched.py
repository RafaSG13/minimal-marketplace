"""Files touched: files read, edited and written this session, with added/removed line counts."""

from __future__ import annotations

import os
from difflib import SequenceMatcher
from pathlib import Path

from textual.content import Content
from textual.widgets import Static

__version__ = "1.2"
__api__ = "1"

ROWS = 12
"""Most files listed, most recently touched first."""

NAME_WIDTH = 14
"""Columns for a file name; longer names lose their start."""

COUNTS_WIDTH = 8
"""Columns for ``+added −removed``, so the bars line up; the row fills the 31-column sidebar panel."""

MARKERS = {"A": "$success", "M": "$warning", "R": "$muted"}


def _diff_bar(added: int, removed: int, cells: int = 5) -> Content:
    """``cells`` blocks split between added (green) and removed (red) lines."""
    total = added + removed
    if not total:
        return Content.styled("·" * cells, "$dim")
    plus = round(cells * added / total)
    return Content.assemble(("█" * plus, "$diff-added"), ("█" * (cells - plus), "$diff-removed"))


def _name(path: Path, cwd: Path) -> str:
    """``path`` relative to ``cwd`` when under it, else absolute with ``~`` for home; cut to NAME_WIDTH."""
    if path.is_relative_to(cwd):
        name = os.path.relpath(path, cwd)
    elif path.is_relative_to(home := Path.home()):
        name = str(Path("~", path.relative_to(home)))
    else:
        name = str(path)
    return name if len(name) <= NAME_WIDTH else "…" + name[-(NAME_WIDTH - 1) :]


def _edit_counts(old: str, new: str) -> tuple[int, int]:
    """``(added, removed)`` line counts of replacing ``old`` with ``new``."""
    added = removed = 0
    matcher = SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("delete", "replace"):
            removed += i2 - i1
        if tag in ("insert", "replace"):
            added += j2 - j1
    return added, removed


def _files(messages: list[dict], cwd: Path, live: dict[str, bool]) -> dict[Path, dict]:
    """Stats per resolved path of every successful read/edit/write; ``live`` maps call ids to ``is_error``."""
    errors: dict[str, bool] = {}
    for message in messages:
        if message.get("role") == "user" and isinstance(message.get("content"), list):
            for block in message["content"]:
                if block.get("type") == "tool_result":
                    errors[block.get("tool_use_id")] = bool(block.get("is_error"))
    errors.update(live)
    files: dict[Path, dict] = {}
    for index, message in enumerate(messages):
        if message.get("role") != "assistant" or not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            name, inp = block.get("name"), block.get("input") or {}
            if block.get("type") != "tool_use" or name not in ("read", "edit", "write"):
                continue
            if errors.get(block.get("id"), True) or not isinstance(inp.get("path"), str):
                continue
            stats = files.setdefault(
                (cwd / inp["path"]).resolve(),
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


class FilesTouched(Static):
    """Sidebar panel: the session's files with a change marker and added/removed lines."""

    DEFAULT_CSS = "FilesTouched { padding: 0 1; margin-bottom: 1; height: auto; }"

    def __init__(self) -> None:
        super().__init__()
        self.live: dict[str, bool] = {}
        self.display = False

    def refresh_state(self, ctx) -> None:
        self._draw(ctx)

    def refresh_live(self, ctx, event: dict) -> None:
        if event["kind"] == "start":
            self.live.clear()
        elif event["kind"] == "tool_result":
            self.live[event["call"]["id"]] = bool(event["result"].get("is_error"))
        self._draw(ctx)

    def _draw(self, ctx) -> None:
        cwd = Path(ctx.cwd or ".").resolve()
        files = _files(ctx.messages, cwd, self.live)
        if not files:
            self.display = False
            return
        total_added = sum(stats["added"] for stats in files.values())
        total_removed = sum(stats["removed"] for stats in files.values())
        lines = [
            Content.assemble(
                ("FILES", "bold $muted"), (f"  {len(files)} · +{total_added} −{total_removed}", "$dim")
            )
        ]
        recent = sorted(files.items(), key=lambda item: item[1]["last"], reverse=True)[:ROWS]
        for path, stats in recent:
            marker = _marker(stats)
            row = [(marker, MARKERS[marker]), f" {_name(path, cwd).ljust(NAME_WIDTH)} "]
            if marker == "R":
                row.append((f"read ×{stats['reads']}", "$dim"))
            else:
                counts = f"+{stats['added']} −{stats['removed']}"
                row += [
                    (f"+{stats['added']}", "$diff-added"),
                    " ",
                    (f"−{stats['removed']}", "$diff-removed"),
                    " " * max(1, COUNTS_WIDTH + 1 - len(counts)),
                    _diff_bar(stats["added"], stats["removed"]),
                ]
            lines.append(Content.assemble(*row))
        self.update(Content("\n").join(lines))
        self.display = True


def register(minimal):
    minimal.register_widget("files_touched", lambda ctx: FilesTouched(), area="sidebar")
