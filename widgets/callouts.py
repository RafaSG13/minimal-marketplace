"""Callouts: draws GitHub alert blockquotes (> [!NOTE], [!TIP], [!IMPORTANT], [!WARNING], [!CAUTION]) as coloured boxes."""

from __future__ import annotations

import re

from textual.app import ComposeResult
from textual.content import Content
from textual.widget import Widget
from textual.widgets import Static
from textual.widgets._markdown import MarkdownBlockQuote, MarkdownParagraph
from textual.widgets.markdown import Markdown

__version__ = "1.0"

KINDS = {
    "note": ("ⓘ", "Note", "$accent"),
    "tip": ("✦", "Tip", "$success"),
    "important": ("❖", "Important", "$secondary"),
    "warning": ("⚠", "Warning", "$warning"),
    "caution": ("✘", "Caution", "$error"),
}
"""Alert kind → (icon, title, colour)."""

MARKER = re.compile(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*", re.I)
"""The alert marker that opens the first paragraph of a callout blockquote."""


class CalloutQuote(MarkdownBlockQuote):
    """A blockquote that becomes a coloured callout box when it starts with an alert marker."""

    DEFAULT_CSS = "\n".join(
        f"CalloutQuote.-{kind} {{ border-left: outer {color}; background: {color} 10%; }}"
        for kind, (_icon, _title, color) in KINDS.items()
    ) + "\nCalloutQuote .callout-title { text-style: bold; }"

    def compose(self) -> ComposeResult:
        first = self._blocks[0] if self._blocks else None
        if isinstance(first, MarkdownParagraph) and (m := MARKER.match(first._content.plain)):
            kind = m.group(1).lower()
            icon, title, color = KINDS[kind]
            self.add_class("-callout", f"-{kind}")
            rest = first._content[m.end() :]
            if rest.plain.strip():
                first.set_content(rest)
            else:
                self._blocks.pop(0)
            yield Static(Content.styled(f"{icon} {title}", color), classes="callout-title")
        yield from super().compose()


class CalloutSupport(Widget):
    """Invisible holder: swaps in CalloutQuote while mounted, restores the stock blockquote when removed."""

    DEFAULT_CSS = "CalloutSupport { display: none; }"

    def on_mount(self) -> None:
        Markdown.BLOCKS = {**Markdown.BLOCKS, "blockquote_open": CalloutQuote}

    def on_unmount(self) -> None:
        Markdown.BLOCKS = {**Markdown.BLOCKS, "blockquote_open": MarkdownBlockQuote}


def register(minimal):
    minimal.register_widget("callouts", lambda ctx: CalloutSupport(), area="bottom")
    minimal.append_system_prompt(
        "The terminal UI draws GitHub alert blockquotes (> [!NOTE], > [!TIP], > [!IMPORTANT], > [!WARNING], "
        "> [!CAUTION]) as coloured callouts; use them for notes and warnings the user must not miss."
    )
