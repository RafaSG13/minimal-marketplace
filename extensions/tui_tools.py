"""Run terminal UIs (lazygit, yazi, btop, ...) from minimal with /<tool> or /tui, and tell you what they changed."""

__version__ = "1.1"
__api__ = "2.4"
__tags__ = ["workflow", "ui"]

import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
"""A tool name is typed as ``/<name>``: lowercase letters, digits, ``_`` and ``-``."""

ALWAYS_RESERVED = frozenset({"theme", "tui"})
"""Names a tool may never take besides ``minimal.builtin_commands()``: ``/tui`` is this extension's own and ``/theme`` is a
command only the terminal UI adds, so ``builtin_commands()`` lacks it until the first ``/reload``."""

FIELDS = ("command", "description", "cwd", "env", "enabled", "install", "git", "key")
CHOOSER = "{chooser}"
CWD = "{cwd}"


def _tool(command, description, install, git=False):
    return {
        "command": command,
        "description": description,
        "cwd": "",
        "env": {},
        "enabled": True,
        "install": install,
        "git": git,
        "key": "",
    }


BUILTIN_TOOLS = {
    "lazygit": _tool(["lazygit", "-p", CWD], "git UI", "brew install lazygit", git=True),
    "yazi": _tool(
        ["yazi", f"--chooser-file={CHOOSER}", CWD], "file manager; the files you pick are listed as @mentions", "brew install yazi"
    ),
    "btop": _tool(["btop"], "resource monitor", "brew install btop"),
    "lazydocker": _tool(["lazydocker"], "Docker UI", "brew install lazydocker"),
    "k9s": _tool(["k9s"], "Kubernetes UI", "brew install k9s"),
    "gh-dash": _tool(
        ["gh", "dash"],
        "GitHub pull requests and issues dashboard",
        "brew install gh && gh extension install dlvhdr/gh-dash",
    ),
    "tig": _tool(["tig"], "git history browser", "brew install tig", git=True),
    "gitui": _tool(["gitui"], "git UI", "brew install gitui", git=True),
}
"""The tools minimal knows how to run. ``command`` may use ``{cwd}`` (the tool's working directory) and ``{chooser}`` (a
temporary file the tool writes the paths it chose to: they are listed after it exits)."""

DEFAULTS = {
    "enabled": True,
    "tools": {},
    "change_note": True,
    "chooser_prefix": "@",
    "chooser_max": 20,
    "chooser_to_draft": True,
    "report_with": "show",
}

SCHEMA = {
    "enabled": {"description": "Register the /tui command and a /<tool> command for each tool found; false registers nothing."},
    "tools": {
        "description": "Tools by name, merged over the built-in ones (lazygit, yazi, btop, lazydocker, k9s, gh-dash, tig, gitui) "
        "field by field: {\"name\": {\"command\": [argv...], \"description\", \"cwd\", \"env\", \"enabled\", \"install\", "
        "\"git\", \"key\"}}. {cwd} and {chooser} in command are replaced; a new tool needs a command; "
        "{\"lazygit\": {\"enabled\": false}} turns a built-in off; \"key\" binds a key to the tool (it runs the tool "
        "directly, as a terminal key). The global, project and local settings are merged tool by tool, so a project "
        "adds or changes one tool without replacing yours. A bad entry is skipped with a warning; the others load.",
        "merge": "deep",
    },
    "change_note": {"description": "After a git tool exits, say in one line if it changed the branch or the changed files."},
    "chooser_prefix": {"description": "Put before each path a file chooser (yazi) picked, so it can be pasted as a mention."},
    "chooser_max": {"description": "Most chosen paths shown right after the tool exits (/tui last lists all).", "min": 1, "max": 1000},
    "chooser_to_draft": {"description": "Add the paths a file chooser (yazi) picked to the end of your message box, so they are ready to send."},
    "report_with": {
        "description": "How a tool reports (exit status, chosen paths, git changes): \"show\" adds a block to the transcript that stays, "
        "\"notify\" shows a toast that vanishes (/tui last always repeats it).",
        "enum": ["show", "notify"],
    },
}


