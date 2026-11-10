"""Animated logo: the pixel-art M and wordmark with a gradient that flows across it (replaces widgets/logo.py; uninstall that one)."""

from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

from minimal.registry import LogoSpec
from minimal.tui import logo_content

__version__ = "1.0"

GRADIENT = ["#f25fc4", "#d861d9", "#b665ea", "#9370f2", "#6f86f4", "#4fa1f2", "#3bb7ec"]
"""Colours of the M, from its top-left corner to its bottom-right one."""

CYCLE = GRADIENT + GRADIENT[-2:0:-1]
"""The gradient there and back, so the animation loops without a seam (at most 36 colours)."""

SHADOW = "#3a2a5e"
"""Colour of the M's drop shadow, or None for no shadow."""

WORDMARK = "$foreground"
"""Colour of the "minimal" wordmark (#rrggbb or a theme variable), or None to show only the M."""

FPS = 10
"""Animation frames per second."""

M = [
    "##........##",
    "###......###",
    "####....####",
    "##.##..##.##",
    "##..####..##",
    "##...##...##",
    "##........##",
    "##........##",
    "##........##",
    "##........##",
]

FONT = {
    "m": ["#####", "#.#.#", "#.#.#", "#.#.#", "#.#.#"],
    "i": ["#", ".", "#", "#", "#"],
    "n": ["####", "#..#", "#..#", "#..#", "#..#"],
    "a": ["####", "...#", "####", "#..#", "####"],
    "l": ["#.", "#.", "#.", "#.", "##"],
}

KEYS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _wordmark(text):
    """The 5-pixel-tall rows of ``text``, letters one pixel apart."""
    return [".".join(FONT[ch][row] for ch in text) for row in range(5)]


def _art():
    """The pixel rows and their colours for ``register_logo``."""
    height, width = len(M), len(M[0])
    word = _wordmark("minimal") if WORDMARK else []
    canvas = [["."] * (width + 1 + (3 + len(word[0]) if word else 0)) for _ in range(height + 1)]
    if SHADOW:
        for y in range(height):
            for x in range(width):
                if M[y][x] == "#":
                    canvas[y + 1][x + 1] = "s"
    for y in range(height):
        for x in range(width):
            if M[y][x] == "#":
                canvas[y][x] = KEYS[(x + y) * len(CYCLE) // (width + height - 1)]
    top = (height + 1 - 5) // 2 + 1
    for row, line in enumerate(word):
        for x, pixel in enumerate(line):
            if pixel == "#":
                canvas[top + row][width + 4 + x] = "w"
    colors = {KEYS[i]: color for i, color in enumerate(CYCLE)}
    if SHADOW:
        colors["s"] = SHADOW
    if WORDMARK:
        colors["w"] = WORDMARK
    return ["".join(row) for row in canvas], colors


class Shimmer(Widget):
    """Invisible driver that recolours the header logo every frame."""

    DEFAULT_CSS = "Shimmer { display: none; }"

    def __init__(self, art, colors):
        super().__init__()
        self.art = art
        self.base_colors = colors  # Widget.colors is a read-only property

    def on_mount(self):
        self.phase = 0
        self.set_interval(1 / FPS, self._frame)

    def _frame(self):
        self.phase += 1
        rotated = {KEYS[i]: CYCLE[(i + self.phase) % len(CYCLE)] for i in range(len(CYCLE))}
        rotated.update({k: v for k, v in self.base_colors.items() if k in ("s", "w")})
        try:
            logo = self.app.query_one("Header .logo", Static)
        except NoMatches:
            return
        logo.update(logo_content(LogoSpec(self.art, rotated, "center")))


def register(minimal):
    art, colors = _art()
    minimal.register_logo(art, colors)
    minimal.register_widget("animated_logo", lambda ctx: Shimmer(art, colors), area="top")
