"""Gruvbox: retro dark theme with warm, earthy colours and a yellow accent.

Override any colour without editing this file: ``/ext settings themes/gruvbox overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/gruvbox.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.4"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "gruvbox"
PALETTE = {
    "dark": True,
    "background": "#282828",
    "foreground": "#ebdbb2",
    "accent": "#fabd2f",
    "surface": "#32312f",
    "panel": "#3c3a36",
    "secondary": "#83a598",
    "success": "#b8bb26",
    "warning": "#fe8019",
    "error": "#ff5c4a",
    "muted": "#aa9b87",
    "dim": "#9b8e83",
    "border": "#504945",
    "focus": "#83a598",
    "user_bg": "#363532",
    "pending_bg": "#32312f",
    "success_bg": "#353528",
    "error_bg": "#422e2c",
    "code": "#d3869b",
    "model": "#fe8019",
    "path": "#8ec07c",
    "status_bg": "#1d2021",
    "git_clean": "#b8bb26",
    "git_dirty": "#fe8019",
    "selection": "#504945",
    "diff_added": "#b8bb26",
    "diff_removed": "#ff5c4a",
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
