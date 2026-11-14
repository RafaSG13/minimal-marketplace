"""Callouts: draws GitHub alert blockquotes (> [!NOTE], [!TIP], [!IMPORTANT], [!WARNING], [!CAUTION]) as coloured callouts."""

__version__ = "1.3"
__api__ = "2"

KINDS = {
    "note": ("ⓘ", "Note", "accent"),
    "tip": ("✦", "Tip", "success"),
    "important": ("❖", "Important", "secondary"),
    "warning": ("⚠", "Warning", "warning"),
    "caution": ("✘", "Caution", "error"),
}
"""Alert kind → (icon, title, style name)."""


def render_alert(ctx, block):
    """The alert's title line and the text of its first paragraph, each line behind a coloured bar."""
    icon, title, style = KINDS[block["alert"]]
    return [[(f"{icon} {title}", f"bold {style}")], *[[("▎ ", style), line] for line in block["text"].splitlines()]]


def register(minimal):
    minimal.register_renderer("blockquote:alert", render_alert)
    minimal.append_system_prompt(
        "The terminal UI draws GitHub alert blockquotes (> [!NOTE], > [!TIP], > [!IMPORTANT], > [!WARNING], "
        "> [!CAUTION]) as coloured callouts; use them for notes and warnings the user must not miss."
    )
