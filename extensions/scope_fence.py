"""Scope fence: block edits outside declared paths or over a diff budget.

/fence <path-or-glob>... [--lines N] limits where the model may write and how
many lines it may change; /fence off removes the fence.
"""

__version__ = "1.2"
__api__ = "1"

import json
import shlex
import subprocess
from pathlib import Path, PurePosixPath

from textual.widgets import Static

from minimal.api import glob_regex

GIT_SCOPE = ("--", ".", ":(exclude).minimal")
STATE = ".minimal/state/fence.json"
USAGE = "usage: /fence <path-or-glob>... [--lines N] | /fence off"


def _git(cwd, *args):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _state_path(root):
    return Path(root, STATE)


def _summary(fence):
    text = f"Fence: {', '.join(fence['globs']) or '(any path)'}"
    if fence.get("lines"):
        text += f" · budget {fence['lines']} lines"
    return text


def _used(cwd):
    out = _git(cwd, "diff", "--numstat", "HEAD", *GIT_SCOPE)
    if out is None:
        return None
    total = 0
    for line in out.splitlines():
        added, deleted = line.split("\t")[:2]
        if added != "-" and deleted != "-":
            total += int(added) + int(deleted)
    return total


def _status(cwd):
    out = _git(cwd, "status", "--porcelain", "-uall", *GIT_SCOPE)
    return None if out is None else set(out.splitlines())


def _paths(cwd, lines):
    prefix = (_git(cwd, "rev-parse", "--show-prefix") or "").strip()
    paths = []
    for line in lines:
        p = line[3:]
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        p = p.strip('"')
        if prefix and p.startswith(prefix):
            p = p[len(prefix) :]
        paths.append(p)
    return paths


def _inside(rel, globs):
    if rel.startswith(".minimal/") or not globs:
        return True
    return any(
        glob_regex(glob).fullmatch(PurePosixPath(rel).name if "/" not in glob else rel) for glob in globs
    )


def _rel(root, raw):
    p = Path(root, raw).resolve()
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return str(p)


class FenceWidget(Static):
    """Sidebar panel showing the active fence, budget use and blocked paths."""

    DEFAULT_CSS = "FenceWidget { padding: 0 1; }"

    def refresh_state(self, ctx):
        fence = _load(_state_path(Path(ctx.cwd)), None)
        if not fence:
            self.display = False
            return
        lines = ["FENCE", *(fence["globs"] or ["(any path)"])]
        if fence.get("lines"):
            used = _used(Path(ctx.cwd))
            lines.append(f"budget {'?' if used is None else used}/{fence['lines']} lines")
        blocked = fence.get("blocked", [])
        if blocked:
            lines.append(f"blocked {len(blocked)}: {', '.join(blocked[-3:])}")
        self.update("\n".join(lines))
        self.display = True


def register(minimal):
    mem = {"before": None}

    def fence_command(args, ctx):
        path = _state_path(ctx.cwd)
        tokens = shlex.split(args)
        if not tokens:
            fence = _load(path, None)
            print(_summary(fence) if fence else f"No fence. {USAGE}")
            return
        if tokens == ["off"]:
            path.unlink(missing_ok=True)
            print("Fence removed.")
            return
        globs, lines, i = [], None, 0
        while i < len(tokens):
            token = tokens[i]
            if token == "--lines":
                if i + 1 >= len(tokens) or not tokens[i + 1].isdecimal() or int(tokens[i + 1]) < 1:
                    raise ValueError(USAGE)
                lines = int(tokens[i + 1])
                i += 2
                continue
            token = token.removeprefix("./")
            if Path(ctx.cwd, token).is_dir():
                token = token.rstrip("/") + "/**"
            globs.append(token)
            i += 1
        fence = {"globs": globs, "lines": lines, "blocked": []}
        _save(path, fence)
        print(_summary(fence))

    minimal.register_command(
        "fence",
        fence_command,
        description="limit edits: /fence <path-or-glob>... [--lines N] | /fence off",
    )

    def guard(event):
        root = Path(event["ctx"].cwd).resolve()
        path = _state_path(root)
        fence = _load(path, None)
        if not fence:
            return None
        name = event["name"]
        if name == "bash":
            mem["before"] = _status(root)
            return None
        if name not in ("write", "edit") or not isinstance(event["input"].get("path"), str):
            return None
        rel = _rel(root, event["input"]["path"])
        globs = fence["globs"]
        if not _inside(rel, globs):
            if rel not in fence["blocked"]:
                fence["blocked"].append(rel)
                _save(path, fence)
            return {
                "block": True,
                "reason": (
                    f"{rel} is outside the fence ({', '.join(globs)}). Do not work around it: "
                    "tell the user why you need this file so they can widen the fence with /fence."
                ),
            }
        lines = fence.get("lines")
        if lines and not rel.startswith(".minimal/"):
            used = _used(root)
            if used is not None and used >= lines:
                return {
                    "block": True,
                    "reason": (
                        f"diff budget used up ({used}/{lines} changed lines). "
                        "Stop editing, summarise what is done and what remains."
                    ),
                }
        return None

    def after_bash(event):
        if event["name"] != "bash":
            return None
        root = Path(event["ctx"].cwd).resolve()
        path = _state_path(root)
        fence = _load(path, None)
        before, mem["before"] = mem["before"], None
        if not fence or before is None:
            return None
        after = _status(root)
        if after is None:
            return None
        outside = [p for p in _paths(root, sorted(after - before)) if not _inside(p, fence["globs"])]
        if not outside:
            return None
        for p in outside:
            if p not in fence["blocked"]:
                fence["blocked"].append(p)
        _save(path, fence)
        event["output"] += (
            f"\n[fence] this command changed files outside the fence: {', '.join(outside)}. "
            "Revert them unless the user asked for it."
        )
        return {"output": event["output"]}

    minimal.on("tool_call", guard)
    minimal.on("tool_result", after_bash)
    minimal.register_widget("fence", lambda ctx: FenceWidget(markup=False), area="sidebar")
