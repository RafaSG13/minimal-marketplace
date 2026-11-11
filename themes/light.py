"""Light: a light editor palette with a blue accent."""

__version__ = "1.1"
__api__ = "1"


def register(minimal):
    minimal.register_theme(
        "light",
        dark=False,
        background="#ffffff",
        foreground="#1f2328",
        accent="#0969da",
        surface="#f6f8fa",
        panel="#e8ecf0",
        secondary="#1b7c83",
        success="#1a7f37",
        warning="#9a6700",
        error="#cf222e",
        muted="#59636e",
        dim="#8c959f",
        border="#d0d7de",
        focus="#0969da",
        user_bg="#f0f3f6",
        pending_bg="#f1f6fd",
        success_bg="#f6f8fa",
        error_bg="#ffebe9",
        code="#8250df",
        model="#8250df",
        path="#1b7c83",
        status_bg="#f6f8fa",
        git_clean="#1a7f37",
        git_dirty="#9a6700",
        selection="#b6e3ff",
        diff_added="#1a7f37",
        diff_removed="#cf222e",
    )
