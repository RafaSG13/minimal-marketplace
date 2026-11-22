r"""Output lenses: compress noisy bash output and keep the full text on disk.

Long bash output is shortened (built-in lenses, repeated lines, head and tail) and the
full text is saved under .minimal/outputs/. That folder holds data only: nothing inside
the repository is ever executed by this extension.

Everything is a setting (``/ext settings lenses``): the limits (``min_chars``, ``head``, ``tail``), the
built-in Python test lens (``python_tests``, ``passing``), ``repeat_min``, the saved-output
folder (``output_dir``), every note it writes (``messages``), whether it starts on (``enabled``) and
a ``key`` that turns it on and off (so does ``/lenses on|off|toggle``). A lens for your own command is a
rule in ``rules``: ``name``, ``command`` (a regex searched in the command), ``drop`` (regexes of
lines to hide when they match the whole line) and ``head`` and ``tail`` (lines to keep of what is left)::

    {"extensions": {"settings": {"lenses": {"rules": [
        {"name": "make", "command": "\\bmake\\b", "drop": ["\\[ *\\d+%\\].*"], "tail": 40}]}}}}

For logic a rule cannot express, an extension rewrites bash output in a tool_result
handler, installed like any other (/ext, or .minimal/extensions/ once the project is
trusted with /trust):

    import re

    def register(minimal):
        @minimal.on("tool_result")
        def shorten(event):
            if event["name"] == "bash" and re.search(r"\bmake\b", event["input"].get("command", "")):
                return {"output": "\n".join(event["output"].splitlines()[-40:])}
"""

__version__ = "2.5"
__api__ = "2.4"
__tags__ = ["context"]

import re
import sys
from pathlib import Path, PurePosixPath

OUTPUT_DIR = ".minimal/outputs"

PASSING = (
    r".* \.\.\. ok",
    r"[.sx]+",
    r"\S+ [.sx]+\s*(\[\s*\d+%\])?",
    r".* PASSED(\s+\[\s*\d+%\])?",
)

MESSAGES = {
    "hidden": "[lens python-tests: {hidden} passing lines hidden]",
    "repeated": "[previous line repeated {count} more times]",
    "omitted": "... [lens: {chars} characters omitted here]",
    "saved": "[full output: {path}, {lines} lines; read it with offset and limit]",
    "rule_hidden": "[lens {name}: {hidden} lines hidden]",
    "rule_omitted": "[lens {name}: {omitted} lines omitted]",
    "prompt": "Output lenses: bash output over {min_chars} characters is compressed and the full text is saved under "
    "{dir}/ (read it with offset and limit when you need hidden lines).",
}
"""The notes the extension writes, with the ``{fields}`` each may use (``prompt`` may be empty: no system-prompt note)."""

MESSAGE_FIELDS = {
    "hidden": {"hidden": 0},
    "repeated": {"count": 0},
    "omitted": {"chars": 0},
    "saved": {"path": "", "lines": 0},
    "rule_hidden": {"name": "", "hidden": 0},
    "rule_omitted": {"name": "", "omitted": 0},
    "prompt": {"min_chars": 0, "dir": ""},
}

DEFAULTS = {
    "enabled": True,
    "key": "",
    "min_chars": 2000,
    "head": 6000,
    "tail": 12000,
    "python_tests": True,
    "passing": list(PASSING),
    "repeat_min": 3,
    "rules": [],
    "output_dir": OUTPUT_DIR,
    "messages": MESSAGES,
}

SCHEMA = {
    "enabled": {"description": "Compress bash output from the start. /lenses on|off (and the key) switch it for the session."},
    "key": {
        "description": "Key that turns the lenses on and off, e.g. alt+l or f7 (empty: no key). Needs ctrl/alt or a function key."
    },
    "min_chars": {"description": "Output shorter than this many characters is left alone.", "min": 1, "max": 10_000_000},
    "head": {"description": "Characters kept from the start of a long output.", "min": 0, "max": 10_000_000},
    "tail": {"description": "Characters kept from the end of a long output.", "min": 0, "max": 10_000_000},
    "python_tests": {"description": "Hide the passing lines of pytest and unittest output."},
    "passing": {
        "description": "Regexes of the passing-test lines the Python test lens hides (a line matching one completely)."
    },
    "repeat_min": {
        "description": "Collapse a line repeated this many times in a row into one (0: never; otherwise 2 or more).",
        "min": 0,
        "max": 1000,
    },
    "rules": {
        "description": "Your own lenses, a list of {name, command, drop, head, tail}: command is a regex searched in the "
        "bash command, drop a list of regexes of lines to hide (whole-line match), head and tail how many lines to "
        "keep of the rest (0: no cut)."
    },
    "output_dir": {
        "description": "Folder inside the project where the full outputs are saved (relative, no '..').",
    },
    "messages": {
        "description": "The notes it writes, by key: hidden, repeated, omitted, saved, rule_hidden, rule_omitted, prompt. "
        "Each uses its own {fields}; keys you leave out keep their default."
    },
}

