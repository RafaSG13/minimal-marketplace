"""Logo: a pixel-art M and the minimal wordmark in the welcome header."""

__version__ = "1.2"
__api__ = "2"

GRADIENT = ["#f25fc4", "#d861d9", "#b665ea", "#9370f2", "#6f86f4", "#4fa1f2", "#3bb7ec"]
"""Colours of the M, from its top-left corner to its bottom-right one (at most 36)."""

SHADOW = "#3a2a5e"
"""Colour of the M's drop shadow, or None for no shadow."""

WORDMARK = "$foreground"
"""Colour of the "minimal" wordmark (#rrggbb or a theme variable), or None to show only the M."""

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
                canvas[y][x] = KEYS[(x + y) * len(GRADIENT) // (width + height - 1)]
    top = (height + 1 - 5) // 2 + 1
    for row, line in enumerate(word):
        for x, pixel in enumerate(line):
            if pixel == "#":
                canvas[top + row][width + 4 + x] = "w"
    colors = {KEYS[i]: color for i, color in enumerate(GRADIENT)}
    if SHADOW:
        colors["s"] = SHADOW
    if WORDMARK:
        colors["w"] = WORDMARK
    return ["".join(row) for row in canvas], colors


def register(minimal):
    art, colors = _art()
    minimal.register_logo(art, colors)
