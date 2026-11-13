"""Mermaid viewer: draws the ```mermaid blocks in replies as diagrams, like GitHub does.

Diagrams are drawn with termaid as Unicode box art (flowchart, sequence, class, ER, state,
gantt, pie, mindmap, …) and redrawn line by line while a reply streams. A block that can't be
drawn shows its source with the error under it. Needs termaid: `/ext` offers to install it into
minimal's Python.
"""

from __future__ import annotations

from minimal.api import theme

try:
    from termaid import render
    from termaid.utils import fit_to_width
except ImportError:
    render = None

__version__ = "1.5"
__api__ = "1.3"
__dependencies__ = ["termaid>=0.12"]

INSTALL_HINT = (
    "the mermaid extension needs termaid: run `uv pip install termaid` in minimal's environment "
    "(or start minimal with `uv run --with termaid minimal`)"
)


def render_fence(ctx, block):
    """``block``'s source as box art narrowed towards its width; ``None`` (the source as is) while it streams and can't be drawn."""
    src, closed, width = block["source"], block["closed"], block["width"]

    def failed(message):
        # While streaming, keep drawing the source until the block closes.
        if not closed:
            return None
        return [*src.rstrip("\n").split("\n"), "", [(f"{theme.WARNING} mermaid: {message}", "warning")]]

    try:
        art = fit_to_width(lambda **options: render(src, **options), render(src), width)
    except Exception as e:
        return failed(f"{type(e).__name__}: {e}")
    if not art.strip():
        return failed("nothing to draw")
    return art.split("\n")


def register(minimal):
    if render is None:
        raise ImportError(INSTALL_HINT, name="termaid")
    minimal.register_renderer("fence:mermaid", render_fence)
    minimal.append_system_prompt(
        "The terminal UI draws ```mermaid fenced code blocks as diagrams. When the user asks for a diagram, "
        "or a diagram would show structure or flow better than prose, write it as a ```mermaid block."
    )
