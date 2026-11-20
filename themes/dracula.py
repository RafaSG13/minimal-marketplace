"""Dracula: the classic purple-and-pink dark theme.

Override any colour without editing this file: ``/ext settings themes/dracula overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/dracula.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.4"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "dracula"
PALETTE = {
    "dark": True,
    "background": "#282a36",
    "foreground": "#f8f8f2",
    "accent": "#bd93f9",
    "surface": "#32343f",
    "panel": "#3d3f49",
    "secondary": "#8be9fd",
    "success": "#50fa7b",
    "warning": "#f1fa8c",
    "error": "#ff6e6e",
    "muted": "#94a0ca",
    "dim": "#8692b9",
    "border": "#44475a",
    "focus": "#ff79c6",
    "user_bg": "#373843",
    "pending_bg": "#32343f",
    "success_bg": "#2c3d3c",
    "error_bg": "#422f3a",
    "code": "#ffb86c",
    "model": "#ff79c6",
    "path": "#8be9fd",
    "status_bg": "#21222c",
    "git_clean": "#50fa7b",
    "git_dirty": "#f1fa8c",
    "selection": "#44475a",
    "diff_added": "#50fa7b",
    "diff_removed": "#ff6e6e",
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
