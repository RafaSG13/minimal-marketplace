"""One Dark: Atom's classic dark theme with a cyan accent.

Override any colour without editing this file: ``/ext settings themes/one_dark overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/one_dark.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "one_dark"
PALETTE = {
    "dark": True,
    "background": "#282c34",
    "foreground": "#abb2bf",
    "accent": "#56b6c2",
    "surface": "#2c313a",
    "panel": "#353b45",
    "secondary": "#61afef",
    "success": "#98c379",
    "warning": "#e5c07b",
    "error": "#e17079",  # lifted from #e06c75 to reach 4.5:1 on background
    "muted": "#9099a8",
    "dim": "#8c939f",  # adjusted from #7f8794 to reach 4.5:1 on background
    "border": "#3e4451",
    "focus": "#528bff",
    "user_bg": "#2e323a",
    "pending_bg": "#2c313a",
    "success_bg": "#333b3a",
    "error_bg": "#3a323a",
    "code": "#c678dd",
    "model": "#d19a66",
    "path": "#61afef",
    "status_bg": "#21252b",
    "git_clean": "#98c379",
    "git_dirty": "#e5c07b",
    "selection": "#3e4451",
    "diff_added": "#98c379",
    "diff_removed": "#e17079",
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
