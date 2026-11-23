"""Tripwire: re-run invariant commands after file changes and tell the model which call broke them.

/tripwire add <command> registers an invariant; after every call that changes
files it is re-run and a [tripwire] note is appended to the tool result.

The invariants are commands that run on your machine, so they are kept in
minimal's data folder for this project (`minimal.data_dir()`), never in the repository:
a repository must not be able to choose what runs when you open it. The
`commands` setting adds invariants from your settings file; a project's settings
count only once you trusted the project. Other settings (`/ext settings tripwire`)
set the timeout, how much output is kept, a debounce, the notes the model sees,
progress and failure notices, and the panel.
"""

__version__ = "2.8"
__api__ = "2.4"
__tags__ = ["safety", "diagnostics"]

import hashlib
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from minimal.api import WIDGET_AREAS

GIT_SCOPE = ("--", ".", ":(exclude).minimal")
SECRET_ENV = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BRAVE_API_KEY")
"""Variables no child process of the tripwire gets: the model's keys must not reach a repository's scripts."""
USAGE = "usage: /tripwire add <command> | rm <n> | run"

BROKE_NOTE = '[tripwire] "{cmd}" was passing before this call and fails now:\n{tail}'
FAILS_NOTE = '[tripwire] "{cmd}" fails:\n{tail}'
STILL_NOTE = '[tripwire] still failing: "{cmd}"'
PASSES_NOTE = '[tripwire] "{cmd}" passes again'
PROMPT_NOTE = (
    "Tripwires: after a tool call changes files, the user's invariant commands run. "
    "A [tripwire] note at the end of a tool result means your last call broke an invariant: "
    "fix it before continuing."
)
NOTE_FIELDS = ("broke_note", "fails_note", "still_note", "passes_note")

DEFAULTS = {
    "enabled": True,
    "commands": [],
    "timeout": 60,
    "tail_lines": 15,
    "clip_chars": 0,
    "debounce": 0.0,
    "progress": True,
    "notify": False,
    "broke_note": BROKE_NOTE,
    "fails_note": FAILS_NOTE,
    "still_note": STILL_NOTE,
    "passes_note": PASSES_NOTE,
    "prompt_note": PROMPT_NOTE,
    "ok_glyph": "●",
    "fail_glyph": "✘",
    "area": "bottom",
    "order": 0,
    "title": "",
}

SCHEMA = {
    "enabled": {"description": "Run the invariants; false registers nothing."},
    "commands": {
        "description": "Invariant commands added from settings (shown by /tripwire, removed by deleting them here). "
        "They run in bash in the project like /tripwire add ones; keep them in your own settings, not a repository's."
    },
    "timeout": {"description": "Seconds an invariant may run before it counts as failing.", "min": 1, "max": 3600},
    "tail_lines": {"description": "Last output lines of a failing invariant sent to the model.", "min": 1, "max": 500},
    "clip_chars": {"description": "Cut that output to this many characters, keeping the end (0: no cut).", "min": 0, "max": 100000},
    "debounce": {
        "description": "Seconds after a run during which later calls do not re-run the invariants (0: every call). "
        "A skipped change is checked by the next run.",
        "min": 0,
        "max": 600,
    },
    "progress": {"description": "Show which invariant is running next to the working indicator."},
    "notify": {"description": "Show a warning notice when an invariant that was not failing fails."},
    "broke_note": {"description": "Note for an invariant that passed before the call and fails now; {cmd} and {tail}."},
    "fails_note": {"description": "Note for an invariant that fails the first time it runs; {cmd} and {tail}."},
    "still_note": {"description": "Note for an invariant that keeps failing; {cmd} and {tail}."},
    "passes_note": {"description": "Note for an invariant that passes again; {cmd} and {tail}."},
    "prompt_note": {"description": "Paragraph added to the system prompt (empty: none)."},
    "ok_glyph": {"description": "Marker of the panel when every invariant passes."},
    "fail_glyph": {"description": "Marker of the panel when one fails."},
    "area": {"description": "Where the panel goes by default (/ui move changes it).", "enum": list(WIDGET_AREAS)},
    "order": {"description": "Position among the panels of the area (lower first)."},
    "title": {"description": "Heading above the panel (empty: no heading)."},
}


STATE_FILE = None


def _env(git=False):
    """The environment of a child: ours without ``SECRET_ENV``; for git also no prompts, pager or colour."""
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    if git:
        env.update(GIT_TERMINAL_PROMPT="0", PAGER="cat", GIT_PAGER="cat", NO_COLOR="1")
    return env


