"""High-contrast dark and light themes, every text colour at least 4.5:1 (WCAG AA). Install it with ``/ext``."""

__version__ = "1.1"
__api__ = "2"
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


def register(minimal):
    for name, palette in THEMES.items():
        minimal.register_theme(name, **palette)
