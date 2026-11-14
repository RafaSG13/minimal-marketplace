"""Dracula: the classic purple-and-pink dark theme."""

__version__ = "1.2"
__api__ = "2"


def register(minimal):
    minimal.register_theme(
        "dracula",
        dark=True,
        background="#282a36",
        foreground="#f8f8f2",
        accent="#bd93f9",
        surface="#32343f",
        panel="#3d3f49",
        secondary="#8be9fd",
        success="#50fa7b",
        warning="#f1fa8c",
        error="#ff5555",
        muted="#8f9bc7",
        dim="#6272a4",
        border="#44475a",
        focus="#ff79c6",
        user_bg="#373843",
        pending_bg="#32343f",
        success_bg="#32343f",
        error_bg="#422f3a",
        code="#ffb86c",
        model="#ff79c6",
        path="#8be9fd",
        status_bg="#21222c",
        git_clean="#50fa7b",
        git_dirty="#f1fa8c",
        selection="#44475a",
        diff_added="#50fa7b",
        diff_removed="#ff5555",
    )
