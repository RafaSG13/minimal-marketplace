"""Gruvbox: retro dark theme with warm, earthy colours and a yellow accent."""

__version__ = "1.2"
__api__ = "2"


def register(minimal):
    minimal.register_theme(
        "gruvbox",
        dark=True,
        background="#282828",
        foreground="#ebdbb2",
        accent="#fabd2f",
        surface="#32312f",
        panel="#3c3a36",
        secondary="#83a598",
        success="#b8bb26",
        warning="#fe8019",
        error="#ff5c4a",
        muted="#a89984",
        dim="#7c6f64",
        border="#504945",
        focus="#83a598",
        user_bg="#363532",
        pending_bg="#32312f",
        success_bg="#32312f",
        error_bg="#422e2c",
        code="#d3869b",
        model="#fe8019",
        path="#8ec07c",
        status_bg="#1d2021",
        git_clean="#b8bb26",
        git_dirty="#fe8019",
        selection="#504945",
        diff_added="#b8bb26",
        diff_removed="#ff5c4a",
    )