def check_settings(settings):
    """``(settings, problems)``: ``settings`` as a dict where what is inconsistent beyond what the schema checks is
    replaced (a bad template or glyph by its default; of ``commands`` only the bad entries are dropped, so one typo
    keeps the other invariants), and one text per fix. A tripwire that does not load guards nothing."""
    fixed, problems = dict(settings), []
    where = "extensions.settings.tripwire."
    commands = fixed["commands"]
    if not all(isinstance(c, str) and c.strip() for c in commands):
        problems.append(f"{where}commands must be a list of non-empty command strings; the other entries are used")
        fixed["commands"] = [c for c in commands if isinstance(c, str) and c.strip()]
    for name in NOTE_FIELDS:
        try:
            fixed[name].format(cmd="c", tail="t")
        except (KeyError, IndexError, ValueError, AttributeError) as exc:
            problems.append(
                f"{where}{name} is not a valid template ({exc!r}); use only {{cmd}} and {{tail}}, and write literal "
                "braces as {{ and }}; the default note is used until you fix it"
            )
            fixed[name] = DEFAULTS[name]
    for name in ("ok_glyph", "fail_glyph"):
        if not fixed[name].isprintable():
            problems.append(f"{where}{name} must be printable text; the default is used until you fix it")
            fixed[name] = DEFAULTS[name]
    return fixed, problems


def _git(cwd, *args):
    """``git`` output, or ``None`` if it failed. ``core.fsmonitor`` is off: a repository's own config must not run a
    program just because we looked at its status."""
    try:
        r = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            stdin=subprocess.DEVNULL,
            env=_env(git=True),
        )
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
    """The saved invariants (none when nothing was saved yet).

    Raises:
        ValueError: if the state file exists but cannot be read; the invariants must not silently stop guarding.
    """
    if not STATE_FILE.exists():
        return {"wires": [], "edits_since_green": 0}
    data = _load(STATE_FILE, None)
    if not isinstance(data, dict) or not isinstance(data.get("wires"), list):
        raise ValueError(
            f"the tripwire state file {STATE_FILE} is unreadable; delete it to start over "
            "(your invariants in it are lost; ones from the commands setting come back)"
        )
    data.setdefault("edits_since_green", 0)
    return data


