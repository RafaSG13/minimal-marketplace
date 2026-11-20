"""Light: a light editor palette with a blue accent.

Override any colour without editing this file: ``/ext settings themes/light overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/light.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.4"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "light"
PALETTE = {
    "dark": False,
    "background": "#ffffff",
    "foreground": "#1f2328",
    "accent": "#0969da",
    "surface": "#f6f8fa",
    "panel": "#e8ecf0",
    "secondary": "#1b7c83",
    "success": "#1a7f37",
    "warning": "#9a6700",
    "error": "#cf222e",
    "muted": "#59636e",
    "dim": "#6c7682",
    "border": "#d0d7de",
    "focus": "#0969da",
    "user_bg": "#f0f3f6",
    "pending_bg": "#f1f6fd",
    "success_bg": "#f6f8fa",
    "error_bg": "#ffebe9",
    "code": "#8250df",
    "model": "#8250df",
    "path": "#1b7c83",
    "status_bg": "#f6f8fa",
    "git_clean": "#1a7f37",
    "git_dirty": "#9a6700",
    "selection": "#b6e3ff",
    "diff_added": "#1a7f37",
    "diff_removed": "#cf222e",
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
