"""Go check: `go vet ./...` of the Go module you are in, rerun after the model edits Go files."""

from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path

__version__ = "1.0"
__api__ = "2"

COMMAND = ["go", "vet", "./..."]
"""Run from the module root, the folder holding go.mod."""

TIMEOUT = 120
"""Seconds a run may take before it is killed."""

ROWS = 6
"""Most diagnostics listed."""

WIDTH = 31
"""Columns of a row; the row fills the sidebar panel."""

WATCHED = (".go", "go.mod", "go.sum", "go.work")
"""A successful edit or write of a path ending in one of these makes the check run again."""

DIAGNOSTIC_RE = re.compile(r"^(?:vet: )?(?:\./)?(\S+?\.go):(\d+)(?::\d+)?: (.*)$")


def find_module_root(cwd: str | None) -> Path | None:
    """The folder of the go.mod of ``cwd`` or its nearest parent holding one, or None."""
    start = Path(cwd or ".").resolve()
    for folder in (start, *start.parents):
        if (folder / "go.mod").is_file():
            return folder
    return None


def parse(output: str) -> list[tuple[str, str, str]]:
    """``(file, line, message)`` of each diagnostic in ``go vet`` output; package headers (``# pkg``) dropped."""
    found = []
    for line in output.splitlines():
        if match := DIAGNOSTIC_RE.match(line.strip()):
            found.append(match.groups())
    return found


def _cut(text: str, width: int) -> str:
    """``text`` cut to ``width`` columns with a trailing ``…``."""
    return text if len(text) <= width else text[: width - 1] + "…"


class GoCheck:
    """Sidebar panel: ``go vet`` results for the module, run on a thread."""

    def __init__(self) -> None:
        self.root: Path | None = None
        self.result: dict | None = None
        self.dirty = True
        self.running = False
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()

    def live(self, ctx, event: dict) -> None:
        if event["kind"] != "tool_result" or event["result"].get("is_error"):
            return
        call = event["call"]
        path = (call.get("input") or {}).get("path")
        if call.get("name") in ("edit", "write") and isinstance(path, str) and path.endswith(WATCHED):
            self.dirty = True

    def render(self, ctx):
        root = find_module_root(ctx.cwd)
        if root is None:
            return None
        if root != self.root:
            self.root, self.result, self.dirty = root, None, True
        if self.dirty and not self.running:
            self.dirty, self.running = False, True
            threading.Thread(target=self._run, args=(root,), daemon=True).start()
        return self._lines()

    def _lines(self) -> list:
        result = self.result
        head = [("GO VET", "bold muted")]
        if result is None:
            return [head + [("  running…", "dim")]]
        if self.running:
            head.append(("  rerunning…", "dim"))
        if result["error"]:
            return [head, [(_cut(result["error"], WIDTH), "warning")]]
        diagnostics = result["diagnostics"]
        if not diagnostics and result["ok"]:
            return [head, [("✓ no issues", "success")]]
        if not diagnostics:
            # Failed without file:line diagnostics, e.g. a module or toolchain error.
            return [head, *[[(_cut(line, WIDTH), "error")] for line in result["other"][:ROWS]]]
        lines = [head, [(f"✗ {len(diagnostics)} issue{'s' if len(diagnostics) != 1 else ''}", "error")]]
        for file, line, message in diagnostics[:ROWS]:
            where = f"{Path(file).name}:{line}"
            lines.append([(where, "accent"), " ", (_cut(message, max(1, WIDTH - len(where) - 1)), "muted")])
        if len(diagnostics) > ROWS:
            lines.append([(f"… {len(diagnostics) - ROWS} more", "dim")])
        return lines

    def _run(self, root: Path) -> None:
        """Runs on a thread: run the command in ``root`` and publish the result for the next render."""
        result = {"ok": False, "diagnostics": [], "other": [], "error": ""}
        try:
            with self.lock:
                self.proc = subprocess.Popen(
                    COMMAND, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
            try:
                output, _ = self.proc.communicate(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.communicate()
                result["error"] = f"timed out after {TIMEOUT}s"
            else:
                result["ok"] = self.proc.returncode == 0
                result["diagnostics"] = parse(output)
                result["other"] = [
                    line.strip() for line in output.splitlines() if line.strip() and not line.startswith("#")
                ]
                if self.proc.returncode < 0:
                    result["error"] = "stopped"
        except FileNotFoundError:
            result["error"] = "go not found on PATH"
        except OSError as e:
            result["error"] = str(e)
        finally:
            with self.lock:
                self.proc = None
            if root == self.root:
                self.result = result
            self.running = False

    def stop(self) -> None:
        """Kill a run in progress (before a reload and when minimal exits)."""
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                self.proc.kill()


def register(minimal):
    panel = GoCheck()
    minimal.register_panel("go_check", panel.render, area="sidebar", live=panel.live, interval=1.0)
    minimal.on_dispose(panel.stop)
