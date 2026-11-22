"""Crystallize: turn repeated commands into tools and denials into AGENTS.md rules.

/crystallize scans past sessions for commands the model ran again and again
and for calls you denied, and lets you keep them as a tool or a rule. Settings
(`/ext settings crystallize`) set how many runs make a habit, which commands are
ignored, how many suggestions are listed, the rule wording, the rules file and
heading, and the valid tool names.
"""

__version__ = "1.7"
__api__ = "2.4"
__tags__ = ["workflow"]

import json
import re
from collections import Counter
from pathlib import Path

from minimal.api import USER_DENIED, result_text

STATE_FILE = None
USAGE = "usage: /crystallize [all]"
DENIED = "Error: " + USER_DENIED
SKIP_FIRST = {"ls", "cd", "pwd", "cat", "echo", "head", "tail", "grep", "rg", "find", "sed", "wc"}
RULES_HEADING = "## Learned rules"
RULES_FILE = "AGENTS.md"
NAME_PATTERN = "[a-z][a-z0-9_]*"
BASH_RULE = "Do not run `{detail}` without asking first."
FILE_RULE = "Do not modify {detail} without asking first."
OTHER_RULE = "Do not call {name} without asking first."
DIALOG_TITLE = "Crystallize · tick what to keep"
RULE_FIELDS = ("bash_rule", "file_rule", "other_rule")

DEFAULTS = {
    "enabled": True,
    "min_runs": 3,
    "max_command_chars": 200,
    "skip_commands": sorted(SKIP_FIRST),
    "max_habits": 10,
    "max_rules": 10,
    "hint_chars": 60,
    "label_chars": 70,
    "tool_name_pattern": NAME_PATTERN,
    "rules_file": RULES_FILE,
    "rules_heading": RULES_HEADING,
    "bash_rule": BASH_RULE,
    "file_rule": FILE_RULE,
    "other_rule": OTHER_RULE,
    "dialog_title": DIALOG_TITLE,
}

SCHEMA = {
    "enabled": {"description": "Register /crystallize and index sessions; false registers nothing."},
    "min_runs": {"description": "Times the model must have run the same bash command to suggest a tool.", "min": 2, "max": 1000},
    "max_command_chars": {"description": "Longest command suggested as a tool.", "min": 10, "max": 5000},
    "skip_commands": {
        "description": "First words of commands never suggested as tools (inspection commands, by default)."
    },
    "max_habits": {"description": "Most tool suggestions listed.", "min": 0, "max": 100},
    "max_rules": {"description": "Most rule suggestions listed.", "min": 0, "max": 100},
    "hint_chars": {"description": "Characters of your reply to a denial shown next to its rule (0: none).", "min": 0, "max": 500},
    "label_chars": {"description": "Characters of a command shown in the list of suggestions.", "min": 10, "max": 500},
    "tool_name_pattern": {"description": "Regular expression a tool name you type must fully match."},
    "rules_file": {"description": "File, relative to the project, that receives the rules you keep."},
    "rules_heading": {"description": "Heading line under which the kept rules are listed in that file."},
    "bash_rule": {"description": "Rule for a denied bash command; {detail} is the command."},
    "file_rule": {"description": "Rule for a denied write or edit; {detail} is the path."},
    "other_rule": {"description": "Rule for any other denied tool; {name} is the tool, {detail} its input."},
    "dialog_title": {"description": "Title of the list of suggestions."},
}


