"""Amber: omp's dark palette, with a yellow accent.

Override any colour without editing this file: ``/ext settings themes/amber overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/amber.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.4"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "amber"
PALETTE = {
    "dark": True,
    "background": "#0f0f14",
    "foreground": "#cccccc",
    "accent": "#febc38",
    "surface": "#1a1a22",
    "panel": "#25252f",
    "secondary": "#0088fa",
    "success": "#89d281",
    "warning": "#e4c00f",
    "error": "#fc3a4b",
    "muted": "#858a94",
    "dim": "#757e8d",
    "border": "#3d424a",
    "focus": "#178fb9",
    "user_bg": "#221d1a",
    "pending_bg": "#1d2129",
    "success_bg": "#161a1f",
    "error_bg": "#291d1d",
    "code": "#e5c1ff",
    "model": "#d787af",
    "path": "#00afaf",
    "status_bg": "#16161c",
    "git_clean": "#5faf5f",
    "git_dirty": "#d7af5f",
    "selection": "#31363f",
    "diff_added": "#89d281",
    "diff_removed": "#fc3a4b",
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
