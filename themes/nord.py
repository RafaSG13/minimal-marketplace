"""Nord: arctic, north-bluish dark theme."""

__version__ = "1.1"
__api__ = "1"


def register(minimal):
    minimal.register_theme(
        "nord",
        dark=True,
        background="#2e3440",
        foreground="#d8dee9",
        accent="#88c0d0",
        surface="#363c48",
        panel="#3f4551",
        secondary="#81a1c1",
        success="#a3be8c",
        warning="#ebcb8b",
        error="#df8088",
        muted="#9aa4bb",
        dim="#7d88a0",
        border="#434c5e",
        focus="#5e81ac",
        user_bg="#3a404c",
        pending_bg="#363c48",
        success_bg="#363c48",
        error_bg="#433d49",
        code="#b48ead",
        model="#8fbcbb",
        path="#81a1c1",
        status_bg="#272c36",
        git_clean="#a3be8c",
        git_dirty="#ebcb8b",
        selection="#434c5e",
        diff_added="#a3be8c",
        diff_removed="#df8088",
    )
