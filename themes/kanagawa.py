"""Kanagawa: dark theme inspired by Hokusai's Great Wave, with ink and wave tones.

Override any colour without editing this file: ``/ext settings themes/kanagawa overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/kanagawa.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "kanagawa"
PALETTE = {
    "dark": True,
    "background": "#1f1f28",
    "foreground": "#dcd7ba",
    "accent": "#957fb8",
    "surface": "#2a2a37",
    "panel": "#363646",
    "secondary": "#7e9cd8",
    "success": "#98bb6c",
    "warning": "#e6c384",
    "error": "#e46876",
    "muted": "#938aa9",
    "dim": "#898881",  # adjusted from #727169 to reach 4.5:1 on background
    "border": "#54546d",
    "focus": "#7e9cd8",
    "user_bg": "#28282f",
    "pending_bg": "#2a2a37",
    "success_bg": "#2b2e2e",
    "error_bg": "#32262f",
    "code": "#d27e99",
    "model": "#ffa066",
    "path": "#7fb4ca",
    "status_bg": "#16161d",
    "git_clean": "#98bb6c",
    "git_dirty": "#e6c384",
    "selection": "#2d4f67",
    "diff_added": "#98bb6c",
    "diff_removed": "#e46876",
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
