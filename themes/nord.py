"""Nord: arctic, north-bluish dark theme.

Override any colour without editing this file: ``/ext settings themes/nord overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/nord.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.4"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "nord"
PALETTE = {
    "dark": True,
    "background": "#2e3440",
    "foreground": "#d8dee9",
    "accent": "#88c0d0",
    "surface": "#363c48",
    "panel": "#3f4551",
    "secondary": "#81a1c1",
    "success": "#a3be8c",
    "warning": "#ebcb8b",
    "error": "#e49299",
    "muted": "#a3acc1",
    "dim": "#959eb1",
    "border": "#434c5e",
    "focus": "#5e81ac",
    "user_bg": "#3a404c",
    "pending_bg": "#363c48",
    "success_bg": "#394047",
    "error_bg": "#433d49",
    "code": "#b793b0",
    "model": "#8fbcbb",
    "path": "#81a1c1",
    "status_bg": "#272c36",
    "git_clean": "#a3be8c",
    "git_dirty": "#ebcb8b",
    "selection": "#434c5e",
    "diff_added": "#a3be8c",
    "diff_removed": "#e49299",
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
