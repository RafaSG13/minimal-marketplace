"""Amber: omp's dark palette, with a yellow accent."""

__version__ = "1.2"
__api__ = "2"


def register(minimal):
    minimal.register_theme(
        "amber",
        dark=True,
        background="#0f0f14",
        foreground="#cccccc",
        accent="#febc38",
        surface="#1a1a22",
        panel="#25252f",
        secondary="#0088fa",
        success="#89d281",
        warning="#e4c00f",
        error="#fc3a4b",
        muted="#777d88",
        dim="#5f6673",
        border="#3d424a",
        focus="#178fb9",
        user_bg="#221d1a",
        pending_bg="#1d2129",
        success_bg="#161a1f",
        error_bg="#291d1d",
        code="#e5c1ff",
        model="#d787af",
        path="#00afaf",
        status_bg="#16161c",
        git_clean="#5faf5f",
        git_dirty="#d7af5f",
        selection="#31363f",
        diff_added="#89d281",
        diff_removed="#fc3a4b",
    )
