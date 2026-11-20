"""Logo: a pixel-art M and a wordmark in the welcome header, with your own colours, text and an optional animation."""

from __future__ import annotations

import re

from minimal.api import LogoSpec, logo_content

__version__ = "2.0"
__api__ = "2.3"
__tags__ = ["ui"]

DEFAULTS = {
    "enabled": True,
    "gradient": ["#f25fc4", "#d861d9", "#b665ea", "#9370f2", "#6f86f4", "#4fa1f2", "#3bb7ec"],
    "shadow": "#3a2a5e",
    "text": "minimal",
    "text_color": "$foreground",
    "align": "center",
    "animate": False,
    "fps": 10,
    "pause_during_turn": True,
}
"""The settings and what they do are in :data:`SCHEMA`."""

SCHEMA = {
    "enabled": {"description": "Draw this logo; false leaves minimal's default wordmark in the header."},
    "gradient": {
        "description": "Colours of the M from its top-left corner to its bottom-right one, 1 to 30 entries, each "
        "#rrggbb or a theme variable such as $accent or $secondary (a variable follows /theme).",
    },
    "shadow": {"description": "Colour of the M's drop shadow (#rrggbb or $variable); empty for no shadow."},
    "text": {
        "description": "The wordmark drawn beside the M, up to 16 characters of a-z, 0-9, space, - and _; "
        "empty draws only the M.",
    },
    "text_color": {"description": "Colour of the wordmark (#rrggbb or $variable)."},
    "align": {"description": "Where the logo and the header text under it sit.", "enum": ["left", "center", "right"]},
    "animate": {"description": "Let the gradient flow across the M and the wordmark's shadow (redraws the logo)."},
    "fps": {"description": "Animation frames per second.", "min": 1, "max": 30},
    "pause_during_turn": {"description": "Freeze the animation while the model works, so a turn costs no redraws."},
}
"""Description, enum and range of each setting (``/ext settings widgets/logo``)."""

MAX_COLORS = 30
"""Most gradient colours; the animation plays the gradient there and back, so it needs twice as many keys."""

MAX_TEXT = 16
"""Most characters of the wordmark."""

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
"""The M, one character per pixel."""

FONT = {
    "a": ["####", "...#", "####", "#..#", "####"],
    "b": ["#...", "###.", "#..#", "#..#", "###."],
    "c": [".###", "#...", "#...", "#...", ".###"],
    "d": ["...#", ".###", "#..#", "#..#", ".###"],
    "e": [".##.", "#..#", "####", "#...", ".###"],
    "f": [".###", "#...", "###.", "#...", "#..."],
    "g": [".###", "#...", "#.##", "#..#", ".###"],
    "h": ["#...", "###.", "#..#", "#..#", "#..#"],
    "i": ["#", ".", "#", "#", "#"],
    "j": ["...#", "....", "...#", "#..#", ".##."],
    "k": ["#..#", "#.#.", "##..", "#.#.", "#..#"],
    "l": ["#.", "#.", "#.", "#.", "##"],
    "m": ["#####", "#.#.#", "#.#.#", "#.#.#", "#.#.#"],
    "n": ["####", "#..#", "#..#", "#..#", "#..#"],
    "o": [".##.", "#..#", "#..#", "#..#", ".##."],
    "p": ["###.", "#..#", "###.", "#...", "#..."],
    "q": [".##.", "#..#", "#..#", ".###", "...#"],
    "r": ["###.", "#..#", "###.", "#.#.", "#..#"],
    "s": [".###", "#...", ".##.", "...#", "###."],
    "t": ["###", ".#.", ".#.", ".#.", ".#."],
    "u": ["#..#", "#..#", "#..#", "#..#", ".##."],
    "v": ["#...#", "#...#", ".#.#.", ".#.#.", "..#.."],
    "w": ["#...#", "#...#", "#.#.#", "##.##", "#...#"],
    "x": ["#..#", "#..#", ".##.", "#..#", "#..#"],
    "y": ["#..#", "#..#", ".###", "...#", "###."],
    "z": ["####", "...#", ".##.", "#...", "####"],
    "0": [".##.", "#..#", "#..#", "#..#", ".##."],
    "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["###.", "...#", ".##.", "#...", "####"],
    "3": ["###.", "...#", ".##.", "...#", "###."],
    "4": ["#..#", "#..#", "####", "...#", "...#"],
    "5": ["####", "#...", "###.", "...#", "###."],
    "6": [".###", "#...", "###.", "#..#", ".##."],
    "7": ["####", "...#", "..#.", ".#..", ".#.."],
    "8": [".##.", "#..#", ".##.", "#..#", ".##."],
    "9": [".##.", "#..#", ".###", "...#", "###."],
    "-": ["...", "...", "###", "...", "..."],
    "_": ["....", "....", "....", "....", "####"],
    " ": ["..", "..", "..", "..", ".."],
}
"""The wordmark's letters: five pixel rows each (``#`` is drawn)."""

KEYS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrtuvxyz"
"""Art characters of the gradient colours (``s`` is the shadow and ``w`` the wordmark)."""

_COLOR = re.compile(r"#[0-9a-fA-F]{6}|\$[a-z][a-z0-9-]*")


