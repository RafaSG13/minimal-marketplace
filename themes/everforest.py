"""Everforest: comfortable green-tinted dark theme with warm, low-glare colours.

Override any colour without editing this file: ``/ext settings themes/everforest overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/everforest.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "everforest"
PALETTE = {
    "dark": True,
    "background": "#2d353b",
    "foreground": "#d3c6aa",
    "accent": "#83c092",
    "surface": "#343f44",
    "panel": "#3d484d",
    "secondary": "#7fbbb3",
    "success": "#a7c080",
    "warning": "#dbbc7f",
    "error": "#e67e80",
    "muted": "#9da9a0",
    "dim": "#949f97",  # adjusted from #859289 to reach 4.5:1 on background
    "border": "#475258",
    "focus": "#a7c080",
    "user_bg": "#353c40",
    "pending_bg": "#343f44",
    "success_bg": "#394241",
    "error_bg": "#3f3c41",
    "code": "#d699b6",
    "model": "#e69875",
    "path": "#7fbbb3",
    "status_bg": "#232a2e",
    "git_clean": "#a7c080",
    "git_dirty": "#dbbc7f",
    "selection": "#543a48",
    "diff_added": "#a7c080",
    "diff_removed": "#e67e80",
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
