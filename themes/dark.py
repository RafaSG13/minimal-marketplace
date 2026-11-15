"""Dark: a neutral dark editor palette with a blue accent."""

__version__ = "1.2"
__api__ = "2"


def register(minimal):
    minimal.register_theme(
        "dark",
        dark=True,
        background="#1e2228",
        foreground="#c8ccd4",
        accent="#61afef",
        surface="#262a31",
        panel="#30353e",
        secondary="#56b6c2",
        success="#98c379",
        warning="#e5c07b",
        error="#e06c75",
        muted="#848b98",
        dim="#5c6370",
        border="#3a3f4b",
        focus="#61afef",
        user_bg="#2a2f38",
        pending_bg="#232832",
        success_bg="#22262d",
        error_bg="#33262b",
        code="#c678dd",
        model="#c678dd",
        path="#56b6c2",
        status_bg="#1a1d22",
        git_clean="#98c379",
        git_dirty="#e5c07b",
        selection="#3e4451",
        diff_added="#98c379",
        diff_removed="#e06c75",
    )