def parse_tools(overrides, reserved):
    """``(tools, problems)``: :data:`BUILTIN_TOOLS` with the user's ``overrides`` merged in, and one text per bad entry.

    A bad entry is skipped whole (a built-in it tried to change stays as it is); the other entries still count.
    ``reserved`` are the names a tool may not take.
    """
    where = "extensions.settings.tui_tools.tools"
    problems = []
    tools = {name: {**tool, "command": list(tool["command"]), "env": dict(tool["env"])} for name, tool in BUILTIN_TOOLS.items()}
    for name, user in overrides.items():
        at = f"{where}.{name}"
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            problems.append(f"{where}: {name!r} is not a tool name (it is typed as /name: lowercase letters, digits, _ and -); entry skipped")
            continue
        if name in reserved:
            problems.append(f"{at}: /{name} is a command of minimal itself; give the tool another name (entry skipped)")
            continue
        if not isinstance(user, dict):
            problems.append(f"{at} must be an object such as {{\"command\": [\"{name}\"]}} (entry skipped)")
            continue
        unknown = [key for key in user if key not in FIELDS]
        if unknown:
            problems.append(f"{at}: unknown field {unknown[0]!r} (known: {', '.join(FIELDS)}); entry skipped")
            continue
        if name not in tools and "command" not in user:
            problems.append(f"{at}.command is required for a tool minimal does not know: set it to a list such as [\"{name}\"] (entry skipped)")
            continue
        entry = {**tools[name]} if name in tools else _tool([], f"run {name}", "", git=False)
        entry.update(user)
        bad = [
            f"{at}.{field} must be {expected}"
            for field, ok, expected in (
                ("command", _strings(entry["command"], required=True), "a non-empty list of non-empty strings, e.g. [\"btop\"]"),
                ("description", isinstance(entry["description"], str), "text"),
                ("cwd", isinstance(entry["cwd"], str), "a folder (relative to the project) or \"\" for the project"),
                ("env", isinstance(entry["env"], dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in entry["env"].items()), "an object of text values, e.g. {\"EDITOR\": \"vim\"}"),
                ("enabled", isinstance(entry["enabled"], bool), "true or false"),
                ("install", isinstance(entry["install"], str), "text telling how to install it"),
                ("git", isinstance(entry["git"], bool), "true or false"),
                ("key", isinstance(entry["key"], str), "a key such as \"ctrl+g\" or \"\" for none"),
            )
            if not ok
        ]
        if bad:
            problems.append(f"{'; '.join(bad)} (entry skipped)")
            continue
        tools[name] = entry
    return tools, problems


def _strings(value, *, required=False):
    return (
        isinstance(value, list)
        and (bool(value) or not required)
        and all(isinstance(part, str) and part for part in value)
    )


def _env(entry):
    return {**os.environ, **entry["env"]}


def find_executable(entry):
    """The path of the tool's executable in the PATH it will run with, or ``None``."""
    return shutil.which(os.path.expanduser(entry["command"][0]), path=_env(entry).get("PATH"))


def project_dir(entry, project):
    """The folder the tool runs in: ``cwd`` made absolute against the project (``~`` allowed), default the project."""
    if not entry["cwd"]:
        return Path(project)
    return Path(project, os.path.expanduser(entry["cwd"]))


def missing_text(name, entry):
    exe = entry["command"][0]
    how = entry["install"] or f"install it, or set extensions.settings.tui_tools.tools.{name}.command to the right executable"
    return f"{name} is not installed ({exe!r} is not on PATH): {how}; then /reload."


def git_snapshot(cwd):
    """``(branch line, changed-file lines)`` of the repository at ``cwd``, or ``None`` outside one."""
    try:
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "--no-optional-locks", "status", "--porcelain", "--branch"],
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = result.stdout.splitlines()
    if result.returncode != 0 or not lines or not lines[0].startswith("## "):
        return None
    return lines[0][3:], lines[1:]


