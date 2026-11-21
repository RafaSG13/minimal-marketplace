"""Scope fence: block edits outside declared paths or over a diff budget.

/fence <path-or-glob>... [--lines N] limits where the model may write and how
many lines it may change; /fence off removes the fence. Settings (`/ext settings
scope_fence`) set a default budget, the guarded tools, exempt prefixes, the
messages the model sees, the panel and an optional status segment and key.
"""

__version__ = "1.7"
__api__ = "2.3"
__tags__ = ["safety"]

import json
import shlex
import subprocess
from pathlib import Path, PurePosixPath

from minimal.api import WIDGET_AREAS, STATUS_SIDES, glob_regex

GIT_SCOPE = ("--", ".", ":(exclude).minimal")
STATE_FILE = None
USAGE = "usage: /fence <path-or-glob>... [--lines N] | /fence off"
OUTSIDE_MESSAGE = (
    "{path} is outside the fence ({globs}). Do not work around it: "
    "tell the user why you need this file so they can widen the fence with /fence."
)
BUDGET_MESSAGE = (
    "diff budget used up ({used}/{lines} changed lines). Stop editing, summarise what is done and what remains."
)
BASH_MESSAGE = "[fence] this command changed files outside the fence: {paths}. Revert them unless the user asked for it."
MESSAGE_FIELDS = {
    "outside_message": {"path": "src/x.py", "globs": "docs/**"},
    "budget_message": {"used": 10, "lines": 10},
    "bash_message": {"paths": "src/x.py"},
}
GUARDABLE = ("write", "edit")

DEFAULTS = {
    "enabled": True,
    "tools": list(GUARDABLE),
    "exempt": [".minimal/"],
    "default_lines": 0,
    "outside_message": OUTSIDE_MESSAGE,
    "budget_message": BUDGET_MESSAGE,
    "bash_message": BASH_MESSAGE,
    "check_bash": True,
    "title": "FENCE",
    "area": "sidebar",
    "order": 0,
    "blocked_shown": 3,
    "status": False,
    "status_side": "left",
    "key": "",
}

SCHEMA = {
    "enabled": {"description": "Enforce the fence; false registers nothing (no guard, command or panel)."},
    "tools": {"description": "Tools whose `path` the fence guards: any of write, edit."},
    "exempt": {"description": "Path prefixes (relative to the project) that are always allowed and never counted as outside."},
    "default_lines": {
        "description": "Diff budget in changed lines for a fence made without --lines (0: no budget).",
        "min": 0,
        "max": 10_000_000,
    },
    "outside_message": {"description": "What the model is told when a path is outside the fence; {path} and {globs}."},
    "budget_message": {"description": "What the model is told when the diff budget is used up; {used} and {lines}."},
    "bash_message": {"description": "Note appended to a bash result that changed files outside the fence; {paths}."},
    "check_bash": {"description": "Compare git status around bash calls and note files changed outside the fence."},
    "title": {"description": "Heading above the panel (empty: no heading)."},
    "area": {"description": "Where the panel goes by default (/ui move changes it).", "enum": list(WIDGET_AREAS)},
    "order": {"description": "Position among the panels of the area (lower first)."},
    "blocked_shown": {"description": "Most recently blocked paths the panel lists (0: none).", "min": 0, "max": 20},
    "status": {"description": "Also show the active fence as a status-line segment."},
    "status_side": {"description": "Side of the status line for that segment.", "enum": list(STATUS_SIDES)},
    "key": {
        "description": "Key that shows the fence as a notice, e.g. ctrl+shift+f or f6 (empty: no key). "
        "Needs ctrl/alt or a function key."
    },
}


def check_settings(settings):
    """``ValueError`` saying what to fix if ``settings`` are inconsistent beyond what the schema checks."""
    for name, sample in MESSAGE_FIELDS.items():
        try:
            settings[name].format(**sample)
        except (KeyError, IndexError, ValueError, AttributeError) as exc:
            known = ", ".join("{" + k + "}" for k in sample)
            raise ValueError(
                f"scope_fence: extensions.settings.scope_fence.{name} is not a valid template ({exc!r}); "
                f"use only {known}, and write literal braces as {{{{ and }}}}"
            ) from exc
    for name in ("tools", "exempt"):
        value = settings[name]
        if not all(isinstance(v, str) and v for v in value):
            raise ValueError(f"scope_fence: extensions.settings.scope_fence.{name} must be a list of non-empty strings")
    bad = [t for t in settings["tools"] if t not in GUARDABLE]
    if bad:
        raise ValueError(
            f"scope_fence: extensions.settings.scope_fence.tools has {', '.join(map(repr, bad))}; "
            f"the fence guards only {', '.join(GUARDABLE)}"
        )


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


