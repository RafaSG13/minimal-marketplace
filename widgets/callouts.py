"""Callouts: draws GitHub alert blockquotes (> [!NOTE], [!TIP], [!IMPORTANT], [!WARNING], [!CAUTION]) as coloured callouts."""

from __future__ import annotations

import textwrap

from minimal.api import styled_line

__version__ = "1.5"
__api__ = "2.3"
__tags__ = ["ui"]

KINDS = {
    "note": ("ⓘ", "Note", "accent"),
    "tip": ("✦", "Tip", "success"),
    "important": ("❖", "Important", "secondary"),
    "warning": ("⚠", "Warning", "warning"),
    "caution": ("✘", "Caution", "error"),
}
"""Alert kind → (icon, title, style name): the defaults of the ``icons``, ``titles`` and ``styles`` settings."""

MAX_LINE = 2000
"""Characters of one line of an alert kept before it is cut; alert text comes from the model."""


def clean(text: object) -> str:
    """``text`` as one printable line: control characters become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def merged(defaults: dict[str, str], overrides: dict, setting: str) -> dict[str, str]:
    """``defaults`` with the entries of ``overrides`` applied; a kind that is not an alert kind is an error."""
    found = dict(defaults)
    for kind, value in overrides.items():
        if kind not in KINDS:
            raise ValueError(f"callouts: {setting} has no kind {kind!r}; use one of {', '.join(KINDS)}")
        if not isinstance(value, str):
            raise ValueError(f"callouts: {setting}.{kind} must be a string")
        found[kind] = value
    return found


def lines_of(text: str, width: int, bar_width: int, wrap: bool) -> list[str]:
    """The cleaned lines of an alert's text, wrapped to ``width`` minus the bar when ``wrap``."""
    lines = [clean(line)[:MAX_LINE] for line in text.splitlines()]
    if not wrap or width <= bar_width + 8:
        return lines
    out: list[str] = []
    for line in lines:
        out += textwrap.wrap(line, width - bar_width, break_long_words=True, break_on_hyphens=False) or [""]
    return out


def make_renderer(icons: dict[str, str], titles: dict[str, str], styles: dict[str, str], bar: str, wrap: bool):
    def render_alert(ctx, block):
        """The alert's title line and the text of its first paragraph, each line behind a coloured bar."""
        kind = block["alert"]
        if kind not in KINDS:
            return None
        style = styles[kind]
        heading = " ".join(part for part in (icons[kind], titles[kind]) if part)
        body = lines_of(block["text"], block.get("width") or 0, len(bar), wrap)
        head = [[(heading, f"bold {style}")]] if heading else []
        return [*head, *[[(bar, style), line] for line in body]]

    return render_alert


def register(minimal):
    settings = minimal.declare_settings(
        {
            "enabled": True,
            "icons": {},
            "titles": {},
            "styles": {},
            "bar": "▎ ",
            "wrap": True,
            "prompt_hint": True,
        },
        {
            "enabled": {"description": "Draw alert blockquotes as callouts. False leaves minimal's default quote."},
            "icons": {
                "description": (
                    "Icon per alert kind, over the defaults "
                    + ", ".join(f"{kind} {icon}" for kind, (icon, _, _) in KINDS.items())
                    + '. Example: {"note": "i"}; "" for none.'
                )
            },
            "titles": {
                "description": (
                    "Heading text per alert kind, over the defaults "
                    + ", ".join(f"{kind} {title}" for kind, (_, title, _) in KINDS.items())
                    + '. Example: {"warning": "Careful"}; "" for none.'
                )
            },
            "styles": {
                "description": (
                    "Style per alert kind (a name such as accent or error, a $theme_colour or #rrggbb), over the defaults "
                    + ", ".join(f"{kind} {style}" for kind, (_, _, style) in KINDS.items())
                    + "."
                )
            },
            "bar": {"description": "Text drawn at the start of every line of a callout; \"\" for none."},
            "wrap": {"description": "Wrap long lines to the transcript width, keeping the bar on every row."},
            "prompt_hint": {
                "description": "Tell the model in the system prompt that alerts are drawn as callouts (costs about 50 tokens)."
            },
        },
    )
    if not settings["enabled"]:
        return
    icons = merged({k: v[0] for k, v in KINDS.items()}, settings["icons"], "icons")
    titles = merged({k: v[1] for k, v in KINDS.items()}, settings["titles"], "titles")
    styles = merged({k: v[2] for k, v in KINDS.items()}, settings["styles"], "styles")
    for kind, style in styles.items():
        styled_line([("x", style), ("x", f"bold {style}")])  # ValueError on an unknown style name
    minimal.register_renderer("blockquote:alert", make_renderer(icons, titles, styles, settings["bar"], settings["wrap"]))
    if settings["prompt_hint"]:
        minimal.append_system_prompt(
            "The terminal UI draws GitHub alert blockquotes (> [!NOTE], > [!TIP], > [!IMPORTANT], > [!WARNING], "
            "> [!CAUTION]) as coloured callouts; use them for notes and warnings the user must not miss."
        )
