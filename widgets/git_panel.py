"""Git panel: branch, ahead/behind, staged/unstaged/untracked counts and per-file diff stats."""

from __future__ import annotations

import re
import subprocess
import threading
import time

from minimal.api import theme

__version__ = "1.2"
__api__ = "1.3"

ROWS = 8
"""Most changed files listed."""

NAME_WIDTH = 18
"""Columns for a file name; longer names lose their start."""

GIT = ["git", "-c", "core.fsmonitor=false", "--no-optional-locks"]
"""git without fsmonitor (a repository's config must not run commands) and without taking locks."""


def _diff_bar(added: int, removed: int, cells: int = 5) -> list:
    """Pieces for ``cells`` blocks split between added (green) and removed (red) lines."""
    total = added + removed
    if not total:
        return [("·" * cells, "dim")]
    plus = round(cells * added / total)
    return [("█" * plus, "diff_added"), ("█" * (cells - plus), "diff_removed")]


def _git(args: list[str], cwd: str | None) -> str | None:
    """stdout of ``git args`` in ``cwd``, or None if it fails."""
    try:
        result = subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _parse(status: str, numstat: str | None) -> dict:
    """Branch, ahead/behind, change counts and ``(path, added, removed)`` rows (counts None for binaries)."""
    data = {"branch": "?", "ahead": 0, "behind": 0, "staged": 0, "unstaged": 0, "untracked": 0, "files": []}
    for line in status.splitlines():
        if line.startswith("## "):
            head = line[3:].removeprefix("No commits yet on ")
            if head.endswith("]") and " [" in head:
                head, info = head[:-1].rsplit(" [", 1)
                if ahead := re.search(r"ahead (\d+)", info):
                    data["ahead"] = int(ahead.group(1))
                if behind := re.search(r"behind (\d+)", info):
                    data["behind"] = int(behind.group(1))
            data["branch"] = head.split("...", 1)[0]
        elif line[:2] == "??":
            data["untracked"] += 1
        elif len(line) >= 2:
            data["staged"] += line[0] not in " ?"
            data["unstaged"] += line[1] != " "
    for line in (numstat or "").splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            added, removed, path = parts
            binary = added == "-" or removed == "-"
            data["files"].append((path, None if binary else int(added), None if binary else int(removed)))
    return data


class GitPanel:
    """Sidebar panel: the repository's branch, change counts and per-file diff stats."""

    def __init__(self) -> None:
        self.data: dict | None = None
        self.fetched = 0.0
        self.fetching = False

    def render(self, ctx):
        if not self.fetching and time.monotonic() - self.fetched >= 2:
            self.fetching = True
            threading.Thread(target=self._fetch, args=(ctx.cwd,), daemon=True).start()
        data = self.data
        if data is None:
            return None
        lines = [
            [
                ("GIT", "bold muted"),
                (f"  {theme.BRANCH} {data['branch']} ↑{data['ahead']} ↓{data['behind']}", "dim"),
            ],
            [(f"staged {data['staged']} · unstaged {data['unstaged']} · untracked {data['untracked']}", "muted")],
        ]
        for path, added, removed in data["files"][:ROWS]:
            name = path if len(path) <= NAME_WIDTH else "…" + path[-(NAME_WIDTH - 1) :]
            row = [f"{name.ljust(NAME_WIDTH)} "]
            if added is None:
                row.append(("bin", "dim"))
            else:
                row += [
                    (f"+{added}", "diff_added"),
                    " ",
                    (f"−{removed}", "diff_removed"),
                    " ",
                    *_diff_bar(added, removed),
                ]
            lines.append(row)
        return lines

    def _fetch(self, cwd: str | None) -> None:
        """Runs on a thread: read the repository, then publish the result for the next render."""
        try:
            status = _git(["status", "--porcelain=v1", "--branch"], cwd)
            self.data = None if status is None else _parse(status, _git(["diff", "--numstat", "HEAD"], cwd))
        finally:
            self.fetched = time.monotonic()
            self.fetching = False


def register(minimal):
    panel = GitPanel()
    minimal.register_panel("git_panel", panel.render, area="sidebar", interval=2.0)
