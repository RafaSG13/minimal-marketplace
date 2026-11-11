"""Catppuccin: Mocha, a soft pastel dark theme with a mauve accent."""

__version__ = "1.1"
__api__ = "1"


def register(minimal):
    minimal.register_theme(
        "catppuccin",
        dark=True,
        background="#1e1e2e",
        foreground="#cdd6f4",
        accent="#cba6f7",
        surface="#272738",
        panel="#303042",
        secondary="#89b4fa",
        success="#a6e3a1",
        warning="#f9e2af",
        error="#f38ba8",
        muted="#9399b2",
        dim="#6c7086",
        border="#45475a",
        focus="#b4befe",
        user_bg="#2a2b3c",
        pending_bg="#272738",
        success_bg="#272738",
        error_bg="#382b3d",
        code="#f5c2e7",
        model="#fab387",
        path="#94e2d5",
        status_bg="#181825",
        git_clean="#a6e3a1",
        git_dirty="#f9e2af",
        selection="#45475a",
        diff_added="#a6e3a1",
        diff_removed="#f38ba8",
    )
