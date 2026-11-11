"""Tripwire: re-run invariant commands after file changes and tell the model which call broke them.

/tripwire add <command> registers an invariant; after every call that changes
files it is re-run and a [tripwire] note is appended to the tool result.

The invariants are commands that run on your machine, so they are kept in
~/.minimal/state/tripwire/ (one file per project directory), never in the repository:
a repository must not be able to choose what runs when you open it.
"""

__version__ = "2.1"
__api__ = "1"

import hashlib
import json
import subprocess
from pathlib import Path

from textual.widgets import Static

GIT_SCOPE = ("--", ".", ":(exclude).minimal")
USAGE = "usage: /tripwire add <command> | rm <n> | run"


def _state_file(root):
    """The project's state: ``~/.minimal/state/tripwire/<hash of its directory>.json``, outside the repository."""
    key = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:16]
    return Path.home() / ".minimal" / "state" / "tripwire" / f"{key}.json"


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


def _save(root, data):
    path = _state_file(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps({**data, "project": str(Path(root).resolve())}, indent=2), encoding="utf-8")
    path.chmod(0o600)


def _state(root):
    data = _load(_state_file(root), None)
    if not isinstance(data, dict) or not isinstance(data.get("wires"), list):
        return {"wires": [], "edits_since_green": 0}
    data.setdefault("edits_since_green", 0)
    return data


def _run_wire(cmd, cwd):
    try:
        r = subprocess.run(["/bin/bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "timed out after 60s"
    lines = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode == 0, "\n".join(lines[-15:]) or "(no output)"


def _fingerprint(cwd):
    status = _git(cwd, "status", "--porcelain", *GIT_SCOPE)
    if status is None:
        return None
    diff = _git(cwd, "diff", "HEAD", *GIT_SCOPE) or ""
    return hashlib.sha1((status + diff).encode("utf-8", "replace")).hexdigest()


def _listing(wires):
    if not wires:
        return f"No tripwires. {USAGE}"
    names = {True: "passing", False: "failing", None: "not run"}
    return "\n".join(f"{n}. {names[w['ok']]}  {w['cmd']}" for n, w in enumerate(wires, 1))


class TripwireWidget(Static):
    """Bottom bar showing how many invariants pass."""

    DEFAULT_CSS = "TripwireWidget { height: 1; padding: 0 1; }"

    def refresh_state(self, ctx):
        state = _state(Path(ctx.cwd))
        wires = state["wires"]
        if not wires:
            self.display = False
            return
        passing = sum(1 for w in wires if w["ok"] is True)
        if passing == len(wires):
            self.update(f"● {passing}/{len(wires)} wires · 0 edits since green")
        else:
            failing = next(w["cmd"] for w in wires if w["ok"] is not True)
            self.update(
                f"✘ {passing}/{len(wires)} wires · {state['edits_since_green']} edits since green"
                f" · failing: {failing}"
            )
        self.display = True


def register(minimal):
    mem = {"fp": _fingerprint(Path.cwd()) if _state(Path.cwd())["wires"] else None}

    def tripwire(args, ctx):
        root = Path(ctx.cwd)
        state = _state(root)
        wires = state["wires"]
        verb, _, rest = args.strip().partition(" ")
        rest = rest.strip()
        if not verb:
            print(_listing(wires))
        elif verb == "add":
            if not rest:
                raise ValueError(USAGE)
            ok, tail = _run_wire(rest, root)
            wires.append({"cmd": rest, "ok": ok, "tail": tail})
            mem["fp"] = _fingerprint(root)
            _save(root, state)
            print(f"Tripwire added: {rest} ({'passing' if ok else 'failing'} now)")
        elif verb == "rm":
            if not rest.isdecimal() or not 1 <= int(rest) <= len(wires):
                raise ValueError(f"no tripwire {rest}")
            removed = wires.pop(int(rest) - 1)
            _save(root, state)
            print(f"Tripwire removed: {removed['cmd']}")
        elif verb == "run":
            for w in wires:
                w["ok"], w["tail"] = _run_wire(w["cmd"], root)
            state["edits_since_green"] = 0 if all(w["ok"] for w in wires) else state["edits_since_green"] + 1
            mem["fp"] = _fingerprint(root)
            _save(root, state)
            print(_listing(wires))
        else:
            raise ValueError(USAGE)

    minimal.register_command(
        "tripwire", tripwire, description="invariants: /tripwire add <command> | rm <n> | run"
    )

    def after_call(event):
        root = Path(event["ctx"].cwd)
        state = _state(root)
        wires = state["wires"]
        if not wires:
            return None
        fp = _fingerprint(root)
        changed = event["name"] in ("write", "edit") and not event["is_error"]
        if not changed and not (fp is not None and fp != mem["fp"]):
            return None
        mem["fp"] = fp
        notes = []
        for w in wires:
            before = w["ok"]
            w["ok"], w["tail"] = _run_wire(w["cmd"], root)
            if before is True and not w["ok"]:
                notes.append(f'[tripwire] "{w["cmd"]}" was passing before this call and fails now:\n{w["tail"]}')
            elif before is None and not w["ok"]:
                notes.append(f'[tripwire] "{w["cmd"]}" fails:\n{w["tail"]}')
            elif before is False and not w["ok"]:
                notes.append(f'[tripwire] still failing: "{w["cmd"]}"')
            elif before is False and w["ok"]:
                notes.append(f'[tripwire] "{w["cmd"]}" passes again')
        state["edits_since_green"] = 0 if all(w["ok"] for w in wires) else state["edits_since_green"] + 1
        _save(root, state)
        if not notes:
            return None
        event["output"] += "".join(f"\n{n}" for n in notes)
        return {"output": event["output"]}

    minimal.on("tool_result", after_call)

    minimal.append_system_prompt(
        "Tripwires: after a tool call changes files, the user's invariant commands run. "
        "A [tripwire] note at the end of a tool result means your last call broke an invariant: "
        "fix it before continuing."
    )

    minimal.register_widget("tripwire", lambda ctx: TripwireWidget(markup=False), area="bottom")
