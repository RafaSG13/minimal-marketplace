"""Go module: the go.mod module path and Go version on the status line, hidden outside Go modules."""

from __future__ import annotations

import re
import time
from pathlib import Path

__version__ = "1.0"
__api__ = "2"

WIDTH = 32
"""Most columns for the module path; a longer one loses its start."""

RECHECK = 2.0
"""Seconds a lookup is reused: the segment renders on every redraw."""

MODULE_RE = re.compile(r"^module\s+(\S+)", re.MULTILINE)
GO_RE = re.compile(r"^go\s+(\S+)", re.MULTILINE)


def find_go_mod(cwd: str | None) -> Path | None:
    """The go.mod of ``cwd`` or its nearest parent holding one, or None."""
    start = Path(cwd or ".").resolve()
    for folder in (start, *start.parents):
        candidate = folder / "go.mod"
        if candidate.is_file():
            return candidate
    return None


def parse(text: str) -> tuple[str, str]:
    """``(module path, go version)`` of go.mod ``text``; ``""`` for either one missing."""
    module, go = MODULE_RE.search(text), GO_RE.search(text)
    return (module.group(1).strip('"') if module else "", go.group(1) if go else "")


class GoModule:
    """Status segment: ``module go1.x`` of the go.mod above the working directory."""

    def __init__(self) -> None:
        self.cwd: str | None = None
        self.checked = 0.0
        self.key: tuple[Path, int] | None = None
        self.value: tuple[str, str] | None = None

    def _lookup(self, cwd: str | None) -> tuple[str, str] | None:
        """``(module, version)`` for ``cwd``, reread only when go.mod moved or changed."""
        path = find_go_mod(cwd)
        if path is None:
            self.key = None
            return None
        try:
            key = (path, path.stat().st_mtime_ns)
            if key != self.key:
                self.key, self.value = key, parse(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            self.key = None
            return None
        return self.value

    def render(self, ctx):
        now = time.monotonic()
        if ctx.cwd != self.cwd or now - self.checked >= RECHECK:
            self.cwd, self.checked = ctx.cwd, now
            self.value = self._lookup(ctx.cwd)
        if not self.value:
            return None
        module, go = self.value
        if not module:
            return None
        if len(module) > WIDTH:
            module = "…" + module[-(WIDTH - 1) :]
        pieces = [(module, "accent")]
        if go:
            pieces.append((f" go{go}", "muted"))
        return pieces


def register(minimal):
    minimal.register_status("go_module", GoModule().render, side="left")
