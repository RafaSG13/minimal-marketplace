"""Monokai: the vivid Sublime Text dark theme with a green accent.

Override any colour without editing this file: ``/ext settings themes/monokai overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/monokai.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "monokai"
PALETTE = {
    "dark": True,
    "background": "#272822",
    "foreground": "#f8f8f2",
    "accent": "#a6e22e",
    "surface": "#2f302a",
    "panel": "#3e3d32",
    "secondary": "#66d9ef",
    "success": "#a6e22e",
    "warning": "#e6db74",
    "error": "#fa4989",  # lifted from #f92672 to reach 4.5:1 on background
    "muted": "#a59f85",
    "dim": "#938e78",  # adjusted from #908b74 to reach 4.5:1 on background
    "border": "#49483e",
    "focus": "#fd971f",
    "user_bg": "#31322c",
    "pending_bg": "#2f302a",
    "success_bg": "#333a23",
    "error_bg": "#3c2b2c",
    "code": "#ae81ff",
    "model": "#fd971f",
    "path": "#66d9ef",
    "status_bg": "#1e1f1c",
    "git_clean": "#a6e22e",
    "git_dirty": "#e6db74",
    "selection": "#49483e",
    "diff_added": "#a6e22e",
    "diff_removed": "#fa4989",
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
