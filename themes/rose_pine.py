"""Rosé Pine: soft dark theme with muted pastels, rose accent.

Override any colour without editing this file: ``/ext settings themes/rose_pine overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/rose_pine.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "rose_pine"
PALETTE = {
    "dark": True,
    "background": "#191724",
    "foreground": "#e0def4",
    "accent": "#ebbcba",
    "surface": "#1f1d2e",
    "panel": "#26233a",
    "secondary": "#c4a7e7",
    "success": "#9ccfd8",
    "warning": "#f6c177",
    "error": "#eb6f92",
    "muted": "#908caa",
    "dim": "#827f97",  # adjusted from #6e6a86 to reach 4.5:1 on background
    "border": "#403d52",
    "focus": "#524f67",
    "user_bg": "#22202e",
    "pending_bg": "#1f1d2e",
    "success_bg": "#262936",
    "error_bg": "#2e1f2f",
    "code": "#f6c177",
    "model": "#c4a7e7",
    "path": "#9ccfd8",
    "status_bg": "#16141f",
    "git_clean": "#9ccfd8",
    "git_dirty": "#f6c177",
    "selection": "#403d52",
    "diff_added": "#9ccfd8",
    "diff_removed": "#eb6f92",
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
