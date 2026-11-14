"""Tokyo Night: deep blue-violet dark theme inspired by Tokyo city lights."""

__version__ = "1.2"
__api__ = "2"


def register(minimal):
    minimal.register_theme(
        "tokyo_night",
        dark=True,
        background="#1a1b26",
        foreground="#c0caf5",
        accent="#7aa2f7",
        surface="#222430",
        panel="#2b2c3b",
        secondary="#2ac3de",
        success="#9ece6a",
        warning="#e0af68",
        error="#f7768e",
        muted="#828bb8",
        dim="#646ea0",
        border="#292e42",
        focus="#bb9af7",
        user_bg="#262734",
        pending_bg="#222430",
        success_bg="#222430",
        error_bg="#352632",
        code="#bb9af7",
        model="#ff9e64",
        path="#7dcfff",
        status_bg="#16161e",
        git_clean="#9ece6a",
        git_dirty="#e0af68",
        selection="#33467c",
        diff_added="#9ece6a",
        diff_removed="#f7768e",
    )