RULE_KEYS = ("name", "command", "drop", "head", "tail")


def _regex(pattern, what, problems):
    """``pattern`` compiled, or ``None`` after adding to ``problems`` why it is not a regex."""
    if not isinstance(pattern, str):
        problems.append(f"{what} must be a string, not {pattern!r}")
        return None
    try:
        return re.compile(pattern)
    except re.error as e:
        problems.append(f"{what} {pattern!r} is not a valid regular expression ({e})")
        return None


def check_settings(settings):
    """``(problems, messages, passing, rules, output_dir, repeat_min)`` from ``settings``: what is wrong, each problem with its fix, and the parsed values; what is wrong is left out or back to its default."""
    problems = []
    messages = dict(MESSAGES)
    for key, value in settings["messages"].items():
        if key not in MESSAGES:
            problems.append(f"messages: unknown key {key!r} (known: {', '.join(MESSAGES)})")
        elif not isinstance(value, str) or (not value and key != "prompt"):
            problems.append(f"messages.{key} must be a non-empty string")
        else:
            try:
                value.format(**MESSAGE_FIELDS[key])
            except (KeyError, IndexError, ValueError) as e:
                fields = ", ".join("{" + f + "}" for f in MESSAGE_FIELDS[key])
                problems.append(f"messages.{key} is not a valid template ({type(e).__name__}: {e}); it may use {fields}")
            else:
                messages[key] = value

    passing = [
        compiled
        for n, pattern in enumerate(settings["passing"])
        if (compiled := _regex(pattern, f"passing[{n}]", problems)) is not None
    ]

    repeat_min = settings["repeat_min"]
    if repeat_min == 1:
        problems.append("repeat_min must be 0 (never) or 2 or more")
        repeat_min = DEFAULTS["repeat_min"]

    rules = []
    for n, rule in enumerate(settings["rules"]):
        what = f"rules[{n}]"
        if not isinstance(rule, dict):
            problems.append(f"{what} must be an object with {', '.join(RULE_KEYS)}")
            continue
        for key in rule:
            if key not in RULE_KEYS:
                problems.append(f"{what}: unknown key {key!r} (known: {', '.join(RULE_KEYS)})")
        name = rule.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"{what}.name must be a non-empty string")
            name = what
        command = _regex(rule.get("command"), f"{what}.command", problems)
        drop_patterns = rule.get("drop", [])
        if not isinstance(drop_patterns, list):
            problems.append(f"{what}.drop must be a list of regexes")
            drop_patterns = []
        drop = [c for i, p in enumerate(drop_patterns) if (c := _regex(p, f"{what}.drop[{i}]", problems)) is not None]
        counts = {}
        for key in ("head", "tail"):
            value = rule.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                problems.append(f"{what}.{key} must be a whole number of lines, 0 or more")
                value = 0
            counts[key] = value
        if not drop_patterns and not counts["head"] and not counts["tail"]:
            problems.append(f"{what} ({name}) does nothing; give it drop, head or tail")
        if command is not None:
            rules.append((name, command, drop, counts["head"], counts["tail"]))

    folder = settings["output_dir"].strip().strip("/")
    parts = PurePosixPath(folder).parts
    if not folder or settings["output_dir"].startswith(("/", "\\")) or ".." in parts or ":" in folder:
        problems.append("output_dir must be a folder inside the project, like .minimal/outputs (relative, no '..')")
        folder = OUTPUT_DIR
    return problems, messages, passing, rules, folder, repeat_min


def _python_tests(command, output, passing=None, message=MESSAGES["hidden"]):
    patterns = passing if passing is not None else [re.compile(p) for p in PASSING]
    lines = output.splitlines()
    kept = [line for line in lines if not any(p.fullmatch(line) for p in patterns)]
    hidden = len(lines) - len(kept)
    if not hidden:
        return None
    note = message.format(hidden=hidden)
    if kept and kept[-1].startswith("[exit "):
        kept.insert(len(kept) - 1, note)
    else:
        kept.append(note)
    return "\n".join(kept)


def _rule(name, drop, head, tail, messages):
    """The lens function of a ``rules`` entry: hide the ``drop`` lines, then keep ``head`` and ``tail`` lines of the rest."""

    def lens(command, output):
        lines = output.splitlines()
        footer = [lines.pop()] if lines and lines[-1].startswith("[exit ") else []
        kept = [line for line in lines if not any(p.fullmatch(line) for p in drop)]
        hidden = len(lines) - len(kept)
        omitted = max(0, len(kept) - head - tail) if head or tail else 0
        if omitted:
            kept = [*kept[:head], messages["rule_omitted"].format(name=name, omitted=omitted), *kept[len(kept) - tail :]]
        if not hidden and not omitted:
            return None
        if hidden:
            kept.append(messages["rule_hidden"].format(name=name, hidden=hidden))
        return "\n".join([*kept, *footer])

    return lens


