"""Mermaid viewer: draws the ```mermaid blocks in replies as diagrams, like GitHub does.

Diagrams are drawn with termaid as Unicode box art (flowchart, sequence, class, ER, state,
gantt, pie, mindmap, …) and redrawn line by line while a reply streams. A block that can't be
drawn shows its source with the error under it. Needs termaid: `/ext` offers to install it into
minimal's Python.
"""

from __future__ import annotations

from collections import OrderedDict

from minimal.api import theme

try:
    from termaid import render
    from termaid.utils import fit_to_width
except ImportError:
    render = None

__version__ = "1.9"
__api__ = "2.3"
__tags__ = ["ui"]
__dependencies__ = ["termaid>=0.12,<1"]

INSTALL_HINT = (
    "the mermaid extension needs termaid>=0.12,<1: run `uv pip install 'termaid>=0.12,<1'` in minimal's environment "
    "(or start minimal with `uv run --with 'termaid>=0.12,<1' minimal`)"
)

ARROW_STYLES = ("pointer", "triangle", "outline")
"""The ``arrow_style`` values termaid draws."""

TERMAID_OPTIONS = {
    "padding_x": int,
    "padding_y": int,
    "gap": int,
    "rounded_edges": bool,
    "inline_edge_labels": bool,
    "max_label_width": int,
    "arrow_style": str,
}
"""The termaid ``render`` options the ``termaid`` setting may pass, with their types."""

MAX_LINE = 500
"""Characters of a source line shown when the diagram is not drawn."""

CACHE_SIZE = 32
"""Drawings kept; a streamed reply redraws one fence once per line, and a redraw of the transcript repeats them all."""


def check_options(options: dict) -> dict:
    """``options`` (the ``termaid`` setting) if every key is a termaid option of the right type.

    Raises:
        ValueError: naming the offending option.
    """
    for name, value in options.items():
        kind = TERMAID_OPTIONS.get(name)
        if kind is None:
            raise ValueError(f"mermaid: termaid has no option {name!r}; use {', '.join(TERMAID_OPTIONS)}")
        if kind is int and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError(f"mermaid: termaid.{name} must be a non-negative integer, not {value!r}")
        if kind is not int and not isinstance(value, kind):
            raise ValueError(f"mermaid: termaid.{name} must be a {kind.__name__}, not {value!r}")
    if options.get("arrow_style", "pointer") not in ARROW_STYLES:
        raise ValueError(f"mermaid: termaid.arrow_style must be one of {', '.join(ARROW_STYLES)}")
    return options


def clean(text: object, limit: int = 200) -> str:
    """``text`` as one printable line of at most ``limit`` characters."""
    line = " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


class Drawer:
    """Draws mermaid sources with termaid, remembering the last ``CACHE_SIZE`` drawings."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.options = {**check_options(dict(settings["termaid"])), "use_ascii": bool(settings["ascii"])}
        self.cache: OrderedDict[tuple[str, int], str | Exception] = OrderedDict()

    def draw(self, src: str, width: int) -> str:
        """The art for ``src`` narrowed towards ``width``; raises what termaid raises (cached too)."""
        key = (src, width)
        if key in self.cache:
            self.cache.move_to_end(key)
            found = self.cache[key]
        else:
            try:
                found = fit_to_width(
                    lambda **override: render(src, **{**self.options, **override}),
                    render(src, **self.options),
                    width,
                    gap=self.options.get("gap", 4),
                    padding_x=self.options.get("padding_x", 4),
                )
            except Exception as e:
                found = e
            self.cache[key] = found
            while len(self.cache) > CACHE_SIZE:
                self.cache.popitem(last=False)
        if isinstance(found, Exception):
            raise found
        return found


def make_renderer(drawer: Drawer):
    settings = drawer.settings

    def render_fence(ctx, block):
        """``block``'s source as box art narrowed towards its width; ``None`` (the source as is) while it streams
        and can't be drawn."""
        src, closed, width = block["source"], block["closed"], block["width"]
        lines = ["".join(ch if ch.isprintable() else " " for ch in line)[:MAX_LINE] for line in src.rstrip("\n").split("\n")]

        def failed(message):
            # While streaming, keep drawing the source until the block closes.
            if not closed:
                return None
            return [*lines, "", [(f"{theme.WARNING} mermaid: {clean(message)}", "warning")]]

        if len(src) > settings["max_source_chars"]:
            return [
                *lines[: settings["notice_lines"]],
                "",
                [(f"{theme.WARNING} mermaid: {len(src):,} characters is over max_source_chars "
                  f"({settings['max_source_chars']:,}); showing the source", "warning")],
            ]
        if not closed and len(src) > settings["max_stream_chars"]:
            return None  # too big to redraw on every streamed line: the source until the fence closes
        try:
            art = drawer.draw(src, width)
        except Exception as e:
            return failed(f"{type(e).__name__}: {e}")
        if not art.strip():
            return failed("nothing to draw")
        rows = art.split("\n")
        limit = settings["max_lines"]
        if limit and len(rows) > limit:
            rows = [*rows[:limit], [(f"… {len(rows) - limit} more lines (max_lines {limit})", "dim")]]
        return rows

    return render_fence


def register(minimal):
    settings = minimal.declare_settings(
        {
            "enabled": True,
            "max_source_chars": 20000,
            "max_stream_chars": 4000,
            "max_lines": 0,
            "notice_lines": 12,
            "ascii": False,
            "termaid": {},
            "prompt_hint": True,
        },
        {
            "enabled": {"description": "Draw mermaid blocks as diagrams. False leaves them as plain code fences."},
            "max_source_chars": {
                "description": "A diagram whose source is longer is not drawn (it would freeze the UI); its source is shown.",
                "min": 100,
                "max": 1000000,
            },
            "max_stream_chars": {
                "description": "While a reply streams, a diagram longer than this is drawn only once its fence closes.",
                "min": 100,
                "max": 1000000,
            },
            "max_lines": {"description": "Rows of a drawn diagram before it is cut; 0 for no limit.", "min": 0, "max": 5000},
            "notice_lines": {
                "description": "Source lines shown above the notice for a diagram over max_source_chars.",
                "min": 0,
                "max": 200,
            },
            "ascii": {"description": "Draw with ASCII characters instead of Unicode box drawing."},
            "termaid": {
                "description": (
                    "Extra termaid render options: "
                    + ", ".join(f"{name} ({kind.__name__})" for name, kind in TERMAID_OPTIONS.items())
                    + ". Example: {\"padding_x\": 2, \"arrow_style\": \"triangle\"}."
                )
            },
            "prompt_hint": {
                "description": "Tell the model in the system prompt that mermaid blocks are drawn (costs about 40 tokens)."
            },
        },
    )
    if not settings["enabled"]:
        return
    if render is None:
        raise ImportError(INSTALL_HINT, name="termaid")
    minimal.register_renderer("fence:mermaid", make_renderer(Drawer(settings)))
    if settings["prompt_hint"]:
        minimal.append_system_prompt(
            "The terminal UI draws ```mermaid fenced code blocks as diagrams. When the user asks for a diagram, "
            "or a diagram would show structure or flow better than prose, write it as a ```mermaid block."
        )
