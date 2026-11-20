"""Git panel: project, branch, ahead/behind, change counts and changed files with diff stats; every part is optional."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from minimal.api import styled_line, theme

__version__ = "2.0"
__api__ = "2.3"
__tags__ = ["git", "ui"]

GLYPHS = {
    "branch": theme.BRANCH,
    "ahead": "↑",
    "behind": "↓",
    "dirty": "*",
    "added": "+",
    "removed": "−",
    "bar": "█",
    "empty": "·",
    "binary": "bin",
    "ellipsis": "…",
}
"""Every piece of text the panel draws besides the repository's own names (the ``glyphs`` setting overrides entries)."""

STYLES = {
    "project": "bold accent",
    "branch": "dim",
    "dirty": "warning",
    "arrows": "dim",
    "counts": "muted",
    "name": "",
    "added": "diff_added",
    "removed": "diff_removed",
    "binary": "dim",
    "empty": "dim",
    "status_new": "success",
    "status_modified": "warning",
    "status_deleted": "error",
    "status_untracked": "dim",
    "status_conflict": "bold error",
}
"""Style of every part (``styles`` overrides entries); a style is the names of :data:`minimal.api.STYLES`,
``$theme_colour`` or ``#rrggbb``."""

DEFAULTS = {
    "enabled": True,
    "title": "GIT",
    "area": "sidebar",
    "order": 0,
    "width": 30,
    "rows": 8,
    "name_width": 18,
    "refresh": 2.0,
    "show_project": False,
    "show_branch": True,
    "show_dirty": True,
    "arrows": "always",
    "show_counts": True,
    "show_files": True,
    "show_stats": True,
    "show_status": False,
    "list_untracked": False,
    "bar_width": 5,
    "glyphs": {},
    "styles": {},
}

SCHEMA = {
    "enabled": {"description": "Show the panel; false registers nothing."},
    "title": {"description": "The heading above the panel; empty for none (collapsible by click when set)."},
    "area": {
        "description": "Where the panel sits (the user's /ui move overrides it).",
        "enum": ["top", "bottom", "sidebar", "left", "footer"],
    },
    "order": {"description": "Position among the area's panels and widgets, lower first."},
    "width": {"description": "Columns of the project and branch rows (the sidebar's usable width is 34).", "min": 8},
    "rows": {"description": "Most changed files listed.", "min": 0, "max": 50},
    "name_width": {"description": "Columns of a file name; a longer one loses its start.", "min": 4, "max": 80},
    "refresh": {
        "description": "Seconds between reads of the per-file +/- counts (branch and counts come from minimal's shared "
        "git poller, set by the git.refresh setting).",
        "min": 0.5,
    },
    "show_project": {"description": "A first row with the project folder's name."},
    "show_branch": {"description": "A row with the branch, its dirty marker and the ahead/behind arrows."},
    "show_dirty": {"description": "Mark the branch with the dirty glyph when files are changed."},
    "arrows": {
        "description": "Ahead/behind arrows after the branch: always, only the non-zero ones, or never.",
        "enum": ["always", "changes", "never"],
    },
    "show_counts": {"description": "The staged / unstaged / untracked counts row."},
    "show_files": {"description": "List the changed files."},
    "show_stats": {"description": "Lines added and removed per listed file, with a small bar."},
    "show_status": {"description": "Prefix each listed file with its git status letter (M, A, D, ?, U)."},
    "list_untracked": {"description": "Also list untracked files (they have no diff stats)."},
    "bar_width": {"description": "Cells of the added/removed bar; 0 hides it.", "min": 0, "max": 20},
    "glyphs": {
        "description": "Override drawn text: " + ", ".join(GLYPHS) + ", e.g. {\"ahead\": \"+\", \"branch\": \"@\"}."
    },
    "styles": {
        "description": "Override a part's style: " + ", ".join(STYLES) + ", e.g. {\"project\": \"bold $secondary\"}."
    },
}
"""Description, enum and range of each setting (``/ext settings widgets/git_panel``)."""

GIT = ["git", "-c", "core.fsmonitor=false", "--no-optional-locks"]
"""git without fsmonitor (a repository's config must not run commands) and without taking locks."""