def _budget(fence, settings):
    """The fence's line budget: its own ``--lines``, else the ``default_lines`` setting (0: none)."""
    return fence.get("lines") or settings["default_lines"]


def _summary(fence, settings):
    text = f"Fence: {', '.join(fence['globs']) or '(any path)'}"
    if _budget(fence, settings):
        text += f" · budget {_budget(fence, settings)} lines"
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


def _inside(rel, globs, exempt=(".minimal/",)):
    if rel.startswith(tuple(exempt)) or not globs:
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


class FenceWidget:
    """Panel showing the active fence, budget use and blocked paths."""

    def __init__(self, settings):
        self.settings = settings

    def render(self, ctx):
        fence = _load(STATE_FILE, None)
        if not fence:
            return None
        lines = list(fence["globs"] or ["(any path)"])
        budget = _budget(fence, self.settings)
        if budget:
            used = _used(Path(ctx.cwd))
            lines.append(f"budget {'?' if used is None else used}/{budget} lines")
        blocked = fence.get("blocked", [])
        shown = self.settings["blocked_shown"]
        if blocked and shown:
            lines.append(f"blocked {len(blocked)}: {', '.join(blocked[-shown:])}")
        return "\n".join(lines)


def register(minimal):
    global STATE_FILE
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    check_settings(settings)
    guarded = tuple(settings["tools"])
    exempt = tuple(settings["exempt"])
    STATE_FILE = minimal.data_dir() / "state.json"
    mem = {"before": None}

    def fence_command(args, ctx):
        path = STATE_FILE
        tokens = shlex.split(args)
        if not tokens:
            fence = _load(path, None)
            print(_summary(fence, settings) if fence else f"No fence. {USAGE}")
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
        print(_summary(fence, settings))

    minimal.register_command(
        "fence",
        fence_command,
        description="limit edits: /fence <path-or-glob>... [--lines N] | /fence off",
    )

    def guard(event):
        root = Path(event["ctx"].cwd).resolve()
        path = STATE_FILE
        fence = _load(path, None)
        if not fence:
            return None
        name = event["name"]
        if name == "bash":
            if settings["check_bash"]:
                mem["before"] = _status(root)
            return None
        if name not in guarded or not isinstance(event["input"].get("path"), str):
            return None
        rel = _rel(root, event["input"]["path"])
        globs = fence["globs"]
        if not _inside(rel, globs, exempt):
            if rel not in fence["blocked"]:
                fence["blocked"].append(rel)
                _save(path, fence)
            return {"block": True, "reason": settings["outside_message"].format(path=rel, globs=", ".join(globs))}
        lines = _budget(fence, settings)
        if lines and not rel.startswith(exempt):
            used = _used(root)
            if used is not None and used >= lines:
                return {"block": True, "reason": settings["budget_message"].format(used=used, lines=lines)}
        return None

    def after_bash(event):
        if event["name"] != "bash":
            return None
        root = Path(event["ctx"].cwd).resolve()
        path = STATE_FILE
        fence = _load(path, None)
        before, mem["before"] = mem["before"], None
        if not fence or before is None:
            return None
        after = _status(root)
        if after is None:
            return None
        outside = [p for p in _paths(root, sorted(after - before)) if not _inside(p, fence["globs"], exempt)]
        if not outside:
            return None
        for p in outside:
            if p not in fence["blocked"]:
                fence["blocked"].append(p)
        _save(path, fence)
        event["output"] += "\n" + settings["bash_message"].format(paths=", ".join(outside))
        return {"output": event["output"]}

    minimal.on("tool_call", guard)
    minimal.on("tool_result", after_bash)
    panel = FenceWidget(settings)
    minimal.register_panel(
        "fence",
        panel.render,
        area=settings["area"],
        order=settings["order"],
        title=settings["title"] or None,
        collapsible=bool(settings["title"]),
    )

    def segment(ctx):
        fence = _load(STATE_FILE, None)
        if not fence:
            return None
        budget = _budget(fence, settings)
        text = f"fence {', '.join(fence['globs']) or '(any path)'}"
        if budget:
            used = _used(Path(ctx.cwd))
            text += f" {'?' if used is None else used}/{budget}"
        return text

    if settings["status"]:
        minimal.register_status("fence", segment, settings["status_side"])

    if settings["key"]:

        def show_fence(ctx):
            """Show the active fence."""
            fence = _load(STATE_FILE, None)
            ctx.notify(_summary(fence, settings) if fence else f"No fence. {USAGE}")

        try:
            minimal.register_keybinding(settings["key"], show_fence, "show the active scope fence", name="show")
        except ValueError as exc:
            raise ValueError(f"scope_fence: extensions.settings.scope_fence.key: {exc}; set it to \"\" for no key") from exc