def check_settings(settings):
    """``(settings, problems)``: ``settings`` as a dict where each key that is inconsistent beyond what the schema checks is
    back to its default, and one text per fix."""
    fixed, problems = dict(settings), []
    where = "extensions.settings.crystallize."

    def reset(name, why):
        problems.append(f"{where}{name} {why}; the default is used until you fix it")
        fixed[name] = DEFAULTS[name]

    if not all(isinstance(c, str) and c for c in fixed["skip_commands"]):
        reset("skip_commands", "must be a list of non-empty command names")
    try:
        re.compile(fixed["tool_name_pattern"])
    except re.error as exc:
        reset("tool_name_pattern", f"is not a valid regular expression ({exc})")
    for name in RULE_FIELDS:
        try:
            text = fixed[name].format(name="n", detail="d")
        except (KeyError, IndexError, ValueError, AttributeError) as exc:
            reset(
                name,
                f"is not a valid template ({exc!r}); use only {{name}} and {{detail}}, and write literal braces as {{{{ and }}}}",
            )
            continue
        if not text.strip() or "\n" in text:
            reset(name, "must be one non-empty line")
    heading = fixed["rules_heading"]
    if not heading.strip() or "\n" in heading:
        reset("rules_heading", "must be one non-empty line")
    rules_file = Path(fixed["rules_file"])
    if not fixed["rules_file"] or rules_file.is_absolute() or ".." in rules_file.parts:
        reset("rules_file", "must be a path inside the project, such as AGENTS.md")
    return fixed, problems


TOOL_TEMPLATE = '''"""__NAME__: runs `__DOC__` (crystallized from __RUNS__ runs)."""

__version__ = "1.0"
__api__ = "2"

COMMAND = __COMMAND__


def register(minimal):
    bash = minimal.tools["bash"].run
    minimal.register_tool(
        name=__TOOLNAME__,
        run=lambda input, ctx: bash({"command": COMMAND}, ctx),
        description=f"Run `{COMMAND}` in the working directory and return its output. Runs without asking: the user approved this exact command.",
    )
'''


def _render(values):
    return re.sub(r"__([A-Z]+)__", lambda m: values.get(m.group(1), m.group(0)), TOOL_TEMPLATE)


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _state():
    data = _load(STATE_FILE, None)
    if not isinstance(data, dict):
        data = {}
    return {
        "sessions": list(data.get("sessions") or []),
        "tools": dict(data.get("tools") or {}),
        "rules": list(data.get("rules") or []),
    }


def _messages(ctx, session_id):
    try:
        messages = ctx.read_session(str(session_id))
    except (ValueError, OSError):
        return []
    return [m for m in messages if isinstance(m, dict)]


def _rule_text(name, detail, settings):
    if name == "bash":
        template = settings["bash_rule"]
    elif name in ("write", "edit"):
        template = settings["file_rule"]
    else:
        template = settings["other_rule"]
    return template.format(name=name, detail=detail)


def _scan(ctx, session_ids, known_tools, known_rules, settings):
    runs, where = Counter(), {}
    denied, hints, texts = Counter(), {}, {}
    for sid in session_ids:
        messages = _messages(ctx, sid)
        uses = {}
        for mi, message in enumerate(messages):
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                    uses[block.get("id")] = block
                    command = block["input"].get("command")
                    if block.get("name") == "bash" and isinstance(command, str):
                        normal = " ".join(command.split())
                        runs[normal] += 1
                        where.setdefault(normal, set()).add(sid)
                elif block.get("type") == "tool_result" and block.get("is_error"):
                    if not result_text(block.get("content")).startswith(DENIED):
                        continue
                    use = uses.get(block.get("tool_use_id"))
                    if not use:
                        continue
                    name, inp = use.get("name", "?"), use["input"]
                    detail = inp.get("command") if name == "bash" else (inp.get("path") or json.dumps(inp))
                    key = f"{name}:{detail}"
                    if key in known_rules:
                        continue
                    denied[key] += 1
                    texts[key] = _rule_text(name, detail, settings)
                    if not hints.get(key):
                        nxt = next(
                            (m["content"] for m in messages[mi + 1 :] if m.get("role") == "user" and isinstance(m.get("content"), str)),
                            "",
                        )
                        hints[key] = nxt[: settings["hint_chars"]]
    habits = []
    skip = set(settings["skip_commands"])
    for command, count in runs.most_common():
        words = command.split()
        if (
            count < settings["min_runs"]
            or len(command) > settings["max_command_chars"]
            or not words
            or words[0] in skip
            or command in known_tools
        ):
            continue
        habits.append({"command": command, "runs": count, "sessions": len(where[command])})
    rules = [
        {"key": key, "text": texts[key], "count": count, "hint": hints.get(key, "")}
        for key, count in denied.most_common()
    ]
    return habits[: settings["max_habits"]], rules[: settings["max_rules"]]


