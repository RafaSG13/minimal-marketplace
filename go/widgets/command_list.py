"""Command list: every slash command, built-in and from extensions, packed into the sidebar."""

from __future__ import annotations

__version__ = "1.0"
__api__ = "2"

WIDTH = 31
"""Columns of a row; names wrap onto the next row past it."""


def _rows(names: list[str], width: int = WIDTH) -> list[str]:
    """``/name`` for each of ``names``, packed into rows of at most ``width`` columns."""
    rows: list[str] = []
    row = ""
    for name in names:
        word = f"/{name}"
        if row and len(row) + 1 + len(word) > width:
            rows.append(row)
            row = word
        else:
            row = f"{row} {word}" if row else word
    if row:
        rows.append(row)
    return rows


def render(ctx):
    names = sorted(ctx.commands())
    if not names:
        return None
    lines = [[("COMMANDS", "bold muted"), (f"  {len(names)}", "dim")]]
    lines += [[(row, "accent")] for row in _rows(names)]
    return lines


def register(minimal):
    minimal.register_panel("command_list", render, area="sidebar")
