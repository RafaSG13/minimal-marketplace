"""GitHub Light: the github.com light palette with a blue accent.

Override any colour without editing this file: ``/ext settings themes/github_light overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/github_light.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "github_light"
PALETTE = {
    "dark": False,
    "background": "#ffffff",
    "foreground": "#1f2328",
    "accent": "#0550ae",
    "surface": "#f6f8fa",
    "panel": "#eaeef2",
    "secondary": "#8250df",
    "success": "#1a7f37",
    "warning": "#9a6700",
    "error": "#cf222e",
    "muted": "#59636e",
    "dim": "#6e7781",
    "border": "#d1d9e0",
    "focus": "#0969da",
    "user_bg": "#f3f4f4",
    "pending_bg": "#f6f8fa",
    "success_bg": "#e8f2eb",
    "error_bg": "#fae8ea",
    "code": "#8250df",
    "model": "#bc4c00",
    "path": "#0969da",
    "status_bg": "#f6f8fa",
    "git_clean": "#1a7f37",
    "git_dirty": "#9a6700",
    "selection": "#ddf4ff",
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
