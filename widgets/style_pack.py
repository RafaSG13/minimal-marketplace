"""Style pack: coloured gutters for messages and tool calls, a bordered composer and a compact or cozy density, all configurable."""

from __future__ import annotations

from minimal.api import CSS_VARIABLES

__version__ = "2.0"
__api__ = "2.3"
__tags__ = ["ui"]

DENSITIES = ("cozy", "compact")
"""Transcript spacing: "cozy" keeps minimal's padding and gaps, "compact" removes the gaps between blocks."""

GUTTER_STYLES = ("thick", "tall", "heavy", "solid", "wide", "outer", "inner")
"""Textual border types that look right as a one-cell bar on the left edge of a block."""

COMPOSER_BORDERS = ("round", "solid", "heavy", "double", "tall", "none", "default")
"""Border of the composer box. ``none`` draws no border, ``default`` leaves minimal's own (top and bottom lines)."""

COLORS = {
    "user": "accent",
    "tool": "border-muted",
    "success": "success",
    "error": "error",
    "pending": "warning",
    "composer": "border-muted",
    "composer_focus": "border-blue",
}
"""The theme CSS variable (without ``$``) behind each coloured part; a ``colors`` setting overrides entries."""

EXTRA_VARIABLES = ("primary", "border-accent", "modal-overlay")
"""CSS variables of the UI that are no theme colour of their own."""


def variable_name(value: object) -> str | None:
    """``value`` as a CSS variable of the terminal UI (``"accent"``, ``"$border-muted"``, ``"git_dirty"``), or ``None``."""
    if not isinstance(value, str):
        return None
    name = value.strip().lstrip("$")
    key = name.replace("-", "_")
    if key in CSS_VARIABLES:
        return CSS_VARIABLES[key]
    if name in CSS_VARIABLES.values() or name in EXTRA_VARIABLES:
        return name
    return None


def resolve_colors(overrides: dict) -> dict[str, str]:
    """``COLORS`` with ``overrides`` applied, each value a CSS variable name.

    Raises:
        ValueError: for an unknown part or a value that is not a CSS variable of the UI (literal colours are refused:
            the pack follows ``/theme``).
    """
    colors = dict(COLORS)
    for part, value in overrides.items():
        if part not in COLORS:
            raise ValueError(f"style_pack: colors has no part {part!r}; use one of {', '.join(COLORS)}")
        variable = variable_name(value)
        if variable is None:
            raise ValueError(
                f"style_pack: colors.{part} must be a theme CSS variable such as 'accent' or 'border-muted', "
                f"not {value!r}"
            )
        colors[part] = variable
    return colors


def build_css(settings) -> str:
    """The stylesheet for ``settings`` (a mapping with the keys ``register`` declares). Only theme variables."""
    colors = resolve_colors(settings["colors"])
    gutter = settings["gutter_style"]
    rules = []
    if settings["gutters"]:
        rules += [
            f".user {{ border-left: {gutter} ${colors['user']}; }}",
            f".tool {{ border-left: {gutter} ${colors['tool']}; }}",
            f".tool.-success {{ border-left: {gutter} ${colors['success']}; }}",
            f".tool.-error {{ border-left: {gutter} ${colors['error']}; }}",
            f".tool.-pending {{ border-left: {gutter} ${colors['pending']}; }}",
        ]
    rules.append(f"Markdown.assistant {{ padding: 0 1 0 {settings['assistant_indent']}; }}")
    border = settings["composer_border"]
    if border == "none":
        rules.append("#composer { border: none; }")
    elif border != "default":
        rules += [
            f"#composer {{ border: {border} ${colors['composer']}; }}",
            f"#composer:focus-within {{ border: {border} ${colors['composer_focus']}; }}",
        ]
    if settings["density"] == "compact":
        rules += [
            ".user, .tool { padding: 0 2; }",
            ".user, .tool, Markdown.assistant, .output, .error { margin-top: 0; }",
        ]
    return "\n".join(rules) + "\n"


def register(minimal):
    settings = minimal.declare_settings(
        {
            "enabled": True,
            "density": "cozy",
            "gutters": True,
            "gutter_style": "thick",
            "composer_border": "round",
            "assistant_indent": 2,
            "colors": {},
        },
        {
            "enabled": {"description": "Apply the style pack. False registers no stylesheet."},
            "density": {
                "description": "Transcript spacing: cozy keeps minimal's gaps, compact removes the gaps between blocks.",
                "enum": list(DENSITIES),
            },
            "gutters": {"description": "Draw a coloured bar on the left of your messages and of tool calls."},
            "gutter_style": {
                "description": "Textual border type of the gutter bar (thick is a full cell, tall a half cell).",
                "enum": list(GUTTER_STYLES),
            },
            "composer_border": {
                "description": "Border around the prompt box: a style, none for no border, default for minimal's own.",
                "enum": list(COMPOSER_BORDERS),
            },
            "assistant_indent": {
                "description": "Columns of left padding of the model's replies.",
                "min": 0,
                "max": 12,
            },
            "colors": {
                "description": (
                    "Theme CSS variable per part, so /theme recolours it. Parts: "
                    + ", ".join(f"{part} (default {variable})" for part, variable in COLORS.items())
                    + ". Example: {\"user\": \"secondary\", \"composer_focus\": \"accent\"}. Literal colours are refused."
                )
            },
        },
    )
    if not settings["enabled"]:
        return
    minimal.register_css("style_pack", build_css(settings))