def check_settings(settings) -> list[str]:
    """What is wrong with ``settings``, one sentence per problem with the fix; empty if usable."""
    problems = []
    gradient = settings["gradient"]
    if not gradient or len(gradient) > MAX_COLORS:
        problems.append(f"'gradient' needs 1 to {MAX_COLORS} colours, not {len(gradient)}")
    for name, value in [("gradient", c) for c in gradient] + [("shadow", settings["shadow"])] + [
        ("text_color", settings["text_color"])
    ]:
        if not (isinstance(value, str) and (_COLOR.fullmatch(value) or (name == "shadow" and value == ""))):
            problems.append(f"'{name}' has {value!r}, which is not a #rrggbb colour or a $variable")
    text = settings["text"]
    unknown = sorted({ch for ch in text.lower() if ch not in FONT})
    if unknown:
        problems.append(f"'text' has characters the pixel font lacks: {''.join(unknown)!r} (use a-z, 0-9, space, - _)")
    if len(text) > MAX_TEXT:
        problems.append(f"'text' is {len(text)} characters; at most {MAX_TEXT}")
    return problems


def wordmark(text: str) -> list[str]:
    """The five pixel rows of ``text``, letters one pixel apart."""
    return [".".join(FONT[ch][row] for ch in text.lower()) for row in range(5)]


def cycle_of(gradient: list[str]) -> list[str]:
    """The gradient there and back, so an animation loops without a seam."""
    return gradient + gradient[-2:0:-1]


def build_art(settings, colors: list[str]) -> tuple[list[str], dict[str, str]]:
    """``(art, key -> colour)`` for ``register_logo``: the M coloured by ``colors`` from corner to corner.

    The shadow and the wordmark are left out when ``shadow`` or ``text`` is empty.
    """
    shadow, text = settings["shadow"], settings["text"]
    height, width = len(M), len(M[0])
    word = wordmark(text) if text else []
    canvas = [["."] * (width + 1 + (3 + len(word[0]) if word else 0)) for _ in range(height + 1)]
    if shadow:
        for y in range(height):
            for x in range(width):
                if M[y][x] == "#":
                    canvas[y + 1][x + 1] = "s"
    for y in range(height):
        for x in range(width):
            if M[y][x] == "#":
                canvas[y][x] = KEYS[(x + y) * len(colors) // (width + height - 1)]
    top = (height + 1 - 5) // 2 + 1
    for row, line in enumerate(word):
        for x, pixel in enumerate(line):
            if pixel == "#":
                canvas[top + row][width + 4 + x] = "w"
    palette = {KEYS[i]: color for i, color in enumerate(colors)}
    if shadow:
        palette["s"] = shadow
    if word:
        palette["w"] = settings["text_color"]
    return ["".join(row) for row in canvas], palette


class Player:
    """The animation's state: which frame shows, and whether it runs. Frames are drawn once and kept."""

    def __init__(self, settings, art: list[str], cycle: list[str]) -> None:
        self.art = art
        self.cycle = cycle
        self.align = settings["align"]
        self.fixed = {k: v for k, v in (("s", settings["shadow"]), ("w", settings["text_color"])) if v}
        self.pause = settings["pause_during_turn"]
        self.busy = False
        self.stopped = False
        self.phase = 0
        self.frames: dict[int, object] = {}

    def colors(self, phase: int) -> dict[str, str]:
        """The colour of every art key at ``phase``: the gradient shifted by that many steps."""
        size = len(self.cycle)
        return {KEYS[i]: self.cycle[(i + phase) % size] for i in range(size)} | self.fixed

    def frame(self, phase: int):
        """The logo as it looks at ``phase``."""
        if phase not in self.frames:
            self.frames[phase] = logo_content(LogoSpec(self.art, self.colors(phase), self.align))
        return self.frames[phase]

    def step(self):
        """The next frame, or None while stopped or paused for a turn."""
        if self.stopped or (self.pause and self.busy):
            return None
        self.phase = (self.phase + 1) % len(self.cycle)
        return self.frame(self.phase)


def shimmer(player: Player, fps: int):
    """The invisible widget whose timer recolours the header logo (Textual is imported only when animating)."""
    from textual.css.query import NoMatches
    from textual.widget import Widget
    from textual.widgets import Static

    class Shimmer(Widget):
        DEFAULT_CSS = "Shimmer { display: none; }"

        def on_mount(self) -> None:
            self.flow = self.set_interval(1 / fps, self.tick)

        def tick(self) -> None:
            if player.stopped:
                self.flow.stop()
                return
            content = player.step()
            if content is None:
                return
            try:
                self.app.query_one("Header .logo", Static).update(content)
            except NoMatches:
                pass

    return Shimmer()


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    if problems := check_settings(settings):
        raise ValueError(f"logo settings: {'; '.join(problems)}")
    gradient = list(settings["gradient"])
    animate = settings["animate"]
    colors = cycle_of(gradient) if animate else gradient
    art, palette = build_art(settings, colors)
    minimal.register_logo(art, palette, settings["align"])
    if not animate:
        return
    player = Player(settings, art, colors)
    minimal.on_dispose(lambda: setattr(player, "stopped", True))
    minimal.on("agent_start", lambda event: setattr(player, "busy", True) if event.get("agent_id") == "main" else None)
    minimal.on("agent_end", lambda event: setattr(player, "busy", False) if event.get("agent_id") == "main" else None)
    minimal.register_widget("logo", lambda ctx: shimmer(player, settings["fps"]), area="top")
