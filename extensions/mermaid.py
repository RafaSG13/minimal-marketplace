"""Mermaid viewer: draws the ```mermaid blocks in replies as diagrams, like GitHub does.

Diagrams are drawn with termaid as Unicode box art (flowchart, sequence, class, ER, state,
gantt, pie, mindmap, …) and redrawn line by line while a reply streams. A block that can't be
drawn shows its source with the error under it. Requires termaid: run `uv pip install termaid`
in minimal's environment, or start minimal with `uv run --with termaid minimal`.
"""

from __future__ import annotations

from contextlib import suppress

from rich.text import Text
from textual.content import Content
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Label
from textual.widgets.markdown import Markdown, MarkdownFence

from minimal import theme

try:
    from termaid import render_rich
    from termaid.utils import fit_to_width
except ImportError:
    render_rich = None

__version__ = "1.1"

INSTALL_HINT = (
    "the mermaid extension needs termaid: run `uv pip install termaid` in minimal's environment "
    "(or start minimal with `uv run --with termaid minimal`)"
)


def _draw(source: str, width: int) -> Text:
    """``source`` drawn as coloured Unicode art, narrowed towards ``width`` columns. Raises on invalid Mermaid."""

    def render(**overrides):
        return render_rich(source, theme="default", **overrides)

    diagram = fit_to_width(render, render(), width, plain=lambda t: t.plain)
    diagram.no_wrap = True
    return diagram


class MermaidFence(MarkdownFence):
    """A fence that shows ```mermaid blocks as diagrams and every other fence unchanged."""

    def __init__(self, markdown, token, code) -> None:
        super().__init__(markdown, token, code)
        raw = token.content
        self.is_mermaid = (token.info.split() or [""])[0].lower() == "mermaid"
        # markdown-it maps a closed fence to its content lines plus the two fence lines.
        self.closed = (
            token.map is not None
            and raw.endswith("\n")
            and token.map[1] - token.map[0] == raw.count("\n") + 2
        )
        # While streaming, only complete lines are drawn.
        self.mermaid_source = raw if self.closed else raw[: raw.rfind("\n") + 1]
        self.diagram: Text | None = None
        self.error: str | None = None
        self._drawn: tuple[str, bool] | None = None

    def _width(self) -> int:
        # 4 = the fence Label's horizontal padding.
        return max((self._markdown.content_region.width or self.app.size.width) - 4, 20)

    def _redraw(self) -> None:
        key = (self.mermaid_source, self.closed)
        if key == self._drawn:
            return
        self._drawn = key
        if not self.mermaid_source.strip():
            return
        try:
            diagram = _draw(self.mermaid_source, self._width())
        except Exception as e:
            # While streaming, keep the last good diagram (or the source) until the block closes.
            if self.closed:
                self.diagram, self.error = None, f"{type(e).__name__}: {e}"
            return
        if diagram.plain.strip():
            self.diagram, self.error = diagram, None
        elif self.closed:
            self.diagram, self.error = None, "nothing to draw"

    def _view(self):
        if not self.is_mermaid:
            return self._highlighted_code
        self._redraw()
        if self.diagram is not None:
            return self.diagram
        if self.error is not None:
            return Content.assemble(self.code, "\n\n", (f"{theme.WARNING} mermaid: {self.error}", "$warning"))
        return self._highlighted_code

    def compose(self):
        yield Label(self._view(), id="code-content", expand=True)

    def set_content(self, content) -> None:
        self._content = content
        with suppress(NoMatches):
            self.query_one("#code-content", Label).update(self._view())

    async def _update_from_block(self, block) -> None:
        if isinstance(block, MermaidFence):
            self.is_mermaid = block.is_mermaid
            self.closed = block.closed
            self.mermaid_source = block.mermaid_source
        await super()._update_from_block(block)

    def finish(self) -> None:
        """Draw a mermaid block the reply left unclosed as if it were closed."""
        if self.is_mermaid and not self.closed:
            self.closed = True
            self.mermaid_source = self.code + "\n"
            self.set_content(self._content)


class MermaidSupport(Widget):
    """Invisible holder: swaps in MermaidFence while mounted, restores the stock fence when removed."""

    DEFAULT_CSS = "MermaidSupport { display: none; }"

    def on_mount(self) -> None:
        Markdown.BLOCKS = {**Markdown.BLOCKS, "fence": MermaidFence}

    def on_unmount(self) -> None:
        Markdown.BLOCKS = {**Markdown.BLOCKS, "fence": MarkdownFence}

    def refresh_state(self, ctx) -> None:
        for fence in self.app.query(MermaidFence):
            fence.finish()


def register(minimal):
    if render_rich is None:
        raise ImportError(INSTALL_HINT)
    minimal.register_widget("mermaid", lambda ctx: MermaidSupport(), area="bottom")
    minimal.append_system_prompt(
        "The terminal UI draws ```mermaid fenced code blocks as diagrams. When the user asks for a diagram, "
        "or a diagram would show structure or flow better than prose, write it as a ```mermaid block."
    )
