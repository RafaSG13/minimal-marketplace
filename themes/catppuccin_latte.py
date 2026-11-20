"""Catppuccin Latte: the light Catppuccin flavour, warm and creamy with a mauve accent.

Override any colour without editing this file: ``/ext settings themes/catppuccin_latte overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/catppuccin_latte.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.4"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "catppuccin_latte"
PALETTE = {
    "dark": False,
    "background": "#eff1f5",
    "foreground": "#4c4f69",
    "accent": "#8839ef",
    "surface": "#e7e9ee",
    "panel": "#dfe1e7",
    "secondary": "#1e66f5",
    "success": "#2a7a19",
    "warning": "#9a5b00",
    "error": "#d20f39",
    "muted": "#5d6071",
    "dim": "#686b7e",
    "border": "#bcc0cc",
    "focus": "#657cfd",
    "user_bg": "#e4e6eb",
    "pending_bg": "#e7e9ee",
    "success_bg": "#dbe5df",
    "error_bg": "#ecd6de",
    "code": "#c51e98",
    "model": "#bc4501",
    "path": "#0e7a80",
    "status_bg": "#e6e9ef",
    "git_clean": "#2a7a19",
    "git_dirty": "#9a5b00",
    "selection": "#ccd0da",
    "diff_added": "#2a7a19",
    "diff_removed": "#d20f39",
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