def _run_wire(cmd, cwd, settings):
    """Run ``cmd`` in bash in ``cwd``; ``(passed, tail)``. A command that cannot start or runs over ``timeout`` fails."""
    timeout = settings["timeout"]
    try:
        proc = subprocess.Popen(
            ["/bin/bash", "-c", cmd],
            cwd=cwd,
            env=_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except OSError as exc:
        return False, f"could not run it: {exc}"
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass  # a daemonised grandchild still holds the pipes; it is not ours to wait for
        return False, f"timed out after {timeout}s"
    lines = (stdout + stderr).strip().splitlines()
    tail = "\n".join(lines[-settings["tail_lines"] :]) or "(no output)"
    clip = settings["clip_chars"]
    if clip and len(tail) > clip:
        tail = "…" + tail[-clip:]
    return proc.returncode == 0, tail


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


def _sync_commands(state, commands):
    """Make the wires marked ``configured`` match ``commands``: add the new ones, drop the removed ones."""
    wires = [w for w in state["wires"] if not w.get("configured") or w["cmd"] in commands]
    have = {w["cmd"] for w in wires}
    for cmd in commands:
        if cmd in have:
            for w in wires:
                if w["cmd"] == cmd:
                    w["configured"] = True
        else:
            wires.append({"cmd": cmd, "ok": None, "tail": "", "configured": True})
            have.add(cmd)
    changed = wires != state["wires"]
    state["wires"] = wires
    return changed


class TripwireWidget:
    """Bar showing how many invariants pass."""

    def __init__(self, settings, view):
        self.settings = settings
        self.view = view

    def render(self, ctx):
        try:
            state = self.view()
        except ValueError:
            return f"{self.settings['fail_glyph']} tripwire state unreadable: delete {STATE_FILE}"
        wires = state["wires"]
        if not wires:
            return None
        passing = sum(1 for w in wires if w["ok"] is True)
        if passing == len(wires):
            return f"{self.settings['ok_glyph']} {passing}/{len(wires)} wires · 0 edits since green"
        failing = next(w["cmd"] for w in wires if w["ok"] is not True)
        return (
            f"{self.settings['fail_glyph']} {passing}/{len(wires)} wires · {state['edits_since_green']} edits since green"
            f" · failing: {failing}"
        )


def register(minimal):
    global STATE_FILE
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    settings, problems = check_settings(settings)
    for problem in problems:
        minimal.report_problem(problem)
    STATE_FILE = minimal.data_dir() / "state.json"
    commands = [c.strip() for c in dict.fromkeys(settings["commands"])]
    mem = {"fp": None, "last": None, "booted": False}

    def view():
        """The state as the panel shows it: the saved wires plus the ``commands`` setting, nothing written."""
        state = _state()
        if commands or any(w.get("configured") for w in state["wires"]):
            _sync_commands(state, commands)
        return state

    def boot(root):
        """First use (never at ``register``): move the old state file, apply the ``commands`` setting to the saved
        wires and take the fingerprint changes are measured against."""
        if mem["booted"]:
            return
        mem["booted"] = True
        legacy = Path.home() / ".minimal" / "state" / "tripwire" / (
            hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:16] + ".json"
        )
        try:
            if legacy.is_file() and not STATE_FILE.exists():
                legacy.replace(STATE_FILE)
        except OSError:
            pass
        try:
            state = _state()
        except ValueError:
            return  # the command and the next tool result tell the user; a handler must not raise from here
        if (commands or any(w.get("configured") for w in state["wires"])) and _sync_commands(state, commands):
            _save(root, state)
        mem["fp"] = _fingerprint(root) if state["wires"] else None

    def tripwire(args, ctx):
        root = Path(ctx.cwd)
        boot(root)
        state = _state()
        wires = state["wires"]
        verb, _, rest = args.strip().partition(" ")
        rest = rest.strip()
        if not verb:
            print(_listing(wires))
        elif verb == "add":
            if not rest:
                raise ValueError(USAGE)
            ok, tail = _run_wire(rest, root, settings)
            wires.append({"cmd": rest, "ok": ok, "tail": tail})
            mem["fp"] = _fingerprint(root)
            _save(root, state)
            print(f"Tripwire added: {rest} ({'passing' if ok else 'failing'} now)")
        elif verb == "rm":
            if not rest.isdecimal() or not 1 <= int(rest) <= len(wires):
                raise ValueError(f"no tripwire {rest}")
            if wires[int(rest) - 1].get("configured"):
                raise ValueError(
                    f"tripwire {rest} comes from the commands setting; "
                    "remove it from extensions.settings.tripwire.commands (/ext settings tripwire commands)"
                )
            removed = wires.pop(int(rest) - 1)
            _save(root, state)
            print(f"Tripwire removed: {removed['cmd']}")
        elif verb == "run":
            for n, w in enumerate(wires, 1):
                if settings["progress"]:
                    ctx.progress(f"tripwire {n}/{len(wires)}: {w['cmd']}")
                w["ok"], w["tail"] = _run_wire(w["cmd"], root, settings)
            ctx.progress(None)
            state["edits_since_green"] = 0 if all(w["ok"] for w in wires) else state["edits_since_green"] + 1
            mem["fp"] = _fingerprint(root)
            mem["last"] = time.monotonic()
            _save(root, state)
            print(_listing(wires))
        else:
            raise ValueError(USAGE)

    minimal.register_command(
        "tripwire", tripwire, description="invariants: /tripwire add <command> | rm <n> | run"
    )

    def before_call(event):
        boot(Path(event["ctx"].cwd))
        return None

    minimal.on("tool_call", before_call)

    def after_call(event):
        root = Path(event["ctx"].cwd)
        boot(root)
        try:
            state = _state()
        except ValueError as exc:
            event["output"] += f"\n[tripwire] the invariants did not run: {exc}"
            return {"output": event["output"]}
        wires = state["wires"]
        if not wires:
            return None
        fp = _fingerprint(root)
        changed = event["name"] in ("write", "edit") and not event["is_error"]
        if not changed and not (fp is not None and fp != mem["fp"]):
            return None
        debounce = settings["debounce"]
        if debounce and mem["last"] is not None and time.monotonic() - mem["last"] < debounce:
            return None
        mem["fp"] = fp
        ctx = event["ctx"]
        notes, broken = [], []
        try:
            for n, w in enumerate(wires, 1):
                if settings["progress"]:
                    ctx.progress(f"tripwire {n}/{len(wires)}: {w['cmd']}")
                before = w["ok"]
                w["ok"], w["tail"] = _run_wire(w["cmd"], root, settings)
                fields = {"cmd": w["cmd"], "tail": w["tail"]}
                if before is True and not w["ok"]:
                    notes.append(settings["broke_note"].format(**fields))
                    broken.append(w["cmd"])
                elif before is None and not w["ok"]:
                    notes.append(settings["fails_note"].format(**fields))
                    broken.append(w["cmd"])
                elif before is False and not w["ok"]:
                    notes.append(settings["still_note"].format(**fields))
                elif before is False and w["ok"]:
                    notes.append(settings["passes_note"].format(**fields))
        finally:
            if settings["progress"]:
                ctx.progress(None)
        mem["last"] = time.monotonic()
        state["edits_since_green"] = 0 if all(w["ok"] for w in wires) else state["edits_since_green"] + 1
        _save(root, state)
        if broken and settings["notify"]:
            ctx.notify(f"tripwire: {len(broken)} invariant(s) failing: {', '.join(broken)}", "warning")
        if not notes:
            return None
        event["output"] += "".join(f"\n{n}" for n in notes)
        return {"output": event["output"]}

    minimal.on("tool_result", after_call)

    if settings["prompt_note"]:
        minimal.append_system_prompt(settings["prompt_note"])

    minimal.register_panel(
        "tripwire",
        TripwireWidget(settings, view).render,
        area=settings["area"],
        order=settings["order"],
        title=settings["title"] or None,
    )
