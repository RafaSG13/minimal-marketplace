"""Dark: a neutral dark editor palette with a blue accent.

Override any colour without editing this file: ``/ext settings themes/dark overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/dark.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.4"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "dark"
PALETTE = {
    "dark": True,
    "background": "#1e2228",
    "foreground": "#c8ccd4",
    "accent": "#61afef",
    "surface": "#262a31",
    "panel": "#30353e",
    "secondary": "#56b6c2",
    "success": "#98c379",
    "warning": "#e5c07b",
    "error": "#e06c75",
    "muted": "#9399a5",
    "dim": "#848c9a",
    "border": "#3a3f4b",
    "focus": "#61afef",
    "user_bg": "#2a2f38",
    "pending_bg": "#232832",
    "success_bg": "#22262d",
    "error_bg": "#33262b",
    "code": "#c678dd",
    "model": "#c678dd",
    "path": "#56b6c2",
    "status_bg": "#1a1d22",
    "git_clean": "#98c379",
    "git_dirty": "#e5c07b",
    "selection": "#3e4451",
    "diff_added": "#98c379",
    "diff_removed": "#e06c75",
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
