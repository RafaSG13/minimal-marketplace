"""Catppuccin: Mocha, a soft pastel dark theme with a mauve accent.

Override any colour without editing this file: ``/ext settings themes/catppuccin overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/catppuccin.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.4"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "catppuccin"
PALETTE = {
    "dark": True,
    "background": "#1e1e2e",
    "foreground": "#cdd6f4",
    "accent": "#cba6f7",
    "surface": "#272738",
    "panel": "#303042",
    "secondary": "#89b4fa",
    "success": "#a6e3a1",
    "warning": "#f9e2af",
    "error": "#f38ba8",
    "muted": "#9399b2",
    "dim": "#84889c",
    "border": "#45475a",
    "focus": "#b4befe",
    "user_bg": "#2a2b3c",
    "pending_bg": "#272738",
    "success_bg": "#2a3038",
    "error_bg": "#382b3d",
    "code": "#f5c2e7",
    "model": "#fab387",
    "path": "#94e2d5",
    "status_bg": "#181825",
    "git_clean": "#a6e3a1",
    "git_dirty": "#f9e2af",
    "selection": "#45475a",
    "diff_added": "#a6e3a1",
    "diff_removed": "#f38ba8",
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
