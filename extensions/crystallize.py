"""Crystallize: turn repeated commands into tools and denials into AGENTS.md rules.

/crystallize scans past sessions for commands the model ran again and again
and for calls you denied, and lets you keep them as a tool or a rule.
"""

__version__ = "1.2"
__api__ = "1"

import json
import re
from collections import Counter
from pathlib import Path

from minimal.api import USER_DENIED, result_text

STATE = ".minimal/state/crystallize.json"
USAGE = "usage: /crystallize [all]"
DENIED = "Error: " + USER_DENIED
SKIP_FIRST = {"ls", "cd", "pwd", "cat", "echo", "head", "tail", "grep", "rg", "find", "sed", "wc"}
RULES_HEADING = "## Learned rules"

TOOL_TEMPLATE = '''"""__NAME__: runs `__DOC__` (crystallized from __RUNS__ runs)."""

__version__ = "1.0"
__api__ = "1"

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


def _state(root):
    data = _load(Path(root, STATE), None)
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


def _rule_text(name, detail):
    if name == "bash":
        return f"Do not run `{detail}` without asking first."
    if name in ("write", "edit"):
        return f"Do not modify {detail} without asking first."
    return f"Do not call {name} without asking first."


def _scan(ctx, session_ids, known_tools, known_rules):
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
                    texts[key] = _rule_text(name, detail)
                    if not hints.get(key):
                        nxt = next(
                            (m["content"] for m in messages[mi + 1 :] if m.get("role") == "user" and isinstance(m.get("content"), str)),
                            "",
                        )
                        hints[key] = nxt[:60]
    habits = []
    for command, count in runs.most_common():
        words = command.split()
        if count < 3 or len(command) > 200 or not words or words[0] in SKIP_FIRST or command in known_tools:
            continue
        habits.append({"command": command, "runs": count, "sessions": len(where[command])})
    rules = [
        {"key": key, "text": texts[key], "count": count, "hint": hints.get(key, "")}
        for key, count in denied.most_common()
    ]
    return habits[:10], rules[:10]


def _crystallize(args, ctx):
    arg = args.strip()
    if arg not in ("", "all"):
        raise ValueError(USAGE)
    root = Path(ctx.cwd)
    state = _state(root)
    ids = [] if arg == "all" else state["sessions"]
    if not ids:
        if arg != "all":
            print("No sessions indexed for this project yet; scanning all sessions.")
        ids = sorted(ctx.sessions())
    habits, rules = _scan(ctx, ids, set(state["tools"].values()), set(state["rules"]))
    if not habits and not rules:
        print("Nothing to crystallize yet.")
        return
    options = [
        (f"tool:{i}", f"tool  {h['runs']}x in {h['sessions']} session(s)  {h['command'][:70]}", False)
        for i, h in enumerate(habits)
    ] + [
        (
            f"rule:{i}",
            f"rule  {r['text']}  (denied {r['count']}x)" + (f' · then: "{r["hint"]}"' if r["hint"] else ""),
            False,
        )
        for i, r in enumerate(rules)
    ]
    ticked = ctx.ui.choose_many("Crystallize · tick what to keep", options)
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
        elif not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            print(f"Skipped: {name!r} is not a valid tool name (use [a-z][a-z0-9_]*)")
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
        agents = root / "AGENTS.md"
        try:
            text = agents.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if RULES_HEADING not in text.splitlines():
            text += f"\n{RULES_HEADING}\n"
        elif not text.endswith("\n"):
            text += "\n"
        text += "".join(f"- {r['text']}\n" for r in chosen)
        agents.write_text(text, encoding="utf-8")
        state["rules"].extend(r["key"] for r in chosen)
        print(f"Added {len(chosen)} rule(s) to AGENTS.md")

    _save(root / STATE, state)
    if wrote:
        print(ctx.reload())


def register(minimal):
    def on_turn_end(event):
        ctx = event.get("ctx")
        if ctx is None or event.get("nested") or event["messages"] is not ctx.messages:
            return None
        root = Path(ctx.cwd)
        state = _state(root)
        if ctx.session_id not in state["sessions"]:
            state["sessions"].append(ctx.session_id)
            _save(root / STATE, state)
        return None

    minimal.on("turn_end", on_turn_end)
    minimal.register_command(
        "crystallize",
        _crystallize,
        description="turn repeated commands into tools and denials into AGENTS.md rules",
    )