def _repeat(output, repeat_min=3, message=MESSAGES["repeated"]):
    if not repeat_min:
        return output
    lines = output.split("\n")
    out, i = [], 0
    while i < len(lines):
        j = i
        while j + 1 < len(lines) and lines[j + 1] == lines[i]:
            j += 1
        run = j - i + 1
        out.append(lines[i])
        if run >= repeat_min:
            out.append(message.format(count=run - 1))
        else:
            out.extend(lines[i + 1 : j + 1])
        i = j + 1
    return "\n".join(out)


def _outputs(root, folder=OUTPUT_DIR):
    folder = Path(root, folder)
    return sorted(folder.glob("*.txt")) if folder.is_dir() else []


def _save_output(root, raw, folder=OUTPUT_DIR):
    numbers = [int(p.stem) for p in _outputs(root, folder) if p.stem.isdecimal()]
    n = max(numbers, default=0) + 1
    target = Path(root, folder)
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{n:04d}.txt").write_text(raw, encoding="utf-8")
    return n


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    problems, messages, passing, rules, folder, repeat_min = check_settings(settings)
    for problem in problems:
        minimal.report_problem(f"{problem} (ignored: the default applies)")
    min_chars, head, tail = settings["min_chars"], settings["head"], settings["tail"]
    state = {"on": settings["enabled"]}

    lenses = [(name, command.pattern, _rule(name, drop, h, t, messages), "(settings)") for name, command, drop, h, t in rules]
    if settings["python_tests"]:
        lenses.append(
            (
                "python-tests",
                r"\b(pytest|unittest)\b",
                lambda command, output: _python_tests(command, output, passing, messages["hidden"]),
                "(built-in)",
            )
        )

    def compress(event):
        raw = event["output"]
        if not state["on"] or event["name"] != "bash" or len(raw) < min_chars:
            return None
        command = event["input"].get("command", "")
        out = raw
        for name, pattern, lens, _ in lenses:
            if not re.search(pattern, command):
                continue
            try:
                result = lens(command, raw)
            except Exception as e:
                print(f"[lenses] {name} failed: {e}", file=sys.stderr)
                continue
            if isinstance(result, str) and result != raw:
                out = result
                break
        out = _repeat(out, repeat_min, messages["repeated"])
        if len(out) > head + tail:
            out = out[:head] + "\n" + messages["omitted"].format(chars=len(out) - head - tail) + "\n" + out[-tail:]
        if out == raw:
            return None
        n = _save_output(event["ctx"].cwd, raw, folder)
        out += "\n" + messages["saved"].format(path=f"{folder}/{n:04d}.txt", lines=len(raw.splitlines()))
        event["output"] = out
        return {"output": out}

    minimal.on("tool_result", compress)

    def prompt_note(ctx):
        if not state["on"] or not messages["prompt"]:
            return None
        return messages["prompt"].format(min_chars=min_chars, dir=folder)

    minimal.register_prompt_section("lenses", prompt_note)

    def switch(value):
        """Turn the lenses on, off or (``None``) the other way; returns the new state as a word."""
        state["on"] = (not state["on"]) if value is None else value
        return "on" if state["on"] else "off"

    def lenses_command(args, ctx):
        arg = args.strip()
        if arg in ("on", "off", "toggle"):
            print(f"Output lenses are {switch(None if arg == 'toggle' else arg == 'on')}.")
            return
        if arg not in ("", "clear"):
            raise ValueError("usage: /lenses [on|off|toggle|clear]")
        saved = _outputs(ctx.cwd, folder)
        if arg == "clear":
            for p in saved:
                p.unlink()
            print(f"Removed {len(saved)} saved output(s).")
            return
        for name, pattern, _, source in lenses:
            print(f"{name}  {pattern}  {source}")
        print(f"{len(saved)} saved output(s) in {folder}")
        if not state["on"]:
            print("Output lenses are off: /lenses on turns them back on.")

    minimal.register_command(
        "lenses",
        lenses_command,
        description="list output lenses; /lenses on|off switches them, /lenses clear deletes saved outputs",
        complete=lambda args, ctx: [w for w in ("on", "off", "toggle", "clear") if w.startswith(args)],
    )

    if settings["key"]:

        def toggle_key(ctx):
            """Turn the output lenses on or off."""
            ctx.notify(f"Output lenses are {switch(None)}.")

        try:
            minimal.register_keybinding(settings["key"], toggle_key, "turn the output lenses on or off", name="toggle")
        except ValueError as exc:
            minimal.report_problem(f"extensions.settings.lenses.key: {exc}; set it to \"\" for no key (the lenses work without it)")
