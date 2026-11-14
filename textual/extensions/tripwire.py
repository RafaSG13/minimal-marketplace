"""Tripwire: re-run invariant commands after file changes and tell the model which call broke them.

/tripwire add <command> registers an invariant; after every call that changes
files it is re-run and a [tripwire] note is appended to the tool result.

The invariants are commands that run on your machine, so they are kept in
minimal's data folder for this project (`minimal.data_dir()`), never in the repository:
a repository must not be able to choose what runs when you open it.
"""

__version__ = "2.4"
__api__ = "2"

import hashlib
import json
import subprocess
from pathlib import Path

GIT_SCOPE = ("--", ".", ":(exclude).minimal")
USAGE = "usage: /tripwire add <command> | rm <n> | run"


STATE_FILE = None


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
    path = STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps({**data, "project": str(Path(root).resolve())}, indent=2), encoding="utf-8")
    path.chmod(0o600)


def _state():
    data = _load(STATE_FILE, None)
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


class TripwireWidget:
    """Bottom bar showing how many invariants pass."""

    def render(self, ctx):
        state = _state()
        wires = state["wires"]
        if not wires:
            return None
        passing = sum(1 for w in wires if w["ok"] is True)
        if passing == len(wires):
            return f"● {passing}/{len(wires)} wires · 0 edits since green"
        failing = next(w["cmd"] for w in wires if w["ok"] is not True)
        return (
            f"✘ {passing}/{len(wires)} wires · {state['edits_since_green']} edits since green"
            f" · failing: {failing}"
        )


def register(minimal):
    global STATE_FILE
    STATE_FILE = minimal.data_dir() / "state.json"
    legacy = Path.home() / ".minimal" / "state" / "tripwire" / (
        hashlib.sha256(str(Path.cwd().resolve()).encode()).hexdigest()[:16] + ".json"
    )
    try:
        if legacy.is_file() and not STATE_FILE.exists():
            legacy.replace(STATE_FILE)
    except OSError:
        pass
    mem = {"fp": _fingerprint(Path.cwd()) if _state()["wires"] else None}

    def tripwire(args, ctx):
        root = Path(ctx.cwd)
        state = _state()
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
        state = _state()
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

    minimal.register_panel("tripwire", TripwireWidget().render, area="bottom")