def _crystallize(args, ctx, settings):
    arg = args.strip()
    if arg not in ("", "all"):
        raise ValueError(USAGE)
    root = Path(ctx.cwd)
    state = _state()
    ids = [] if arg == "all" else state["sessions"]
    if not ids:
        if arg != "all":
            print("No sessions indexed for this project yet; scanning all sessions.")
        ids = sorted(ctx.sessions())
    habits, rules = _scan(ctx, ids, set(state["tools"].values()), set(state["rules"]), settings)
    if not habits and not rules:
        print("Nothing to crystallize yet.")
        return
    options = [
        (f"tool:{i}", f"tool  {h['runs']}x in {h['sessions']} session(s)  {h['command'][: settings['label_chars']]}", False)
        for i, h in enumerate(habits)
    ] + [
        (
            f"rule:{i}",
            f"rule  {r['text']}  (denied {r['count']}x)" + (f' · then: "{r["hint"]}"' if r["hint"] else ""),
            False,
        )
        for i, r in enumerate(rules)
    ]
    ticked = ctx.ui.choose_many(settings["dialog_title"], options)
    if ticked is None:
        print("Cancelled.")
        return
    if not ticked:
        print("Nothing selected.")
        return

    wrote = False
    for value in ticked:
        kind, _, index = value.partition(":")
        if kind != "tool":
            continue
        habit = habits[int(index)]
        command = habit["command"]
        name = ctx.ui.ask_text(f"Tool name for: {command[:60]}")
        name = name.strip() if isinstance(name, str) else None
        target = root / ".minimal" / "extensions" / "tools" / f"{name}.py"
        if name is None:
            print("Skipped: no name given")
        elif not re.fullmatch(settings["tool_name_pattern"], name):
            print(f"Skipped: {name!r} is not a valid tool name (use {settings['tool_name_pattern']})")
        elif name in ctx.tools:
            print(f"Skipped: a tool named {name} already exists")
        elif target.exists():
            print(f"Skipped: {target.relative_to(root).as_posix()} already exists")
        else:
            doc = command.replace("\\", "\\\\").replace('"', '\\"')
            source = _render({"DOC": doc, "NAME": name, "RUNS": str(habit["runs"]), "COMMAND": repr(command), "TOOLNAME": repr(name)})
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
            state["tools"][name] = command
            wrote = True
            print(f"Tool written: .minimal/extensions/tools/{name}.py")

    chosen = [rules[int(v.partition(":")[2])] for v in ticked if v.startswith("rule:")]
    if chosen:
        agents = root / settings["rules_file"]
        try:
            text = agents.read_text(encoding="utf-8")
        except OSError:
            text = ""
        heading = settings["rules_heading"]
        if heading not in text.splitlines():
            text += f"\n{heading}\n"
        elif not text.endswith("\n"):
            text += "\n"
        text += "".join(f"- {r['text']}\n" for r in chosen)
        agents.parent.mkdir(parents=True, exist_ok=True)
        agents.write_text(text, encoding="utf-8")
        state["rules"].extend(r["key"] for r in chosen)
        print(f"Added {len(chosen)} rule(s) to {settings['rules_file']}")

    _save(STATE_FILE, state)
    if wrote:
        print(ctx.reload())


def register(minimal):
    global STATE_FILE
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    settings, problems = check_settings(settings)
    for problem in problems:
        minimal.report_problem(problem)
    STATE_FILE = minimal.data_dir() / "state.json"

    def on_turn_end(event):
        ctx = event.get("ctx")
        if ctx is None or event.get("nested") or event["messages"] is not ctx.messages:
            return None
        state = _state()
        if ctx.session_id not in state["sessions"]:
            state["sessions"].append(ctx.session_id)
            _save(STATE_FILE, state)
        return None

    minimal.on("turn_end", on_turn_end)
    minimal.register_command(
        "crystallize",
        lambda args, ctx: _crystallize(args, ctx, settings),
        description="turn repeated commands into tools and denials into AGENTS.md rules",
    )
