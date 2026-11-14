"""The Textual terminal UI for minimal: app.py holds MinimalTui and run_tui; widgets, dialogs, frontend and theme live beside it.

minimal finds it through the ``minimal.frontends`` entry point, which calls :func:`register`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.content import Content

    from minimal.extensions.registry import LogoSpec, Registry

__all__ = ["logo_content", "register"]


def register(registry: Registry) -> None:
    """Register the ``tui`` frontend (the entry point minimal calls)."""
    from minimal_textual.app import run_tui

    registry.register_frontend("tui", run_tui, "the terminal UI: transcript, widgets, themes", toolkit="textual")


def logo_content(spec: LogoSpec) -> Content:
    """The pixel-art logo ``spec`` as Textual content: each pair of art rows is one row of half blocks (see :func:`minimal_textual.widgets.logo_content`)."""
    from minimal_textual.widgets import logo_content as render

    return render(spec)
