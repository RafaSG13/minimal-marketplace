"""Context ledger: what fills the context window, stale reads, and /prune.

A sidebar panel shows the heaviest tool results in the context; /prune drops
chosen ones and continues in a new session (the old one stays on disk).
"""

__version__ = "1.1"
__requires__ = ">=0.2"

import copy
import json
import time
from pathlib import Path

from textual.widgets import Static

from minimal.api import result_text

STUB_PREFIX = "[pruned by the user"
_read_at: dict[str, float] = {}


def _resolve(cwd, path):
    return str(Path(cwd, path).resolve())


def _entries(messages, cwd):
    uses, errors, writes = {}, {}, []
    for mi, message in enumerate(messages):
        if not isinstance(message["content"], list):
            continue
        for bi, block in enumerate(message["content"]):
            if block.get("type") == "tool_use":
                uses[block["id"]] = (mi, bi, block["name"], block.get("input") or {})
            elif block.get("type") == "tool_result":
                errors[block["tool_use_id"]] = bool(block.get("is_error"))
    for tool_id, (mi, bi, name, input) in uses.items():
        if name in ("write", "edit") and isinstance(input.get("path"), str) and not errors.get(tool_id):
            writes.append((mi, bi, _resolve(cwd, input["path"])))

    entries = []
    for mi, message in enumerate(messages):
        if not isinstance(message["content"], list):
            continue
        for bi, block in enumerate(message["content"]):
            if block.get("type") != "tool_result":
                continue
            text = result_text(block.get("content"))
            if text.startswith(STUB_PREFIX):
                continue
            use = uses.get(block["tool_use_id"])
            label, stale = "?", False
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
                    label = name
                if name == "read" and isinstance(input.get("path"), str):
                    path = _resolve(cwd, input["path"])
                    file = Path(path)
                    stale = (
                        not file.exists()
                        or any(p == path and (wmi, wbi) > (umi, ubi) for wmi, wbi, p in writes)
                        or (path in _read_at and file.stat().st_mtime > _read_at[path])
                    )
            entries.append({"key": f"{mi}:{bi}", "chars": len(text), "label": label, "stale": stale})
    return entries


def _totals(messages):
    results = inputs = prose = 0
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            if message["role"] == "user":
                prose += len(content)
            continue
        for block in content:
            kind = block.get("type")
            if kind == "tool_result":
                results += len(result_text(block.get("content")))
            elif kind == "tool_use":
                inputs += len(json.dumps(block.get("input")))
            elif kind == "text" and message["role"] == "assistant":
                prose += len(block.get("text", ""))
    return results, inputs, prose


def _tokens_per_char(ctx, total):
    return ctx.context_tokens / total if ctx.context_tokens and total else 0.25


class LedgerWidget(Static):
    """Sidebar panel: context size, its composition and the heaviest tool results."""

    DEFAULT_CSS = "LedgerWidget { padding: 0 1; }"

    def refresh_state(self, ctx):
        messages = ctx.messages
        if not messages:
            self.update("CONTEXT empty")
            return
        results, inputs, prose = _totals(messages)
        total = results + inputs + prose
        per_char = _tokens_per_char(ctx, total)
        tokens = ctx.context_tokens
        head = f"CONTEXT {tokens / 1000:.1f}k" if tokens is not None else f"CONTEXT ~{total * per_char / 1000:.1f}k"

        def pct(n):
            return round(100 * n / total) if total else 0

        lines = [head, f"results {pct(results)}% · prose {pct(prose)}% · inputs {pct(inputs)}%"]
        for e in sorted(_entries(messages, ctx.cwd), key=lambda e: e["chars"], reverse=True)[:6]:
            label = e["label"] if len(e["label"]) <= 26 else e["label"][:25] + "…"
            lines.append(f"{e['chars'] * per_char / 1000:>4.1f}k {label}" + (" ⚠" if e["stale"] else ""))
        self.update("\n".join(lines))


def register(minimal):
    def note_read(event):
        path = event["input"].get("path")
        if event["name"] == "read" and not event["is_error"] and isinstance(path, str):
            _read_at[_resolve(event["ctx"].cwd, path)] = time.time()
        return None

    minimal.on("tool_result", note_read)

    def prune(args, ctx):
        entries = _entries(ctx.messages, ctx.cwd)
        candidates = sorted((e for e in entries if e["chars"] >= 500), key=lambda e: e["chars"], reverse=True)[:20]
        if not candidates:
            raise ValueError("nothing to prune")
        per_char = _tokens_per_char(ctx, sum(_totals(ctx.messages)))
        options = [
            (
                e["key"],
                f"{e['chars'] * per_char / 1000:.1f}k  {e['label'][:60]}" + ("  (stale)" if e["stale"] else ""),
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
                f"{STUB_PREFIX} to save context: {e['label']}, {e['chars']} characters. "
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
    minimal.register_widget("ledger", lambda ctx: LedgerWidget(markup=False), area="sidebar")