def change_line(name, before, after):
    """One line saying what a git tool changed between two :func:`git_snapshot` results, or ``None`` if nothing."""
    parts = []
    if before[0] != after[0]:
        parts.append(f"branch {before[0].split('...')[0]} -> {after[0].split('...')[0]}")
    if before[1] != after[1]:
        parts.append(f"{len(before[1])} -> {len(after[1])} changed files")
    return f"{name} changed the working tree: {', '.join(parts)}." if parts else None


def chosen_paths(chooser, project, prefix):
    """The paths a chooser file lists: inside ``project`` relative to it with ``prefix`` (a mention; none if the path has
    spaces or an ``@``), elsewhere absolute and as they are."""
    try:
        raw = [line.strip() for line in Path(chooser).read_text(encoding="utf-8", errors="replace").splitlines()]
    except OSError:
        return []
    root = Path(project).resolve()
    shown = []
    for line in filter(None, raw):
        try:
            text = str(Path(line).resolve().relative_to(root))
        except (OSError, ValueError):
            shown.append(line)
            continue
        shown.append(text if re.search(r"[\s@]", text) else prefix + text)
    return shown


def draft_text(paths):
    """``paths`` as one run of words for the message box: a path with spaces is quoted, the rest stay as mentions."""
    return " ".join(f'"{path}"' if re.search(r"\s", path) else path for path in paths)


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    tools, problems = parse_tools(settings["tools"], minimal.builtin_commands() | ALWAYS_RESERVED)
    for problem in problems:
        minimal.report_problem(problem)
    state = {"last": [], "registered": set()}

    def say(ctx, lines, kind="info", full=None):
        """Report ``lines`` (a terminal command's printed output is gone when the interface returns, so a block that stays,
        or a toast with ``report_with: notify``) and keep ``full`` (default ``lines``) for ``/tui last``."""
        state["last"] = list(full or lines)
        text = "\n".join(lines)
        if settings["report_with"] == "show":
            ctx.show(text, "error" if kind == "error" else "output")
        else:
            ctx.notify(text, kind)

    def to_draft(ctx, paths):
        """Append ``paths`` to the message box; ``False`` if there is none (plain terminal) or it did not change."""
        before = ctx.ui.get_draft()
        lead = " " if before and not before[-1].isspace() else ""
        ctx.ui.set_draft(f"{lead}{draft_text(paths)} ", append=True)
        return ctx.ui.get_draft() != before

    def launch(name, args, ctx):
        entry = tools[name]
        exe = find_executable(entry)
        if exe is None:
            say(ctx, [missing_text(name, entry)], "error")
            return
        try:
            extra = shlex.split(args)
        except ValueError as exc:
            say(ctx, [f"/{name}: cannot read the arguments ({exc}); close the quote or remove it."], "error")
            return
        cwd = project_dir(entry, ctx.cwd)
        if not cwd.is_dir():
            say(
                ctx,
                [f"/{name}: {cwd} is not a folder; fix extensions.settings.tui_tools.tools.{name}.cwd."],
                "error",
            )
            return
        template = entry["command"][1:]
        chooser = None
        try:
            if any(CHOOSER in part for part in template):
                fd, chooser = tempfile.mkstemp(prefix="minimal-tui-", suffix=".chooser")
                os.close(fd)
            argv = [exe]
            argv += [part.replace(CWD, str(cwd)).replace(CHOOSER, chooser or "") for part in template] + extra
            before = git_snapshot(cwd) if entry["git"] and settings["change_note"] else None
            lines, full, kind = [], [], "info"  # what the notice shows, and what /tui last keeps

            def add(text):
                lines.append(text)
                full.append(text)

            try:
                status = subprocess.run(argv, cwd=cwd, env=_env(entry)).returncode
            except KeyboardInterrupt:
                status = None
                add(f"{name} was interrupted.")
            except OSError as exc:
                say(
                    ctx,
                    [f"/{name}: could not run {exe} ({exc.strerror or exc}); check extensions.settings.tui_tools.tools.{name}.command."],
                    "error",
                )
                return
            if status:
                add(f"{name} exited with status {status}.")
                kind = "warning"
            if chooser is not None:
                paths = chosen_paths(chooser, ctx.cwd, settings["chooser_prefix"])
                if paths:
                    shown = paths[: settings["chooser_max"]]
                    placed = settings["chooser_to_draft"] and to_draft(ctx, paths)
                    where = "added to your message" if placed else "paste or type them in your message"
                    add(f"{name} chose {len(paths)} path{'s' * (len(paths) != 1)}: {where}")
                    lines += shown
                    full += paths
                    if len(paths) > len(shown):
                        lines.append(f"... and {len(paths) - len(shown)} more (/tui last lists all)")
            if entry["git"]:
                ctx.git()  # makes sure the shared poller runs
                if before is not None and (after := git_snapshot(cwd)) is not None and (note := change_line(name, before, after)):
                    add(note)
                ctx.git_refresh()  # a terminal command's end asks it too, but a key's does not
            ctx.invalidate()
            if lines:
                say(ctx, lines, kind, full)
        finally:
            if chooser is not None:
                try:
                    os.unlink(chooser)
                except OSError:
                    pass

    def runner(name):
        return lambda args, ctx: launch(name, args, ctx)

    def keyer(name):
        # A terminal key runs on the UI thread with the interface suspended, like the terminal command.
        return lambda ctx: launch(name, "", ctx)

    for name, entry in tools.items():
        if not entry["enabled"] or find_executable(entry) is None:
            continue
        hint = f"{entry['description']}: /{name} [args]"
        minimal.register_command(name, runner(name), description=hint, terminal=True)
        state["registered"].add(name)
        if entry["key"]:
            try:
                minimal.register_keybinding(entry["key"], keyer(name), f"open {name}", name=name, terminal=True)
            except ValueError as exc:
                minimal.report_problem(f"extensions.settings.tui_tools.tools.{name}.key: {exc}; /{name} works without the key")

    def listing(ctx):
        print("Terminal tools (open with /<name> [args] or /tui <name> [args]; add or change them in /ext settings tui_tools):")
        for name, entry in tools.items():
            if not entry["enabled"]:
                status = "disabled"
            elif (exe := find_executable(entry)) is None:
                status = f"missing: {entry['install'] or 'not on PATH'}"
            elif name in state["registered"]:
                status = f"ready ({exe})"
            else:
                status = f"installed since the last load ({exe}): /reload to add /{name}"
            key = f"  [{entry['key']}]" if entry["key"] else ""
            print(f"  {name:<12}{status}{key}  {entry['description']}")
        print("/tui last shows what the last tool reported (the paths a file chooser picked).")

    def tui(args, ctx):
        """List the terminal tools, run one (/tui <name> [args]), or show the last report (/tui last)."""
        word, _, rest = args.partition(" ")
        if word in ("", "list"):
            listing(ctx)
        elif word == "last":
            print("\n".join(state["last"]) if state["last"] else "No tool has reported anything yet.")
        elif word not in tools:
            print(f"Unknown tool {word!r}. Known: {', '.join(tools)}; add one in extensions.settings.tui_tools.tools (/ext settings tui_tools).")
        elif not tools[word]["enabled"]:
            print(f"{word} is disabled: set extensions.settings.tui_tools.tools.{word}.enabled to true.")
        elif find_executable(tools[word]) is None:
            print(missing_text(word, tools[word]))
        elif word not in state["registered"]:
            print(f"{word} was installed after minimal loaded its extensions: run /reload, then /{word}.")
        else:
            # This command only prints; the tool's own command takes the terminal. Queueing it runs it as typed.
            ctx.queue_user_message(f"/{word} {rest.strip()}".rstrip())

    def complete(args, ctx):
        if " " in args:
            return []
        return [name for name in (*tools, "last", "list") if name.startswith(args)]

    minimal.register_command("tui", tui, description="list terminal tools (lazygit, yazi, btop...), or open one: /tui [name [args]|last]", complete=complete)
