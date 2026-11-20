"""Context gauge: a one-line bar of how full the context window is, with the prompt-cache hit rate."""

from __future__ import annotations

from minimal.api import styled_line

__version__ = "2.0"
__api__ = "2.3"
__tags__ = ["context", "ui", "diagnostics"]

GLYPHS = {"left": "▕", "right": "▏", "fill": "█", "empty": "░", "eighths": "▏▎▍▌▋▊▉"}
"""The bar's pieces: its ends, the full and empty cells and the seven partial cells (``eighths``, thinnest first)."""

STYLES = {
    "label": "muted",
    "ok": "success",
    "warn": "warning",
    "crit": "error",
    "empty": "dim",
    "text": "",
    "cache": "dim",
}
"""Style of each part; ``ok``, ``warn`` and ``crit`` colour the filled bar by how full it is."""

DEFAULTS = {
    "enabled": True,
    "title": "",
    "area": "bottom",
    "order": 0,
    "width": 24,
    "label": "ctx",
    "limit": 0,
    "limits": {},
    "fallback_limit": 200_000,
    "warn": 0.5,
    "crit": 0.8,
    "show_numbers": True,
    "show_percent": True,
    "show_cache": True,
    "glyphs": {},
    "styles": {},
}

SCHEMA = {
    "enabled": {"description": "Show the gauge; false registers nothing."},
    "title": {"description": "A heading above the gauge; empty for none."},
    "area": {
        "description": "Where the gauge sits (the user's /ui move overrides it).",
        "enum": ["top", "bottom", "sidebar", "left", "footer"],
    },
    "order": {"description": "Position among the area's panels and widgets, lower first."},
    "width": {"description": "Cells of the bar.", "min": 4, "max": 200},
    "label": {"description": "Text before the bar; empty for none."},
    "limit": {
        "description": "Context window in tokens for every model; 0 asks minimal for the current model's real window.",
        "min": 0,
    },
    "limits": {
        "description": "Window per model, by name prefix (the longest match wins; it beats limit), "
        "e.g. {\"claude-opus\": 1000000}.",
    },
    "fallback_limit": {"description": "Window to use when limit is 0 and minimal does not know the model's.", "min": 1},
    "warn": {"description": "Fill fraction from which the bar turns the warn style.", "min": 0.0, "max": 1.0},
    "crit": {"description": "Fill fraction from which the bar turns the crit style.", "min": 0.0, "max": 1.0},
    "show_numbers": {"description": "Show used/limit in thousands of tokens."},
    "show_percent": {"description": "Show the fill percentage."},
    "show_cache": {"description": "Show the last reply's prompt-cache hit rate when it had one."},
    "glyphs": {"description": "Override the bar's pieces: " + ", ".join(GLYPHS) + "."},
    "styles": {"description": "Override a part's style: " + ", ".join(STYLES) + ", e.g. {\"ok\": \"$accent\"}."},
}
"""Description, enum and range of each setting (``/ext settings widgets/context_gauge``)."""


def merged(name: str, given: dict, defaults: dict, problems: list[str], style: bool = False) -> dict:
    """``defaults`` with the entries of ``given`` laid over them; each bad entry is added to ``problems``."""
    result = dict(defaults)
    for key, value in given.items():
        if key not in defaults:
            problems.append(f"'{name}' has no entry {key!r} (known: {', '.join(defaults)})")
        elif not isinstance(value, str):
            problems.append(f"'{name}.{key}' must be text, not {value!r}")
        elif style:
            try:
                styled_line((" ", value))
            except ValueError as error:
                problems.append(f"'{name}.{key}': {error}")
            else:
                result[key] = value
        else:
            result[key] = value
    return result


def check_settings(settings) -> tuple[list[str], dict, dict]:
    """``(problems, glyphs, styles)``: one sentence per problem with the fix, and the dicts over the defaults."""
    problems: list[str] = []
    glyphs = merged("glyphs", settings["glyphs"], GLYPHS, problems)
    styles = merged("styles", settings["styles"], STYLES, problems, style=True)
    if len(glyphs["eighths"]) != 7:
        problems.append("'glyphs.eighths' needs 7 characters, the partial cells from thinnest to widest")
    if settings["warn"] > settings["crit"]:
        problems.append("'warn' must not exceed 'crit'")
    for model, window in settings["limits"].items():
        if not isinstance(window, int) or isinstance(window, bool) or window < 1:
            problems.append(f"'limits.{model}' must be a token count above 0, not {window!r}")
    return problems, glyphs, styles


def window_of(ctx, settings) -> int:
    """The window to draw against: ``limits`` by model prefix, else ``limit``, else the model's, else the fallback."""
    model = ctx.model or ""
    prefixes = [prefix for prefix in settings["limits"] if model.startswith(prefix)]
    if prefixes:
        return settings["limits"][max(prefixes, key=len)]
    return settings["limit"] or ctx.context_window or settings["fallback_limit"]


def format_limit(window: int) -> str:
    """``200k`` or ``1M`` for a window."""
    return f"{window // 1000}k" if window < 1_000_000 else f"{window / 1e6:g}M"


def bar(fraction: float, width: int, color: str, glyphs: dict, styles: dict) -> list:
    """A ``width``-cell gauge filled to ``fraction`` in ``color``, padded with the empty glyph, as pieces."""
    eighths = round(max(0.0, min(fraction, 1.0)) * width * 8)
    full, part = divmod(eighths, 8)
    filled = glyphs["fill"] * full + (glyphs["eighths"][part - 1] if part else "")
    return [(filled, color), (glyphs["empty"] * (width - full - (1 if part else 0)), styles["empty"])]


def last_usage(messages: list) -> dict | None:
    """The ``usage`` of the latest message that has one."""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("usage"):
            return message["usage"]
    return None


def build_line(tokens: int, window: int, usage: dict | None, settings, glyphs: dict, styles: dict) -> list:
    """The gauge's pieces for ``tokens`` of ``window`` used and the last reply's ``usage``."""
    fraction = min(tokens / window, 1)
    style = styles["ok"]
    if fraction >= settings["crit"]:
        style = styles["crit"]
    elif fraction >= settings["warn"]:
        style = styles["warn"]
    parts: list = []
    if settings["label"]:
        parts.append((settings["label"] + " ", styles["label"]))
    parts += [glyphs["left"], *bar(fraction, settings["width"], style, glyphs, styles), glyphs["right"]]
    text = []
    if settings["show_numbers"]:
        text.append(f"{tokens / 1000:.1f}k/{format_limit(window)}")
    if settings["show_percent"]:
        text.append(f"{fraction:.0%}")
    if text:
        parts.append((" " + " ".join(text), styles["text"]))
    if settings["show_cache"] and usage:
        inp, read = usage.get("input_tokens") or 0, usage.get("cache_read_tokens") or 0
        if inp > 0 and read > 0:
            parts.append((f" · cache {read / inp:.0%}", styles["cache"]))
    return parts


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    problems, glyphs, styles = check_settings(settings)
    if problems:
        raise ValueError(f"context_gauge settings: {'; '.join(problems)}")

    def render(ctx):
        tokens = ctx.context_tokens
        if tokens is None:
            return None
        return [build_line(tokens, window_of(ctx, settings), last_usage(ctx.messages), settings, glyphs, styles)]

    minimal.register_panel(
        "context_gauge",
        render,
        area=settings["area"],
        order=settings["order"],
        title=settings["title"] or None,
        collapsible=True,
    )
