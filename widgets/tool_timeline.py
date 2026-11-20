"""Tool timeline: each turn's tool calls as coloured marks, and calls per tool as bars."""

from __future__ import annotations

import re
from collections import Counter

from minimal.api import WIDGET_AREAS

__version__ = "1.5"
__api__ = "2.3"
__tags__ = ["diagnostics", "ui"]

DEFAULT_GLYPHS = {"ok": "●", "error": "✘", "pending": "◌", "bar_empty": "░"}
"""Marks of a successful, failed and unfinished call, and the empty part of a bar."""

DEFAULT_STYLES = {"ok": "success", "error": "error", "pending": "warning", "bar": "accent"}
"""Style of each mark and of the bars (names, ``$var`` or ``#rrggbb``, as in a panel line)."""

DEFAULTS = {
    "enabled": True,
    "title": "TOOLS",
    "area": "sidebar",
    "order": 0,
    "turns": 8,
    "marks": 26,
    "top_tools": 6,
    "bar_width": 12,
    "name_width": 8,
    "glyphs": DEFAULT_GLYPHS,
    "styles": DEFAULT_STYLES,
}

SCHEMA = {
    "enabled": {"description": "Show the panel; false registers nothing."},
    "title": {"description": "Heading above the panel (empty: no heading)."},
    "area": {"description": "Where the panel goes by default (/ui move changes it).", "enum": list(WIDGET_AREAS)},
    "order": {"description": "Position among the panels of the area (lower first)."},
    "turns": {"description": "Most recent turns shown, one row each (0: no rows).", "min": 0, "max": 100},
    "marks": {"description": "Most marks on one turn's row; the rest are counted as +N.", "min": 1, "max": 200},
    "top_tools": {"description": "Tools shown in the calls-per-tool bars (0: no bars).", "min": 0, "max": 50},
    "bar_width": {"description": "Cells of a calls-per-tool bar.", "min": 1, "max": 60},
    "name_width": {"description": "Columns for a tool name in the bars; longer names are cut.", "min": 3, "max": 40},
    "glyphs": {"description": "Glyphs by key: ok, error, pending (marks), bar_empty. Missing keys keep the default."},
    "styles": {
        "description": "Styles by key: ok, error, pending (marks), bar. Names, $theme_var or #rrggbb, "
        "space-separated, e.g. 'bold $accent'."
    },
}

_STYLE_TOKEN = re.compile(
    r"^(?:\$[A-Za-z][\w-]*|#[0-9A-Fa-f]{6}|bold|italic|underline|reverse|foreground|accent|secondary|success|warning"
    r"|error|muted|dim|diff_added|diff_removed)$"
)


def merge(kind: str, defaults: dict, user: dict, check) -> dict:
    """``defaults`` with the user's ``user`` overrides; ``ValueError`` naming ``kind`` for a bad key or value."""
    merged = dict(defaults)
    for key, value in user.items():
        if key not in defaults:
            raise ValueError(f"{kind}: unknown key {key!r} (known: {', '.join(defaults)})")
        if not isinstance(value, str) or not check(value):
            raise ValueError(f"{kind}.{key}: invalid value {value!r}")
        merged[key] = value
    return merged


def clean(text: object, width: int | None = None) -> str:
    """``text`` as one printable line (control characters become spaces), cut with ``…`` beyond ``width``."""
    out = " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())
    return out if width is None or len(out) <= width else out[: max(width - 1, 0)] + "…"


def _bar(fraction: float, width: int, color: str, empty: str) -> list:
    """A ``width``-cell gauge filled to ``fraction`` in ``color``, with eighth-cell precision, as pieces."""
    eighths = round(max(0.0, min(1.0, fraction)) * width * 8)
    full, part = divmod(eighths, 8)
    filled = "█" * full + ("▏▎▍▌▋▊▉"[part - 1] if part else "")
    return [(filled, color), (empty * (width - len(filled)), "dim")]


def _turns(messages: list[dict], live: dict[str, bool]) -> list[list[tuple[str, str]]]:
    """Per turn, its tool calls as ``(name, state)``; ``live`` maps call ids to ``is_error``."""
    errors: dict[str, bool] = {}
    for message in messages:
        if message.get("role") == "user" and isinstance(message.get("content"), list):
            for block in message["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    errors[block.get("tool_use_id")] = bool(block.get("is_error"))
    errors.update(live)
    turns: list[list[tuple[str, str]]] = []
    for message in messages:
        content = message.get("content")
        if message.get("role") == "user" and isinstance(content, str):
            turns.append([])
        elif message.get("role") == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                if not turns:
                    turns.append([])
                error = errors.get(block.get("id"))
                state = "pending" if error is None else "error" if error else "ok"
                turns[-1].append((str(block.get("name", "?")), state))
    return turns


class ToolTimeline:
    """Panel: the last turns' tool calls as marks and the most used tools as bars, cached per transcript state."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.glyphs = merge("glyphs", DEFAULT_GLYPHS, settings["glyphs"], lambda v: bool(v) and v.isprintable())
        self.styles = merge("styles", DEFAULT_STYLES, settings["styles"], self._valid_style)
        self.errors: dict[str, bool] = {}
        self.version = 0
        self._key: tuple | None = None
        self._lines: list | None = None

    @staticmethod
    def _valid_style(value: str) -> bool:
        return all(_STYLE_TOKEN.match(token) for token in value.split()) and bool(value.split())

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
            self.version,
        )
        if key != self._key:
            self._lines = self._build(messages)
            self._key = key
        return self._lines

    def _build(self, messages):
        s = self.settings
        turns = _turns(messages, self.errors)
        calls = [call for turn in turns for call in turn]
        if not calls:
            return None
        errors = sum(state == "error" for _, state in calls)
        lines: list = [[(f"{len(calls)} calls · {errors} errors", "dim")]]
        first = max(0, len(turns) - s["turns"])
        for n, turn in enumerate(turns[first:], first + 1):
            row = [(f"{n:>3} ", "dim"), *((self.glyphs[state], self.styles[state]) for _, state in turn[: s["marks"]])]
            if len(turn) > s["marks"]:
                row.append((f"+{len(turn) - s['marks']}", "dim"))
            lines.append(row)
        if s["top_tools"]:
            lines.append("")
            top = Counter(name for name, _ in calls).most_common(s["top_tools"])
            most = top[0][1]
            width = s["name_width"]
            for name, count in top:
                bar = _bar(count / most, s["bar_width"], self.styles["bar"], self.glyphs["bar_empty"])
                lines.append([f"{clean(name, width):<{width}} ", *bar, f" {count}"])
        return lines


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    panel = ToolTimeline(settings)
    minimal.register_panel(
        "tool_timeline",
        panel.render,
        area=settings["area"],
        live=panel.live,
        order=settings["order"],
        title=settings["title"] or None,
        collapsible=True,
    )
