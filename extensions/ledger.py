"""Context ledger: what fills the context window, stale reads, and /prune.

A sidebar panel shows the heaviest tool results in the context; /prune drops
chosen ones and continues in a new session (the old one stays on disk).
"""

__version__ = "1.6"
__api__ = "2.3"
__tags__ = ["context", "ui"]

import copy
import json
import os
import threading
import time

from minimal.api import WIDGET_AREAS, result_text

DEFAULTS = {
    "enabled": True,
    "title": "CONTEXT",
    "area": "sidebar",
    "order": 0,
    "rows": 6,
    "label_width": 26,
    "stale_mark": "⚠",
    "min_prune_chars": 500,
    "prune_candidates": 20,
    "stub_prefix": "[pruned by the user",
}

SCHEMA = {
    "enabled": {"description": "Show the panel and offer /prune; false registers nothing."},
    "title": {"description": "Heading above the panel (empty: no heading)."},
    "area": {"description": "Where the panel goes by default (/ui move changes it).", "enum": list(WIDGET_AREAS)},
    "order": {"description": "Position among the panels of the area (lower first)."},
    "rows": {"description": "Heaviest tool results listed.", "min": 0, "max": 50},
    "label_width": {"description": "Columns of a result's label; longer ones are cut with an ellipsis.", "min": 8, "max": 120},
    "stale_mark": {"description": "Mark after a read whose file changed, vanished or was written since."},
    "min_prune_chars": {"description": "/prune only offers results at least this many characters long.", "min": 0},
    "prune_candidates": {"description": "Most results /prune offers, heaviest first.", "min": 1, "max": 200},
    "stub_prefix": {
        "description": "Start of the text that replaces a pruned result; results starting with it are not listed again."
    },
}


def clean(text, width=None):
    """``text`` as one printable line (control characters become spaces), cut with ``…`` beyond ``width``."""
    out = " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())
    return out if width is None or len(out) <= width else out[: max(width - 1, 0)].rstrip() + "…"


def _resolve(cwd, path):
    """``path`` made absolute against ``cwd`` and normalised, without touching the filesystem."""
    return os.path.normpath(os.path.join(cwd or ".", path))


def stat_file(path):
    """``(exists, mtime)`` of ``path``; a file that vanishes between the two calls counts as missing."""
    try:
        return True, os.stat(path).st_mtime
    except OSError:
        return False, 0.0


def _entries(messages, cwd, stat, read_at, stub_prefix):
    """The tool results of ``messages``: ``key``, ``chars``, ``label``, ``stale`` and, for a read, its ``path``.

    ``stat(path)`` gives ``(exists, mtime)`` or ``None`` if unknown (then the file counts as unchanged); ``read_at``
    maps a path to the time it was last read.
    """
    uses, errors, writes = {}, {}, []
    for mi, message in enumerate(messages):
        if not isinstance(message.get("content"), list):
            continue
        for bi, block in enumerate(message["content"]):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                uses[block.get("id")] = (mi, bi, block.get("name"), block.get("input") or {})
            elif block.get("type") == "tool_result":
                errors[block.get("tool_use_id")] = bool(block.get("is_error"))
    for tool_id, (mi, bi, name, input) in uses.items():
        if name in ("write", "edit") and isinstance(input.get("path"), str) and not errors.get(tool_id):
            writes.append((mi, bi, _resolve(cwd, input["path"])))

    entries = []
    for mi, message in enumerate(messages):
        if not isinstance(message.get("content"), list):
            continue
        for bi, block in enumerate(message["content"]):
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            text = result_text(block.get("content"))
            if text.startswith(stub_prefix):
                continue
            use = uses.get(block.get("tool_use_id"))
            label, stale, read_path = "?", False, None
            if use:
                umi, ubi, name, input = use
                if name == "read":
                    label = f"read {input.get('path', '')}"
                elif name == "bash":
                    command = str(input.get("command", "")).splitlines()
                    label = f"bash {command[0] if command else ''}"
                elif name == "grep":
                    label = f"grep {input.get('pattern', '')}"
                else:
                    label = str(name)
                if name == "read" and isinstance(input.get("path"), str):
                    read_path = path = _resolve(cwd, input["path"])
                    state = stat(path)
                    stale = (
                        (state is not None and not state[0])
                        or any(p == path and (wmi, wbi) > (umi, ubi) for wmi, wbi, p in writes)
                        or (state is not None and path in read_at and state[1] > read_at[path])
                    )
            entries.append(
                {"key": f"{mi}:{bi}", "chars": len(text), "label": clean(label), "stale": stale, "path": read_path}
            )
    return entries


def _totals(messages):
    results = inputs = prose = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            if message.get("role") == "user":
                prose += len(content)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "tool_result":
                results += len(result_text(block.get("content")))
            elif kind == "tool_use":
                inputs += len(json.dumps(block.get("input")))
            elif kind == "text" and message.get("role") == "assistant":
                prose += len(block.get("text", ""))
    return results, inputs, prose


def _tokens_per_char(ctx, total):
    return ctx.context_tokens / total if ctx.context_tokens and total else 0.25


