"""Catppuccin Latte: the light Catppuccin flavour, warm and creamy with a mauve accent."""

__version__ = "1.2"
__api__ = "2"


def register(minimal):
    minimal.register_theme(
        "catppuccin_latte",
        dark=False,
        background="#eff1f5",
        foreground="#4c4f69",
        accent="#8839ef",
        surface="#e7e9ee",
        panel="#dfe1e7",
        secondary="#1e66f5",
        success="#2a7a19",
        warning="#9a5b00",
        error="#d20f39",
        muted="#636678",
        dim="#7c7f93",
        border="#bcc0cc",
        focus="#7287fd",
        user_bg="#e4e6eb",
        pending_bg="#e7e9ee",
        success_bg="#e7e9ee",
        error_bg="#ecd6de",
        code="#ea76cb",
        model="#fe640b",
        path="#0e7a80",
        status_bg="#e6e9ef",
        git_clean="#2a7a19",
        git_dirty="#9a5b00",
        selection="#ccd0da",
        diff_added="#2a7a19",
        diff_removed="#d20f39",
    )
