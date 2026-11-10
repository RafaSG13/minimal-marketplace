"""Cyberpunk: near-black violet with neon pink and cyan."""

__version__ = "1.0"


def register(minimal):
    minimal.register_theme(
        "cyberpunk",
        dark=True,
        background="#0b0b1a",
        foreground="#e0e6ff",
        accent="#ff2a6d",
        surface="#161625",
        panel="#202131",
        secondary="#05d9e8",
        success="#00ff9f",
        warning="#f9f002",
        error="#ff3860",
        muted="#8a8fc4",
        dim="#5b60a0",
        border="#2a2a55",
        focus="#05d9e8",
        user_bg="#1a1a2a",
        pending_bg="#161625",
        success_bg="#161625",
        error_bg="#281022",
        code="#e040fb",
        model="#ff2a6d",
        path="#05d9e8",
        status_bg="#070711",
        git_clean="#00ff9f",
        git_dirty="#f9f002",
        selection="#3a1f4e",
        diff_added="#00ff9f",
        diff_removed="#ff3860",
    )
