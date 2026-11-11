"""Forest: calm dark green theme with moss and sage tones."""

__version__ = "1.1"
__api__ = "1"


def register(minimal):
    minimal.register_theme(
        "forest",
        dark=True,
        background="#1e2a25",
        foreground="#d3c6aa",
        accent="#a7c080",
        surface="#27322c",
        panel="#303a32",
        secondary="#7fbbb3",
        success="#a7c080",
        warning="#dbbc7f",
        error="#e67e80",
        muted="#8a9a8f",
        dim="#66766b",
        border="#3a4a42",
        focus="#83c092",
        user_bg="#2b352e",
        pending_bg="#27322c",
        success_bg="#27322c",
        error_bg="#363430",
        code="#d699b6",
        model="#e69875",
        path="#7fbbb3",
        status_bg="#18221d",
        git_clean="#a7c080",
        git_dirty="#dbbc7f",
        selection="#3d5048",
        diff_added="#a7c080",
        diff_removed="#e67e80",
    )
