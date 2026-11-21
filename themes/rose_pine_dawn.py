"""Rosé Pine Dawn: the light Rosé Pine, warm parchment with a pine accent.

Override any colour without editing this file: ``/ext settings themes/rose_pine_dawn overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/rose_pine_dawn.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "rose_pine_dawn"
PALETTE = {
    "dark": False,
    "background": "#faf4ed",
    "foreground": "#575279",
    "accent": "#286983",
    "surface": "#fffaf3",
    "panel": "#f2e9e1",
    "secondary": "#907aa9",
    "success": "#467881",  # darkened from #56949f to reach 4.5:1 on background
    "warning": "#986622",  # darkened from #ea9d34 to reach 4.5:1 on background
    "error": "#a45a6f",  # darkened from #b4637a to reach 4.5:1 on background
    "muted": "#6f6b87",  # adjusted from #797593 to read above dim and reach 4.5:1 on background
    "dim": "#726e7c",  # adjusted from #9893a5 to reach 4.5:1 on background
    "border": "#dfdad9",
    "focus": "#cecacd",
    "user_bg": "#f1ebe7",
    "pending_bg": "#fffaf3",
    "success_bg": "#e8e7e2",
    "error_bg": "#f1e4e0",
    "code": "#9d5f5c",  # darkened from #d7827e to reach 4.5:1 on background
    "model": "#7a6890",  # darkened from #907aa9 to reach 4.5:1 on background
    "path": "#56949f",
    "status_bg": "#f4ede8",
    "git_clean": "#467881",
    "git_dirty": "#986622",
    "selection": "#dfdad9",
    "diff_added": "#467881",
    "diff_removed": "#a45a6f",
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
