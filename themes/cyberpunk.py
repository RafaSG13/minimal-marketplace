"""Cyberpunk: near-black violet with neon pink and cyan.

Override any colour without editing this file: ``/ext settings themes/cyberpunk overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/cyberpunk.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.4"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "cyberpunk"
PALETTE = {
    "dark": True,
    "background": "#0b0b1a",
    "foreground": "#e0e6ff",
    "accent": "#ff2a6d",
    "surface": "#161625",
    "panel": "#202131",
    "secondary": "#05d9e8",
    "success": "#00ff9f",
    "warning": "#f9f002",
    "error": "#ff3860",
    "muted": "#8a8fc4",
    "dim": "#7277af",
    "border": "#2a2a55",
    "focus": "#05d9e8",
    "user_bg": "#1a1a2a",
    "pending_bg": "#161625",
    "success_bg": "#0a2126",
    "error_bg": "#281022",
    "code": "#e040fb",
    "model": "#ff2a6d",
    "path": "#05d9e8",
    "status_bg": "#070711",
    "git_clean": "#00ff9f",
    "git_dirty": "#f9f002",
    "selection": "#3a1f4e",
    "diff_added": "#00ff9f",
    "diff_removed": "#ff3860",
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
