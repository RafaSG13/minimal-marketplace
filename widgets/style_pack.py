"""Style pack: coloured gutters for messages and tool calls, a rounded composer and a compact or cozy density."""

from __future__ import annotations

from textual.widget import Widget

__version__ = "1.0"

DENSITY = "cozy"
"""Transcript spacing: "cozy" keeps minimal's padding and gaps, "compact" removes the gaps between blocks."""

CSS_COMMON = """
Screen.-style-pack .user { border-left: thick $accent; }
Screen.-style-pack .tool { border-left: thick $border-muted; }
Screen.-style-pack .tool.-success { border-left: thick $success; }
Screen.-style-pack .tool.-error { border-left: thick $error; }
Screen.-style-pack .tool.-pending { border-left: thick $warning; }
Screen.-style-pack Markdown.assistant { padding: 0 1 0 2; }
Screen.-style-pack #composer { border: round $border-muted; }
Screen.-style-pack #composer:focus-within { border: round $border-blue; }
"""
"""Rules for every density. Gated behind the screen class so they switch off when the widget is removed."""

CSS_COMPACT = """
Screen.-style-pack .user, Screen.-style-pack .tool { padding: 0 2; }
Screen.-style-pack .user, Screen.-style-pack .tool, Screen.-style-pack Markdown.assistant,
Screen.-style-pack .output, Screen.-style-pack .error { margin-top: 0; }
"""
"""Extra rules for the compact density."""


class StylePack(Widget):
    """Invisible holder: loads the style rules and turns them on while mounted, off when removed.

    The rules are added as a user stylesheet source, which wins over the TUI's own CSS (widget
    ``DEFAULT_CSS`` would lose to it).
    """

    DEFAULT_CSS = "StylePack { display: none; }"

    def on_mount(self) -> None:
        css = CSS_COMMON + (CSS_COMPACT if DENSITY == "compact" else "")
        self.app.stylesheet.add_source(css, read_from=("style_pack", "StylePack"), is_default_css=False)
        self.screen.add_class("-style-pack")
        self.app.refresh_css(animate=False)

    def on_unmount(self) -> None:
        # The CSS source stays loaded but inert without the class; a remount replaces the same source.
        self.screen.remove_class("-style-pack")


def register(minimal):
    minimal.register_widget("style_pack", lambda ctx: StylePack(), area="bottom")
