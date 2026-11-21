"""Solarized Dark: Ethan Schoonover's precision dark theme with a blue accent.

Override any colour without editing this file: ``/ext settings themes/solarized_dark overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/solarized_dark.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "solarized_dark"
PALETTE = {
    "dark": True,
    "background": "#002b36",
    "foreground": "#eee8d5",  # base2 for body text so muted (base0 #839496) and dim read below it; upstream body is base0 itself
    "accent": "#3794d6",  # lifted from #268bd2 to reach 4.5:1 on background
    "surface": "#073642",
    "panel": "#0d4250",
    "secondary": "#2aa198",
    "success": "#859900",
    "warning": "#b58900",
    "error": "#e56563",  # lifted from #dc322f to reach 4.5:1 on background
    "muted": "#839496",
    "dim": "#7e9097",  # adjusted from #657b83 to reach 4.5:1 on background
    "border": "#586e75",
    "focus": "#268bd2",
    "user_bg": "#0b343d",
    "pending_bg": "#073642",
    "success_bg": "#0d3630",
    "error_bg": "#16303a",
    "code": "#dd629e",  # lifted from #d33682 to reach 4.5:1 on background
    "model": "#8488cd",  # lifted from #6c71c4 to reach 4.5:1 on background
    "path": "#2aa198",
    "status_bg": "#00212b",
    "git_clean": "#859900",
    "git_dirty": "#b58900",
    "selection": "#094454",
    "diff_added": "#859900",
    "diff_removed": "#e56563",
}
"""The palette: ``dark`` plus ``background``, ``foreground``, ``accent`` and every optional colour."""
HEX = re.compile(r"#[0-9a-fA-F]{6}")


def register(minimal):
    settings = minimal.declare_settings(
        {"overrides": {}},
        {
            "overrides": {
                "description": "colours to change in this theme: an object of colour name (background, foreground, "
                "accent, surface, panel, muted, dim, ...) -> #rrggbb, e.g. {\"accent\": \"#ff8800\"}"
            }
        },
    )
    palette = dict(PALETTE)
    bad = []
    for key, value in settings["overrides"].items():
        if key == "dark" or key not in palette:
            bad.append(f"unknown colour {str(key)[:40]!r} (use {', '.join(c for c in PALETTE if c != 'dark')})")
        elif not (isinstance(value, str) and HEX.fullmatch(value)):
            bad.append(f"{key} must be #rrggbb, got {str(value)[:40]!r}")
        else:
            palette[key] = value.lower()
    minimal.register_theme(NAME, **palette)
    if bad:  # the theme is registered with the valid overrides; the load error names the rest
        raise ValueError(f"extensions.settings.themes/{NAME}.overrides: {'; '.join(bad)}")