def clean(text: object) -> str:
    """``text`` as one printable line: control characters (escape sequences, newlines) become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def clip(text: str, width: int, ellipsis: str = "…") -> str:
    """``text`` cut to ``width`` columns with a trailing ``ellipsis``."""
    return text if len(text) <= width else text[: max(1, width - len(ellipsis))].rstrip() + ellipsis


def merged(name: str, given: dict, defaults: dict, problems: list[str], style: bool = False) -> dict:
    """``defaults`` with the entries of ``given`` laid over them; each bad entry is added to ``problems``."""
    result = dict(defaults)
    for key, value in given.items():
        if key not in defaults:
            problems.append(f"'{name}' has no entry {key!r} (known: {', '.join(defaults)})")
        elif not isinstance(value, str):
            problems.append(f"'{name}.{key}' must be text, not {value!r}")
        else:
            if style:
                try:
                    styled_line((" ", value))
                except ValueError as error:
                    problems.append(f"'{name}.{key}': {error}")
                    continue
            result[key] = value
    return result


def check_settings(settings) -> tuple[list[str], dict, dict]:
    """``(problems, glyphs, styles)``: one sentence per problem with the fix, and the dicts over the defaults."""
    problems: list[str] = []
    glyphs = merged("glyphs", settings["glyphs"], GLYPHS, problems)
    styles = merged("styles", settings["styles"], STYLES, problems, style=True)
    if not (settings["show_project"] or settings["show_branch"] or settings["show_counts"] or settings["show_files"]):
        problems.append("every 'show_*' part is false, so the panel would be empty")
    return problems, glyphs, styles


def read_numstat(cwd: str | None) -> dict[str, tuple[int, int] | None]:
    """``{path: (added, removed)}`` of the files changed since HEAD (``None`` for a binary); ``{}`` on failure."""
    try:
        result = subprocess.run(
            [*GIT, "diff", "--numstat", "--no-renames", "-z", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    stats: dict[str, tuple[int, int] | None] = {}
    if result.returncode == 0:
        for record in result.stdout.split("\0"):
            parts = record.split("\t", 2)
            if len(parts) == 3:
                added, removed, path = parts
                stats[path] = None if "-" in (added, removed) else (int(added), int(removed))
    return stats


class Stats:
    """The per-file +/- counts, read on a thread every ``refresh`` seconds while the panel is drawn.

    The thread starts at the first draw (never in the middle of one) and asks for a redraw only when the counts changed.
    """

    def __init__(self, refresh: float, read=read_numstat) -> None:
        self.refresh = refresh
        self.read = read
        self.value: dict[str, tuple[int, int] | None] = {}
        self.thread: threading.Thread | None = None
        self.stopped = threading.Event()

    def start(self, ctx) -> None:
        """Start the thread once; a second call, or one after :meth:`stop`, does nothing."""
        if self.thread is None and not self.stopped.is_set():
            self.thread = threading.Thread(target=self._run, args=(ctx,), name="git-panel-stats", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stopped.set()

    def _run(self, ctx) -> None:
        while not self.stopped.is_set():
            info = ctx.git()
            stats = self.read(ctx.cwd) if info is not None and info.dirty else {}
            if stats != self.value and not self.stopped.is_set():
                self.value = stats
                ctx.invalidate()
            self.stopped.wait(self.refresh)


def _kind(code: str) -> str:
    """The style key of a git status ``code``."""
    if code == "??":
        return "status_untracked"
    if "U" in code or code in ("AA", "DD"):
        return "status_conflict"
    if "D" in code:
        return "status_deleted"
    if "A" in code:
        return "status_new"
    return "status_modified"


def diff_bar(added: int, removed: int, cells: int, glyphs: dict, styles: dict) -> list:
    """Pieces for ``cells`` blocks split between added and removed lines; nothing for no cells."""
    if cells <= 0:
        return []
    total = added + removed
    if not total:
        return [(glyphs["empty"] * cells, styles["empty"])]
    plus = round(cells * added / total)
    return [(glyphs["bar"] * plus, styles["added"]), (glyphs["bar"] * (cells - plus), styles["removed"])]


def build_lines(info, cwd: str, stats: dict, settings, glyphs: dict, styles: dict) -> list | None:
    """The panel's lines for the repository ``info`` (:class:`~minimal.api.GitInfo`); None when nothing is shown."""
    width, ellipsis = settings["width"], glyphs["ellipsis"]
    lines: list = []
    if settings["show_project"]:
        lines.append([(clip(clean(Path(cwd).name or cwd), width, ellipsis), styles["project"])])
    if settings["show_branch"]:
        branch = clean(info.branch) if info.branch else "detached"
        marker = f" {glyphs['dirty']}" if settings["show_dirty"] and info.dirty and glyphs["dirty"] else ""
        arrows = ""
        if settings["arrows"] != "never":
            always = settings["arrows"] == "always"
            if always or info.ahead:
                arrows += f" {glyphs['ahead']}{info.ahead}"
            if always or info.behind:
                arrows += f" {glyphs['behind']}{info.behind}"
        room = max(1, width - len(marker) - len(arrows) - len(glyphs["branch"]) - 1)
        row: list = [(f"{glyphs['branch']} {clip(branch, room, ellipsis)}", styles["branch"])]
        if marker:
            row.append((marker, styles["dirty"]))
        if arrows:
            row.append((arrows, styles["arrows"]))
        lines.append(row)
    if settings["show_counts"]:
        lines.append(
            [(f"staged {info.staged} · unstaged {info.unstaged} · untracked {info.untracked}", styles["counts"])]
        )
    if settings["show_files"]:
        name_width = settings["name_width"]
        files = [(c, p) for c, p in info.files if settings["list_untracked"] or c != "??"]
        for code, path in files[: settings["rows"]]:
            row = []
            if settings["show_status"]:
                row.append((f"{(code[0] if code[0] != ' ' else code[1])} ", styles[_kind(code)]))
            name = clean(path)
            name = name if len(name) <= name_width else ellipsis + name[-(name_width - len(ellipsis)) :]
            row.append((f"{name.ljust(name_width)} ", styles["name"]))
            if settings["show_stats"] and path in stats:
                counts = stats[path]
                if counts is None:
                    row.append((glyphs["binary"], styles["binary"]))
                else:
                    added, removed = counts
                    row += [
                        (f"{glyphs['added']}{added}", styles["added"]),
                        " ",
                        (f"{glyphs['removed']}{removed}", styles["removed"]),
                    ]
                    if settings["bar_width"]:
                        row += [" ", *diff_bar(added, removed, settings["bar_width"], glyphs, styles)]
            lines.append(row)
    return lines or None


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    problems, glyphs, styles = check_settings(settings)
    if problems:
        raise ValueError(f"git_panel settings: {'; '.join(problems)}")
    stats = Stats(settings["refresh"])
    minimal.on_dispose(stats.stop)

    def render(ctx):
        info = ctx.git()
        if info is None:
            return None
        if settings["show_files"] and settings["show_stats"]:
            stats.start(ctx)
        return build_lines(info, ctx.cwd, stats.value, settings, glyphs, styles)

    minimal.register_panel(
        "git_panel",
        render,
        area=settings["area"],
        order=settings["order"],
        title=settings["title"] or None,
        collapsible=True,
    )
