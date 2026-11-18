"""Project badge: a small panel with the project folder's name and its git branch, with a marker when it has changes."""

from __future__ import annotations

import re
import subprocess
import threading
import time
from pathlib import Path

from minimal.api import WIDGET_AREAS, theme

__version__ = "1.1"
__api__ = "2"
__tags__ = ["git", "ui"]

DEFAULTS = {
    "area": "sidebar",
    "width": 30,
    "show_project": True,
    "show_branch": True,
    "show_dirty": True,
    "show_ahead_behind": True,
}
"""``area``: where the panel goes (``top``, ``bottom`` or ``sidebar``); ``width``: columns of a row (the sidebar's
usable width is 34); ``show_*``: which parts to draw."""

GIT = ["git", "-c", "core.fsmonitor=false", "--no-optional-locks"]
"""git without fsmonitor (a repository's config must not run commands) and without taking locks."""

REFRESH = 3.0
"""Seconds between reads of the repository."""


def clean(text: object) -> str:
    """``text`` as one printable line: control characters (escape sequences, newlines) become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def clip(text: str, width: int) -> str:
    """``text`` cut to ``width`` columns with a trailing ``…``."""
    return text if len(text) <= width else text[: max(1, width - 1)].rstrip() + "…"


def check_settings(settings: dict) -> list[str]:
    """What is wrong with ``settings``, one sentence per problem with the fix; empty if usable."""
    problems = []
    if settings["area"] not in WIDGET_AREAS:
        problems.append(f"'area' must be one of {', '.join(WIDGET_AREAS)}, not {settings['area']!r}")
    if settings["width"] < 8:
        problems.append("'width' must be at least 8")
    if not (settings["show_project"] or settings["show_branch"]):
        problems.append("'show_project' and 'show_branch' are both false, so the badge would be empty")
    return problems


def parse_status(status: str) -> dict | None:
    """Branch, ahead/behind and dirty flag from ``git status --porcelain=v1 --branch`` output; None if not a repository's."""
    lines = status.splitlines()
    if not lines or not lines[0].startswith("## "):
        return None
    head = lines[0][3:].removeprefix("No commits yet on ")
    ahead = behind = 0
    if head.endswith("]") and " [" in head:
        head, info = head[:-1].rsplit(" [", 1)
        ahead = int(m.group(1)) if (m := re.search(r"ahead (\d+)", info)) else 0
        behind = int(m.group(1)) if (m := re.search(r"behind (\d+)", info)) else 0
    branch = head.split("...", 1)[0]
    return {
        "branch": "detached" if branch.startswith("HEAD (no branch)") else branch,
        "dirty": len(lines) > 1,
        "ahead": ahead,
        "behind": behind,
    }


def read_git(cwd: str | None) -> dict | None:
    """:func:`parse_status` of the repository containing ``cwd``; None outside one or without git."""
    try:
        result = subprocess.run(
            [*GIT, "status", "--porcelain=v1", "--branch"], cwd=cwd, capture_output=True, text=True, timeout=2
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_status(result.stdout) if result.returncode == 0 else None


def format_badge(cwd: str, git: dict | None, settings: dict) -> list | None:
    """The badge's lines for the folder ``cwd`` and ``git`` (see :func:`parse_status`), or None if nothing to show.

    Rows are at most ``width`` columns. Outside a repository only the project row is drawn.
    """
    width = settings["width"]
    lines: list = []
    if settings["show_project"]:
        lines.append([(clip(clean(Path(cwd).name or cwd), width), "bold accent")])
    if settings["show_branch"] and git is not None:
        marker = " *" if settings["show_dirty"] and git["dirty"] else ""
        counts = ""
        if settings["show_ahead_behind"]:
            counts = (f" ↑{git['ahead']}" if git["ahead"] else "") + (f" ↓{git['behind']}" if git["behind"] else "")
        room = max(1, width - len(marker) - len(counts) - len(theme.BRANCH) - 1)
        row: list = [(f"{theme.BRANCH} {clip(clean(git['branch']), room)}", "muted")]
        if marker:
            row.append((marker, "warning"))
        if counts:
            row.append((counts, "dim"))
        lines.append(row)
    return lines or None


class Badge:
    """The panel: reads the repository on a thread at most every ``REFRESH`` seconds, never in ``render``."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.git: dict | None = None
        self.fetched = 0.0
        self.fetching = False
        self.stopped = False

    def render(self, ctx):
        wants_git = self.settings["show_branch"]
        if wants_git and not self.stopped and not self.fetching and time.monotonic() - self.fetched >= REFRESH:
            self.fetching = True
            threading.Thread(target=self._fetch, args=(ctx.cwd,), daemon=True).start()
        return format_badge(ctx.cwd, self.git if wants_git else None, self.settings)

    def _fetch(self, cwd: str | None) -> None:
        """Runs on a thread: read the repository, then publish the result for the next render."""
        try:
            self.git = read_git(cwd)
        finally:
            self.fetched = time.monotonic()
            self.fetching = False


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS)
    if problems := check_settings(settings):
        raise ValueError(f"project_badge settings: {'; '.join(problems)}")
    badge = Badge(settings)
    minimal.on_dispose(lambda: setattr(badge, "stopped", True))
    minimal.register_panel("project_badge", badge.render, area=settings["area"], interval=REFRESH)