class Ledger:
    """The panel, its record of when files were read and the worker thread that stats them off the UI thread."""

    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.Lock()
        self.read_at: dict[str, float] = {}
        self.stats: dict[str, tuple[bool, float]] = {}
        self.wanted: set[str] = set()
        self.version = 0
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.thread: threading.Thread | None = None
        self.ctx = None
        self._key = None
        self._lines = None

    # -- file state, off the UI thread --

    def note_read(self, event):
        path = event["input"].get("path")
        if event["name"] == "read" and not event["is_error"] and isinstance(path, str):
            with self.lock:
                self.read_at[_resolve(event["ctx"].cwd, path)] = time.time()
                self.version += 1
        return None

    def clear(self, _event=None):
        """Forget what was read and what was seen on disk (a new session, a reload, exit)."""
        with self.lock:
            self.read_at.clear()
            self.stats.clear()
            self.wanted.clear()
            self.version += 1
            self._key = None

    def _want(self, ctx, paths):
        with self.lock:
            self.wanted = set(paths)
            self.ctx = ctx
        if not paths or self.stopped.is_set():
            return
        if self.thread is None:
            self.thread = threading.Thread(target=self._work, name="ledger-stat", daemon=True)
            self.thread.start()
        self.wake.set()

    def _work(self):
        while True:
            self.wake.wait()
            self.wake.clear()
            if self.stopped.is_set():
                return
            with self.lock:
                paths = set(self.wanted)
            seen = {path: stat_file(path) for path in paths}
            with self.lock:
                changed = any(self.stats.get(path) != state for path, state in seen.items())
                if changed:
                    self.stats = seen
                    self.version += 1
                ctx = self.ctx
            if changed and ctx is not None and not self.stopped.is_set():
                ctx.invalidate()

    def dispose(self):
        self.stopped.set()
        self.wake.set()
        thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        self.thread = None
        self.clear()

    # -- panel --

    def render(self, ctx):
        messages = ctx.messages
        key = (
            id(messages),
            len(messages),
            id(messages[0]) if messages else 0,
            id(messages[-1]) if messages else 0,
            ctx.context_tokens,
            ctx.cwd,
            self.version,
        )
        if key != self._key:
            self._lines = self._build(ctx)
            self._key = key
        return self._lines

    def _build(self, ctx):
        s = self.settings
        messages = ctx.messages
        if not messages:
            return [[("empty", "dim")]]
        results, inputs, prose = _totals(messages)
        total = results + inputs + prose
        per_char = _tokens_per_char(ctx, total)
        tokens = ctx.context_tokens
        head = f"{tokens / 1000:.1f}k" if tokens is not None else f"~{total * per_char / 1000:.1f}k"

        def pct(n):
            return round(100 * n / total) if total else 0

        with self.lock:
            read_at, stats = dict(self.read_at), dict(self.stats)
        entries = _entries(messages, ctx.cwd, stats.get, read_at, s["stub_prefix"])
        self._want(ctx, {e["path"] for e in entries if e["path"]})
        lines = [
            [(head, "bold"), (" tokens", "dim")],
            [
                (f"results {pct(results)}%", "accent"),
                (" · ", "dim"),
                (f"prose {pct(prose)}%", "secondary"),
                (" · ", "dim"),
                (f"inputs {pct(inputs)}%", "muted"),
            ],
        ]
        for e in sorted(entries, key=lambda e: e["chars"], reverse=True)[: s["rows"]]:
            row = [(f"{e['chars'] * per_char / 1000:>4.1f}k", "accent"), " " + clean(e["label"], s["label_width"])]
            if e["stale"]:
                row.append((f" {s['stale_mark']}", "warning"))
            lines.append(row)
        return lines


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    ledger = Ledger(settings)
    prefix = settings["stub_prefix"]
    minimal.on("tool_result", ledger.note_read)
    minimal.on("session_switch", ledger.clear)
    minimal.on_dispose(ledger.dispose)

    def prune(args, ctx):
        with ledger.lock:
            read_at = dict(ledger.read_at)
        entries = _entries(ctx.messages, ctx.cwd, stat_file, read_at, prefix)
        candidates = sorted(
            (e for e in entries if e["chars"] >= settings["min_prune_chars"]), key=lambda e: e["chars"], reverse=True
        )[: settings["prune_candidates"]]
        if not candidates:
            raise ValueError("nothing to prune")
        per_char = _tokens_per_char(ctx, sum(_totals(ctx.messages)))
        options = [
            (
                e["key"],
                f"{e['chars'] * per_char / 1000:.1f}k  {clean(e['label'], 60)}" + ("  (stale)" if e["stale"] else ""),
                e["stale"],
            )
            for e in candidates
        ]
        ticked = ctx.ui.choose_many("Prune from context (heaviest first)", options)
        if ticked is None:
            print("Cancelled.")
            return
        if not ticked:
            print("Nothing pruned.")
            return
        chosen = {e["key"]: e for e in candidates if e["key"] in ticked}
        new = copy.deepcopy(ctx.messages)
        for key, e in chosen.items():
            mi, bi = map(int, key.split(":"))
            new[mi]["content"][bi]["content"] = (
                f"{prefix} to save context: {e['label']}, {e['chars']} characters. "
                "Run the tool again if you need it.]"
            )
        for message in new:
            message.pop("usage", None)
        old = ctx.new_session(new)
        saved = sum(e["chars"] for e in chosen.values()) * per_char
        print(
            f"[prune] {len(chosen)} results pruned (~{saved / 1000:.1f}k tokens); "
            f"now in session {ctx.session_id}; the full history stays in session {old}"
        )

    minimal.register_command(
        "prune",
        prune,
        description="drop chosen tool results from the context (continues in a new session)",
    )
    minimal.register_panel(
        "ledger",
        ledger.render,
        area=settings["area"],
        order=settings["order"],
        title=settings["title"] or None,
        collapsible=True,
    )
