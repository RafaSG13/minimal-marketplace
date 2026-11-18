"""Diff panel: a compact coloured diff of the files the model changed this turn, and `/diff` for all of it. Install it with `/ext`."""

from __future__ import annotations

import difflib
import threading
import unicodedata
from pathlib import Path

__version__ = "1.0"
__api__ = "2"

DEFAULTS = {"max_file_bytes": 200_000, "max_hunks": 6, "max_lines": 24, "context": 2}
"""Largest file diffed (bigger ones are listed, not diffed), hunks and lines shown in the panel, context lines."""

BINARY_PROBE = 8192
"""How many leading bytes are checked for a NUL byte, which marks a file as binary."""

TOOLS = ("edit", "write")

MISSING = ("missing", "")
"""Snapshot of a file that does not exist."""


# --- pure helpers -------------------------------------------------------------


def clean(text: str) -> str:
    """``text`` with control characters (and line/paragraph separators) shown as ``\\xNN``/``\\uNNNN``; tabs as spaces."""
    out = []
    for ch in text:
        if ch == "\t":
            out.append("    ")
        elif unicodedata.category(ch) in ("Cc", "Zl", "Zp"):
            out.append(f"\\x{ord(ch):02x}" if ord(ch) < 0x100 else f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)


def snapshot(path: Path, max_bytes: int) -> tuple[str, str]:
    """``(kind, text)`` of the file now: ``text`` for readable text (bytes that are not UTF-8 become U+FFFD),
    ``missing`` when absent, ``binary`` (a NUL in the first bytes), ``large`` (over ``max_bytes``) or ``unreadable``."""
    try:
        if path.stat().st_size > max_bytes:
            return ("large", "")
        data = path.read_bytes()
    except FileNotFoundError:
        return MISSING
    except OSError:  # a directory, a permission error, a device...
        return ("unreadable", "")
    if b"\0" in data[:BINARY_PROBE]:
        return ("binary", "")
    return ("text", data.decode("utf-8", errors="replace"))


def split_hunks(lines: list[str]) -> list[list[str]]:
    """Group unified-diff body lines (no ``---``/``+++`` headers) into hunks, each starting at its ``@@`` line."""
    hunks: list[list[str]] = []
    for line in lines:
        if line.startswith("@@"):
            hunks.append([line])
        elif hunks:
            hunks[-1].append(line)
    return hunks


def _lines(text: str) -> list[str]:
    """``text`` split on ``\\n`` only (other separators stay inside their line)."""
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def make_change(before: tuple[str, str], after: tuple[str, str], context: int = 2) -> dict | None:
    """What changing a file from snapshot ``before`` to ``after`` did, or None if nothing visible changed.

    The result has ``status`` (``new``, ``deleted``, ``modified`` or ``skipped``), ``note`` (why a file was
    not diffed, else ``""``), ``hunks`` (lists of unified-diff lines) and the ``added``/``removed`` counts.
    """
    (kind_a, old), (kind_b, new) = before, after
    if kind_a == kind_b == "missing":
        return None
    for kind in (kind_a, kind_b):
        if kind not in ("text", "missing"):
            note = {"binary": "binary file", "large": "file too large", "unreadable": "unreadable"}[kind]
            return {"status": "skipped", "note": note, "hunks": [], "added": 0, "removed": 0}
    status = "new" if kind_a == "missing" else "deleted" if kind_b == "missing" else "modified"
    if status == "modified" and old == new:
        return None
    body = list(
        difflib.unified_diff(_lines(old), _lines(new), "a", "b", n=max(0, context), lineterm="")
    )[2:]
    hunks = split_hunks(body)
    added = sum(1 for h in hunks for line in h[1:] if line.startswith("+"))
    removed = sum(1 for h in hunks for line in h[1:] if line.startswith("-"))
    return {"status": status, "note": "", "hunks": hunks, "added": added, "removed": removed}


def display_name(path: Path, cwd: Path) -> str:
    """``path`` relative to ``cwd`` when under it, else absolute."""
    try:
        return path.relative_to(cwd).as_posix()
    except ValueError:
        return str(path)


def _header(name: str, change: dict) -> list:
    """The ``name  +n -m`` row (or a note for a file that was not diffed), as pieces."""
    status, note = change["status"], change["note"]
    tag = {"new": " (new)", "deleted": " (deleted)", "skipped": f" ({note}, not diffed)"}.get(status, "")
    row: list = [(clean(name), "bold"), (tag, "dim")]
    if status != "skipped":
        row += [("  ", ""), (f"+{change['added']}", "success"), (" ", ""), (f"-{change['removed']}", "error")]
    return row


