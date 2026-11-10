"""Transcript minimap: one coloured cell per transcript block; click a cell to scroll to it."""

from textual.content import Content
from textual.css.query import NoMatches
from textual.widgets import Static

__version__ = "1.0"

COLS = 15
"""Cells per row; each cell is two columns wide."""

CELL = "■ "


def _color(block):
    """Theme colour of a transcript block, from its CSS classes."""
    if block.has_class("user"):
        return "$accent"
    if block.has_class("tool"):
        if block.has_class("-error"):
            return "$error"
        if block.has_class("-pending"):
            return "$warning"
        if block.has_class("-success"):
            return "$success"
        return "$dim"
    if block.has_class("assistant"):
        return "$foreground"
    if block.has_class("error"):
        return "$error"
    if block.has_class("output"):
        return "$muted"
    return "$dim"


class TranscriptMinimap(Static):
    DEFAULT_CSS = "TranscriptMinimap { padding: 0 1; margin-bottom: 1; height: auto; }"

    def __init__(self):
        super().__init__()
        self.display = False

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
            self.display = False
            return
        lines = [Content.assemble(("MAP", "bold $muted"), (f"  {len(blocks)} blocks", "$dim"))]
        for start in range(0, len(blocks), COLS):
            lines.append(Content.assemble(*((CELL, _color(b)) for b in blocks[start : start + COLS])))
        self.update(Content("\n").join(lines))
        self.display = True

    def on_click(self, event):
        off = event.get_content_offset(self)
        if off is None or off.y == 0:
            return
        transcript, blocks = self._blocks()
        i = (off.y - 1) * COLS + off.x // 2
        if transcript is not None and 0 <= i < len(blocks):
            transcript.scroll_to_widget(blocks[i], top=True)


def register(minimal):
    minimal.register_widget("transcript_minimap", lambda ctx: TranscriptMinimap(), area="sidebar")
