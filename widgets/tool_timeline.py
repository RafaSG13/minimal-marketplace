"""Tool timeline: each turn's tool calls as coloured marks, and calls per tool as bars."""

from __future__ import annotations

from collections import Counter

from textual.content import Content
from textual.widgets import Static

__version__ = "1.0"

TURNS = 8
"""Most recent turns shown, one row each."""

MARKS = 26
"""Most marks on one turn's row; the rest are counted as +N."""

TOP_TOOLS = 6
"""Tools shown in the calls-per-tool bars."""

MARK = {"ok": ("●", "$success"), "error": ("✘", "$error"), "pending": ("◌", "$warning")}


def _bar(fraction: float, width: int, color: str) -> Content:
    """A ``width``-cell gauge filled to ``fraction`` in ``color``, with eighth-cell precision."""
    eighths = round(max(0.0, min(1.0, fraction)) * width * 8)
    full, part = divmod(eighths, 8)
    filled = "█" * full + ("▏▎▍▌▋▊▉"[part - 1] if part else "")
    return Content.assemble((filled, color), ("░" * (width - len(filled)), "$dim"))


def _turns(messages: list[dict], live: dict[str, bool]) -> list[list[tuple[str, str]]]:
    """Per turn, its tool calls as ``(name, state)``; ``live`` maps call ids to ``is_error``."""
    errors: dict[str, bool] = {}
    for message in messages:
        if message.get("role") == "user" and isinstance(message.get("content"), list):
            for block in message["content"]:
                if block.get("type") == "tool_result":
                    errors[block.get("tool_use_id")] = bool(block.get("is_error"))
    errors.update(live)
    turns: list[list[tuple[str, str]]] = []
    for message in messages:
        content = message.get("content")
        if message.get("role") == "user" and isinstance(content, str):
            turns.append([])
        elif message.get("role") == "assistant" and isinstance(content, list):
            for block in content:
                if block.get("type") != "tool_use":
                    continue
                if not turns:
                    turns.append([])
                error = errors.get(block.get("id"))
                state = "pending" if error is None else "error" if error else "ok"
                turns[-1].append((block.get("name", "?"), state))
    return turns


class ToolTimeline(Static):
    """Sidebar panel: the last turns' tool calls as marks and the most used tools as bars."""

    DEFAULT_CSS = "ToolTimeline { padding: 0 1; margin-bottom: 1; height: auto; }"

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
        turns = _turns(ctx.messages, self.live)
        calls = [call for turn in turns for call in turn]
        if not calls:
            self.display = False
            return
        errors = sum(state == "error" for _, state in calls)
        lines = [Content.assemble(("TOOLS", "bold $muted"), (f"  {len(calls)} calls · {errors} errors", "$dim"))]
        first = max(0, len(turns) - TURNS)
        for n, turn in enumerate(turns[first:], first + 1):
            row = [(f"{n:>3} ", "$dim"), *(MARK[state] for _, state in turn[:MARKS])]
            if len(turn) > MARKS:
                row.append((f"+{len(turn) - MARKS}", "$dim"))
            lines.append(Content.assemble(*row))
        lines.append(Content(""))
        top = Counter(name for name, _ in calls).most_common(TOP_TOOLS)
        most = top[0][1]
        for name, count in top:
            lines.append(Content.assemble(f"{name[:8]:<8} ", _bar(count / most, 12, "$accent"), f" {count}"))
        self.update(Content("\n").join(lines))
        self.display = True


def register(minimal):
    minimal.register_widget("tool_timeline", lambda ctx: ToolTimeline(), area="sidebar")
