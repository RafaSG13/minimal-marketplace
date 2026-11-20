"""Transcript minimap: one coloured cell per transcript block; click a cell to scroll to it."""

import re

from minimal.api import WIDGET_AREAS
from textual.content import Content
from textual.css.query import NoMatches
from textual.widgets import Static

__version__ = "1.6"
__api__ = "2.3"
__tags__ = ["ui"]

DEFAULT_COLORS = {
    "user": "$accent",
    "assistant": "$foreground",
    "tool_ok": "$success",
    "tool_error": "$error",
    "tool_pending": "$warning",
    "tool": "$dim",
    "error": "$error",
    "output": "$muted",
    "other": "$dim",
}
"""Colour of each kind of transcript block: a ``$theme_variable`` or ``#rrggbb``."""

DEFAULTS = {
    "enabled": True,
    "title": "MAP",
    "area": "sidebar",
    "order": 0,
    "cols": 15,
    "glyph": "■",
    "max_rows": 0,
    "colors": DEFAULT_COLORS,
}

SCHEMA = {
    "enabled": {"description": "Show the minimap; false registers nothing."},
    "title": {"description": "Heading above the map (empty: no heading)."},
    "area": {"description": "Where the map goes by default (/ui move changes it).", "enum": list(WIDGET_AREAS)},
    "order": {"description": "Position among the widgets of the area (lower first)."},
    "cols": {"description": "Cells per row; each cell is two columns wide.", "min": 1, "max": 40},
    "glyph": {"description": "One character drawn for each block."},
    "max_rows": {"description": "Most rows drawn, the newest blocks (0: no limit, the map grows with the session).", "min": 0},
    "colors": {
        "description": "Colour by block kind: user, assistant, tool_ok, tool_error, tool_pending, tool, error, "
        "output, other. Each is $theme_variable or #rrggbb; missing kinds keep the default."
    },
}

_COLOR = re.compile(r"^(?:\$[A-Za-z][\w-]*|#[0-9A-Fa-f]{6})$")


def merge_colors(user: dict) -> dict[str, str]:
    """The default colours with the user's overrides; ``ValueError`` for an unknown kind or a bad colour."""
    colors = dict(DEFAULT_COLORS)
    for kind, value in user.items():
        if kind not in DEFAULT_COLORS:
            raise ValueError(f"colors: unknown kind {kind!r} (known: {', '.join(DEFAULT_COLORS)})")
        if not isinstance(value, str) or not _COLOR.match(value):
            raise ValueError(f"colors.{kind}: {value!r} is not $theme_variable or #rrggbb")
        colors[kind] = value
    return colors


def kind(block) -> str:
    """The kind of a transcript block, from the CSS classes documented as stable."""
    if block.has_class("user"):
        return "user"
    if block.has_class("tool"):
        if block.has_class("-error"):
            return "tool_error"
        if block.has_class("-pending"):
            return "tool_pending"
        if block.has_class("-success"):
            return "tool_ok"
        return "tool"
    if block.has_class("assistant"):
        return "assistant"
    if block.has_class("error"):
        return "error"
    if block.has_class("output"):
        return "output"
    return "other"


def check(settings) -> None:
    """``ValueError`` unless the ``colors`` and ``glyph`` settings are usable (reported when the extension loads)."""
    merge_colors(settings["colors"])
    glyph = settings["glyph"]
    if len(glyph) != 1 or not glyph.isprintable() or glyph.isspace():
        raise ValueError("glyph must be one printable character")


class TranscriptMinimap(Static):
    DEFAULT_CSS = "TranscriptMinimap { padding: 0 1; margin-bottom: 1; height: auto; }"

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.colors = merge_colors(settings["colors"])
        self.cell = settings["glyph"] + " "
        self.display = False
        self._kinds: list[str] | None = None
        self._first = 0

    def _blocks(self):
        try:
            transcript = self.app.query_one("#transcript")
        except NoMatches:
            return None, []
        return transcript, list(transcript.children)[1:]

    def refresh_state(self, ctx):
        self._draw()

    def refresh_live(self, ctx, event):
        self.call_after_refresh(self._draw)

    def _draw(self):
        _, blocks = self._blocks()
        if not blocks:
            self._kinds = None
            self.display = False
            return
        kinds = [kind(b) for b in blocks]
        if kinds == self._kinds:
            return
        self._kinds = kinds
        cols = self.settings["cols"]
        rows = self.settings["max_rows"]
        # With a row limit, the first block drawn starts a row, so the cells keep their columns as the session grows.
        self._first = -(-max(0, len(blocks) - rows * cols) // cols) * cols if rows else 0
        shown = kinds[self._first :]
        lines = [Content.assemble((f"{len(blocks)} blocks", "$dim"))]
        for start in range(0, len(shown), cols):
            lines.append(Content.assemble(*((self.cell, self.colors[k]) for k in shown[start : start + cols])))
        self.update(Content("\n").join(lines))
        self.display = True

    def on_click(self, event):
        off = event.get_content_offset(self)
        if off is None or off.y == 0:
            return
        transcript, blocks = self._blocks()
        i = self._first + (off.y - 1) * self.settings["cols"] + off.x // len(self.cell)
        if transcript is not None and 0 <= i < len(blocks):
            transcript.scroll_to_widget(blocks[i], top=True)


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    check(settings)
    minimal.register_widget(
        "transcript_minimap",
        lambda ctx: TranscriptMinimap(settings),
        area=settings["area"],
        order=settings["order"],
        title=settings["title"] or None,
        collapsible=True,
    )