def _line(text: str) -> tuple[str, str]:
    style = "success" if text.startswith("+") else "error" if text.startswith("-") else "dim"
    return clean(text), style


def panel_lines(changes: list[tuple[str, dict]], max_hunks: int, max_lines: int) -> list:
    """Styled lines for ``(name, change)`` pairs, oldest first: a ``+n -m`` row per file, then the last
    ``max_hunks`` hunks of all of them (added ``success``, removed ``error``, context ``dim``), at most
    ``max_lines`` lines in all, with a note when something is left out."""
    keep: set[tuple[int, int]] = set()
    positions = [(i, j) for i, (_, change) in enumerate(changes) for j in range(len(change["hunks"]))]
    keep.update(positions[-max_hunks:] if max_hunks > 0 else [])
    lines: list = []
    for i, (name, change) in enumerate(changes):
        lines.append(_header(name, change))
        for j, hunk in enumerate(change["hunks"]):
            if (i, j) in keep:
                lines.extend(_line(text) for text in hunk)
    hidden = len(positions) - len(keep)
    if len(lines) > max_lines:
        extra = len(lines) - max(1, max_lines)
        lines = lines[: max(1, max_lines)]
        lines.append((f"… {extra} more lines, /diff shows all", "dim"))
    elif hidden:
        lines.append((f"… {hidden} earlier hunks, /diff shows all", "dim"))
    return lines


def full_diff(changes: list[tuple[str, dict]]) -> list[str]:
    """The whole unified diff of ``(name, change)`` pairs as plain lines, control characters escaped."""
    out: list[str] = []
    for name, change in changes:
        label = clean(name)
        if change["status"] == "skipped":
            out.append(f"# {label}: {change['note']}, not diffed")
            continue
        out.append(f"--- {'/dev/null' if change['status'] == 'new' else 'a/' + label}")
        out.append(f"+++ {'/dev/null' if change['status'] == 'deleted' else 'b/' + label}")
        out.extend(clean(line) for hunk in change["hunks"] for line in hunk)
    return out


# --- bookkeeping --------------------------------------------------------------


class Turn:
    """Per-turn record: each touched file's first snapshot and its latest change, in order of first touch."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.lock = threading.Lock()
        self.reset()

    def reset(self, *_args) -> None:
        with self.lock:
            self.before: dict[Path, tuple[str, str]] = {}
            self.changes: dict[Path, dict] = {}
            self.cwd = Path(".")

    def _path(self, event) -> Path | None:
        if event.get("name") not in TOOLS:
            return None
        raw = (event.get("input") or {}).get("path")
        if not isinstance(raw, str) or not raw:
            return None
        cwd = Path(event["ctx"].cwd)
        try:
            return Path(cwd, raw).resolve()
        except (OSError, RuntimeError, ValueError):
            return None

    def on_call(self, event) -> None:
        """Snapshot the file before the call (the first time this turn); never blocks the call."""
        try:
            path = self._path(event)
            if path is None:
                return
            with self.lock:
                if path in self.before:
                    return
            snap = snapshot(path, self.settings["max_file_bytes"])
            with self.lock:
                self.before.setdefault(path, snap)
                self.cwd = Path(event["ctx"].cwd).resolve()
        except Exception:  # an observer must not break the call
            return

    def on_result(self, event) -> None:
        """Compare the file now with its first snapshot of the turn."""
        try:
            path = self._path(event)
            if path is None:
                return
            with self.lock:
                before = self.before.get(path)
            if before is None:
                return
            after = snapshot(path, self.settings["max_file_bytes"])
            change = make_change(before, after, self.settings["context"])
            with self.lock:
                if change is None:
                    self.changes.pop(path, None)
                else:
                    self.changes[path] = change
        except Exception:
            return

    def named(self) -> list[tuple[str, dict]]:
        with self.lock:
            return [(display_name(p, self.cwd), c) for p, c in self.changes.items()]

    def render(self, ctx):
        changes = self.named()
        if not changes:
            return None
        return panel_lines(changes, self.settings["max_hunks"], self.settings["max_lines"])


def register(minimal):
    turn = Turn(minimal.declare_settings(DEFAULTS))
    minimal.on("turn_start", turn.reset)
    minimal.on("session_switch", turn.reset)
    minimal.on("tool_call", turn.on_call)
    minimal.on("tool_result", turn.on_result)
    minimal.register_panel("diff_panel", turn.render, area="sidebar", live=lambda ctx, event: None)

    def diff_command(args, ctx):
        changes = turn.named()
        print("\n".join(full_diff(changes)) if changes else "No files were changed this turn.")

    minimal.register_command("diff", diff_command, description="show the full diff of the files changed this turn")
