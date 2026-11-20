"""Tokyo Night: deep blue-violet dark theme inspired by Tokyo city lights.

Override any colour without editing this file: ``/ext settings themes/tokyo_night overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/tokyo_night.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.4"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "tokyo_night"
PALETTE = {
    "dark": True,
    "background": "#1a1b26",
    "foreground": "#c0caf5",
    "accent": "#7aa2f7",
    "surface": "#222430",
    "panel": "#2b2c3b",
    "secondary": "#2ac3de",
    "success": "#9ece6a",
    "warning": "#e0af68",
    "error": "#f7768e",
    "muted": "#8790bb",
    "dim": "#7a83ae",
    "border": "#292e42",
    "focus": "#bb9af7",
    "user_bg": "#262734",
    "pending_bg": "#222430",
    "success_bg": "#262b2c",
    "error_bg": "#352632",
    "code": "#bb9af7",
    "model": "#ff9e64",
    "path": "#7dcfff",
    "status_bg": "#16161e",
    "git_clean": "#9ece6a",
    "git_dirty": "#e0af68",
    "selection": "#33467c",
    "diff_added": "#9ece6a",
    "diff_removed": "#f7768e",
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
