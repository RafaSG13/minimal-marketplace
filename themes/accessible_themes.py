"""High-contrast dark and light themes, every text colour at least 4.5:1 (WCAG AA). Install it with ``/ext``.

Override a colour without editing this file, per theme:
``/ext settings themes/accessible_themes overrides '{"high_contrast_dark": {"accent": "#ff8800"}}'``
(``extensions.settings.themes/accessible_themes.overrides`` in settings.json: theme name -> colour name ->
``#rrggbb``). The shipped palettes pass ``scripts/check_items.py``' contrast gate; overrides are yours to keep readable.
"""

import re

__version__ = "1.2"
__api__ = "2.3"
__tags__ = ["theme"]

THEMES = {
    "high_contrast_dark": {
        "dark": True,
        "background": "#000000",
        "foreground": "#ffffff",
        "accent": "#6cc4ff",
        "surface": "#0d0d0d",
        "panel": "#1a1a1a",
        "secondary": "#b9a6ff",
        "success": "#5cf08a",
        "warning": "#ffd24d",
        "error": "#ff8080",
        "muted": "#d0d0d0",
        "dim": "#ababab",
        "border": "#8a8a8a",
        "focus": "#ffe14d",
        "user_bg": "#1f1f1f",
        "pending_bg": "#141414",
        "success_bg": "#06240f",
        "error_bg": "#2e0808",
        "code": "#ffa8e8",
        "model": "#7fe3d4",
        "path": "#b9a6ff",
        "status_bg": "#141414",
        "git_clean": "#5cf08a",
        "git_dirty": "#ffd24d",
        "selection": "#1f4f99",
        "diff_added": "#5cf08a",
        "diff_removed": "#ff8080",
    },
    "high_contrast_light": {
        "dark": False,
        "background": "#ffffff",
        "foreground": "#000000",
        "accent": "#0033b3",
        "surface": "#f2f2f2",
        "panel": "#e6e6e6",
        "secondary": "#5a1fa8",
        "success": "#006b1f",
        "warning": "#7a4a00",
        "error": "#b00020",
        "muted": "#3d3d3d",
        "dim": "#595959",
        "border": "#6b6b6b",
        "focus": "#0033b3",
        "user_bg": "#ededed",
        "pending_bg": "#f5f5f5",
        "success_bg": "#e0f5e6",
        "error_bg": "#fde0e0",
        "code": "#8a0f6e",
        "model": "#0a5a7a",
        "path": "#5a1fa8",
        "status_bg": "#ececec",
        "git_clean": "#006b1f",
        "git_dirty": "#7a4a00",
        "selection": "#a8cdff",
        "diff_added": "#006b1f",
        "diff_removed": "#b00020",
    },
}
"""The palettes by theme name; the test measures the contrast of every text colour against its backgrounds."""


HEX = re.compile(r"#[0-9a-fA-F]{6}")


def register(minimal):
    settings = minimal.declare_settings(
        {"overrides": {}},
        {
            "overrides": {
                "description": "colours to change, per theme: an object of theme name (high_contrast_dark, "
                'high_contrast_light) -> colour name -> #rrggbb, e.g. {"high_contrast_dark": {"accent": "#ff8800"}}'
            }
        },
    )
    bad = []
    changes = {}
    for name, colors in settings["overrides"].items():
        if name not in THEMES:
            bad.append(f"unknown theme {str(name)[:40]!r} (use {', '.join(THEMES)})")
        elif not isinstance(colors, dict):
            bad.append(f"{str(name)[:40]} must be an object of colour -> #rrggbb")
        else:
            changes[name] = colors
    palettes = {name: dict(palette) for name, palette in THEMES.items()}
    for name, colors in changes.items():
        for key, value in colors.items():
            if key == "dark" or key not in palettes[name]:
                bad.append(f"{name}: unknown colour {str(key)[:40]!r}")
            elif not (isinstance(value, str) and HEX.fullmatch(value)):
                bad.append(f"{name}: {key} must be #rrggbb, got {str(value)[:40]!r}")
            else:
                palettes[name][key] = value.lower()
    for name, palette in palettes.items():
        minimal.register_theme(name, **palette)
    if bad:  # the themes are registered with the valid overrides; the load error names the rest
        raise ValueError(f"extensions.settings.themes/accessible_themes.overrides: {'; '.join(bad)}")
