"""GitHub Dark: the github.com dark palette with a blue accent.

Override any colour without editing this file: ``/ext settings themes/github_dark overrides '{"accent": "#ff8800"}'``
(``extensions.settings.themes/github_dark.overrides`` in settings.json: colour name -> ``#rrggbb``). The checked-in
palette passes ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "github_dark"
PALETTE = {
    "dark": True,
    "background": "#0d1117",
    "foreground": "#e6edf3",
    "accent": "#4493f8",
    "surface": "#151b23",
    "panel": "#212830",
    "secondary": "#a371f7",
    "success": "#3fb950",
    "warning": "#d29922",
    "error": "#f85149",
    "muted": "#9198a1",
    "dim": "#757d87",  # adjusted from #6e7681 to reach 4.5:1 on background
    "border": "#3d444d",
    "focus": "#1f6feb",
    "user_bg": "#171c22",
    "pending_bg": "#151b23",
    "success_bg": "#12211c",
    "error_bg": "#24171c",
    "code": "#ff7b72",
    "model": "#d2a8ff",
    "path": "#79c0ff",
    "status_bg": "#010409",
    "git_clean": "#3fb950",
    "git_dirty": "#d29922",
    "selection": "#1f3a5f",
    "diff_added": "#3fb950",
    "diff_removed": "#f85149",
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
