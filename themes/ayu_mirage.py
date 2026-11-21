"""Ayu Mirage: the soft slate-blue Ayu dark theme with an orange accent.

Override any colour without editing this file: ``/ext settings themes/ayu_mirage overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/ayu_mirage.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "ayu_mirage"
PALETTE = {
    "dark": True,
    "background": "#1f2430",
    "foreground": "#cccac2",
    "accent": "#ffad66",
    "surface": "#242936",
    "panel": "#2d3343",
    "secondary": "#73d0ff",
    "success": "#87d96c",
    "warning": "#ffcc66",
    "error": "#ff6666",
    "muted": "#9a9fae",
    "dim": "#838b9b",  # adjusted from #707a8c to reach 4.5:1 on background
    "border": "#33415e",
    "focus": "#ffcc66",
    "user_bg": "#272c37",
    "pending_bg": "#242936",
    "success_bg": "#293636",
    "error_bg": "#352a35",
    "code": "#dfbfff",
    "model": "#5ccfe6",
    "path": "#73d0ff",
    "status_bg": "#171b24",
    "git_clean": "#87d96c",
    "git_dirty": "#ffcc66",
    "selection": "#33415e",
    "diff_added": "#87d96c",
    "diff_removed": "#ff6666",
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
