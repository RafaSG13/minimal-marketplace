"""Forest: calm dark green theme with moss and sage tones.

Override any colour without editing this file: ``/ext settings themes/forest overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/forest.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.4"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "forest"
PALETTE = {
    "dark": True,
    "background": "#1e2a25",
    "foreground": "#d3c6aa",
    "accent": "#a7c080",
    "surface": "#27322c",
    "panel": "#303a32",
    "secondary": "#7fbbb3",
    "success": "#a7c080",
    "warning": "#dbbc7f",
    "error": "#e67e80",
    "muted": "#92a197",
    "dim": "#839488",
    "border": "#3a4a42",
    "focus": "#83c092",
    "user_bg": "#2b352e",
    "pending_bg": "#27322c",
    "success_bg": "#2a382d",
    "error_bg": "#363430",
    "code": "#d699b6",
    "model": "#e69875",
    "path": "#7fbbb3",
    "status_bg": "#18221d",
    "git_clean": "#a7c080",
    "git_dirty": "#dbbc7f",
    "selection": "#3d5048",
    "diff_added": "#a7c080",
    "diff_removed": "#e67e80",
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
