"""Creator: lets the model write, check, version, list, remove and catalogue extensions, tools, widgets and themes (/create).

Its skeletons and ``ext_api`` teach the current API (typed settings, panel titles, ``read_only`` tools, keys, CSS), and
``ext_check`` also lints what ``minimal ext check`` cannot: the marketplace ``__tags__``, an ``__api__`` older than the
features used, settings declared without a schema. Settings (``/ext settings creator``): ``check_timeout`` (seconds),
``default_scope`` (where ``ext_new`` writes), ``lint`` (the extra checks) and ``prompt`` (the system-prompt note).
"""

import ast
import inspect
import re
import shutil
import subprocess
import sys
from pathlib import Path

import minimal.api
from minimal.api import API_VERSION

__version__ = "1.1"
__api__ = "2.3"
__tags__ = ["workflow"]

NAME_RE = re.compile(r"[a-z0-9][a-z0-9_]*")
"""Valid item names (always ``fullmatch``): what the marketplace and the loader accept."""

CATEGORIES = {"extension": "extensions", "tool": "tools", "widget": "widgets", "theme": "themes"}
"""Item kind to marketplace category; ``extensions`` items live directly in the extensions folder."""

SUBFOLDERS = ("themes", "tools", "widgets")
"""The category folders inside an extensions folder."""

CHECK_TIMEOUT = 120
"""Seconds ``ext_check`` waits for ``minimal ext check``."""

VERSION_RE = re.compile(r'^__version__\s*=\s*"(\d+)\.(\d+)"', re.M)
"""The top-level ``__version__`` that ``ext_bump`` rewrites."""

EXTENSION_TEMPLATE = '''"""__NAME__: one line saying what it does."""

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["workflow"]

DEFAULTS = {"enabled": True, "message": "__NAME__: {turns} turns finished since the last reload", "key": ""}

SCHEMA = {
    "enabled": {"description": "Count turns; false registers nothing."},
    "message": {"description": "What /__NAME__ prints; {turns} is the number of turns."},
    "key": {"description": "Key that runs /__NAME__ (for example ctrl+o); empty: no key."},
}


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    turns = 0

    @minimal.on("turn_end")
    def count(event):
        nonlocal turns
        turns += 1

    def show(args, ctx):
        print(settings["message"].replace("{turns}", str(turns)))

    minimal.register_command("__NAME__", show, description="show how many turns finished")
    if settings["key"]:
        minimal.register_keybinding(settings["key"], lambda ctx: show("", ctx), "show turns", name="__NAME__")
'''

TOOL_TEMPLATE = '''"""__NAME__ tool: one line saying what the model gets from it."""

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["workflow"]

DEFAULTS = {"max_chars": 2000}

SCHEMA = {"max_chars": {"description": "Longest text the tool accepts.", "min": 1, "max": 100000}}


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)

    def run(input, ctx):
        text = str(input.get("text", "")).strip()
        if not text:
            raise ValueError("__NAME__ needs a non-empty text")
        if len(text) > settings["max_chars"]:
            raise ValueError(f"__NAME__: text is over {settings['max_chars']} characters (setting max_chars); send less")
        return text.upper()

    minimal.register_tool(
        name="__NAME__",
        run=run,
        read_only=True,  # changes nothing and is thread-safe: several calls in one reply run side by side
        description="Return `text` in upper case. Replace this with what the tool does and when to call it.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "The text to convert"}},
            "required": ["text"],
        },
    )
'''

WIDGET_TEMPLATE = '''"""__NAME__: a sidebar panel with the project folder and the model in use."""

from pathlib import Path

from minimal.api import WIDGET_AREAS

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["ui"]

DEFAULTS = {"enabled": True, "title": "__NAME__", "area": "sidebar", "order": 0}

SCHEMA = {
    "enabled": {"description": "Show the panel; false registers nothing."},
    "title": {"description": "Heading above the panel (empty: no heading)."},
    "area": {"description": "Where the panel goes by default (/ui move changes it).", "enum": list(WIDGET_AREAS)},
    "order": {"description": "Position among the panels of the area (lower first).", "min": -100, "max": 100},
}


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return

    def render(ctx):
        return [(Path(ctx.cwd).name, "bold $accent"), (f"{ctx.provider_name} · {ctx.model}", "muted")]

    minimal.register_panel(
        "__NAME__",
        render,
        area=settings["area"],
        order=settings["order"],
        title=settings["title"] or None,
        collapsible=True,
    )
'''

THEME_TEMPLATE = '''"""__NAME__: a dark theme; only background, foreground and accent are required."""

__version__ = "1.0"
__api__ = "2"
__tags__ = ["theme"]


def register(minimal):
    minimal.register_theme("__NAME__", dark=True, background="#1e2228", foreground="#c8ccd4", accent="#61afef")
'''

TEMPLATES = {
    "extension": EXTENSION_TEMPLATE,
    "tool": TOOL_TEMPLATE,
    "widget": WIDGET_TEMPLATE,
    "theme": THEME_TEMPLATE,
}
"""The skeleton of each kind, with ``__NAME__`` where the name goes."""

PROMPT = (
    "To create or change an extension, tool, widget or theme: ext_search first, ext_list to see what is installed, "
    "ext_new (or ext_template), edit, ext_check, ext_bump on every change, reload_extensions, then ext_catalogue_row "
    "and ext_publish if asked. Read ext_api for the API and the conventions (every knob a typed setting with a schema, "
    "read_only tools when safe, __tags__, the lowest __api__ that fits); keep state in minimal.data_dir(). "
    "ext_remove deletes an extension you created."
)

TAGS = ("git", "ui", "safety", "context", "agents", "provider", "theme", "diagnostics", "workflow")
"""The marketplace's ``__tags__``."""

FEATURE_API = (2, 3)
"""The API minor whose features :func:`lint` looks for; an item using one declares at least this ``__api__``."""

GUIDE = '''# Writing for API 2.3 (the rules the marketplace follows)

Header: a one-line module docstring, `__version__ = "1.0"` (bump it on every change: minor when additive, major when a
setting, command or behaviour was renamed or removed), `__api__ = "2.3"` only if the item uses an API 2.3 feature
(otherwise keep the lowest API it needs, so older minimals still load it), `__tags__` from: git ui safety context agents
provider theme diagnostics workflow.

Settings: every user-facing knob (limit, pattern, message, threshold, glyph, enable/disable) is a validated setting whose
default is what the item does without any:

    DEFAULTS = {"enabled": True, "rows": 12}
    SCHEMA = {
        "enabled": {"description": "Show the panel; false registers nothing."},
        "rows": {"description": "Most rows listed.", "min": 1, "max": 200},   # also: "enum": [...]
    }
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)    # read-only mapping; /ext settings <id> lists them

A value outside the schema is a load error naming `extensions.settings.<id>.<key>`; the default stays. Settings a schema
cannot check (patterns, formats) are validated in `register` or at use: raise ValueError saying what is wrong and how
to fix it, never crash on them.

Tools: `minimal.register_tool(name=, run=, description=, input_schema=, confirm=False, read_only=False)`; `run(input, ctx)`
returns text (or text/image blocks) and raises ValueError with the fix for bad input. `read_only=True` only when the
tool changes nothing and is thread-safe: a run of such calls in one reply executes concurrently. During long work call
`ctx.progress("one line")` (and `ctx.progress(None)` after). Other ctx helpers: `ctx.notify(text, kind)`,
`ctx.complete_text(prompt)` for a one-shot model answer, `ctx.usage`, `ctx.context_window`, `ctx.max_turns`,
`ctx.reasoning_effort`, `ctx.git()`, `ctx.keybindings()`, `ctx.fork()`/`ctx.truncate(i)`.

UI: `minimal.register_panel(name, render, area=settings["area"], order=0, title="HEADING", collapsible=True)`; render
returns lines, a line being a string, `(text, style)` or a list of those. Styles: `bold`, `muted`, `dim`, `success`,
`warning`, `error`, plus `$name` theme colours (`$accent`, `$code`) and `#rrggbb`. `register_widget(name, create,
area, order=, title=, collapsible=)` for Textual widgets. `minimal.register_css("name", "Selector { ... }")` restyles
the terminal UI with theme variables such as `$accent`.

Keys: `minimal.register_keybinding("ctrl+o", run, "description", name="x")` or `@minimal.keybinding("ctrl+o", ...)`;
`run(ctx)` may use `ctx.ui`. Make the key a setting so the user can change or drop it.

Metadata that helps users: `__depends__` / `__conflicts__` (other item ids), `__dependencies__` (pip requirements).

Check with ext_check (it also lints the rules above), then ext_bump, reload_extensions.
'''
"""One page of the conventions of API 2.3, returned by ``ext_api`` before the source."""

DEFAULTS = {"check_timeout": CHECK_TIMEOUT, "default_scope": "global", "lint": True, "prompt": PROMPT, "guide": True}

SCHEMA = {
    "check_timeout": {"description": "Seconds ext_check waits for `minimal ext check`.", "min": 1, "max": 1800},
    "default_scope": {"description": "Where ext_new writes when the model gives no scope.", "enum": ["global", "project"]},
    "lint": {"description": "Make ext_check also lint tags, api/feature mismatches and settings without a schema."},
    "prompt": {"description": "System-prompt note about the creator workflow (empty: none)."},
    "guide": {"description": "Put the API 2.3 conventions before the source in ext_api's answer."},
}


def _kind(kind):
    if kind not in CATEGORIES:
        raise ValueError(f"unknown kind {kind!r}; use one of: {', '.join(CATEGORIES)}")
    return kind


def _name(name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError(f"invalid name {name!r}: use lowercase letters, digits and _, not starting with _")
    return name


def _roots(cwd):
    """The two extensions folders: ``(scope, path)`` for the global one and the project's."""
    return [("global", Path.home() / ".minimal" / "extensions"), ("project", Path(cwd) / ".minimal" / "extensions")]


def _resolve(path, cwd):
    return Path(cwd, Path(path).expanduser())


def _entry_file(path):
    """The module holding an item's metadata: the file, or a package's ``__init__.py``."""
    return path / "__init__.py" if path.is_dir() else path


def _category_of(path):
    return path.parent.name if path.parent.name in SUBFOLDERS else "extensions"


def _description(entry):
    """First docstring line of ``entry``; ``""`` if unreadable or none."""
    try:
        doc = ast.get_docstring(ast.parse(entry.read_text(encoding="utf-8")))
    except (OSError, SyntaxError, ValueError):
        return ""
    return doc.strip().splitlines()[0] if doc and doc.strip() else ""


def _version(entry):
    """``__version__`` of ``entry``; ``"?"`` if unreadable or none."""
    try:
        tree = ast.parse(entry.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return "?"
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    return "?"


def _items(folder):
    """The items directly in ``folder``: ``(category, path)``, files and packages, without ``_`` or ``.`` names."""
    found = []
    for category, base in [("extensions", folder), *[(sub, folder / sub) for sub in SUBFOLDERS]]:
        if not base.is_dir():
            continue
        for path in sorted(base.iterdir()):
            if path.name.startswith(("_", ".")):
                continue
            if category == "extensions" and path.name in SUBFOLDERS:
                continue
            if (path.is_file() and path.suffix == ".py") or (path.is_dir() and (path / "__init__.py").is_file()):
                found.append((category, path))
    return found


def _api_tuple(text):
    """``"2.3"`` as ``(2, 3)``; ``None`` if it is not ``major[.minor]``."""
    parts = str(text).split(".")
    if len(parts) > 2 or not all(part.isdigit() for part in parts):
        return None
    return int(parts[0]), int(parts[1]) if len(parts) == 2 else 0


def _constants(tree, *names):
    """The values of the top-level assignments to ``names`` (``ast.literal_eval``; missing or unreadable ones left out)."""
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    try:
                        found[target.id] = ast.literal_eval(node.value)
                    except ValueError:
                        pass
    return found


def lint(source):
    """``(problems, notes)`` for an item's source: problems break a rule the marketplace enforces, notes are advice.

    Problems: ``__tags__`` that is not a list of marketplace tags, and an ``__api__`` lower than the API 2.3 features
    the code uses. Notes: ``declare_settings`` without a schema, panels and widgets without
    ``title``, tools that say neither ``read_only`` nor ``confirm``.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"syntax error at line {e.lineno}: {e.msg}"], []
    problems, notes = [], []
    meta = _constants(tree, "__api__", "__tags__")
    if "__tags__" in meta:
        tags = meta["__tags__"]
        bad = [tag for tag in tags if tag not in TAGS] if isinstance(tags, list) else None
        if bad is None or bad:
            problems.append(f"__tags__ must be a list of marketplace tags ({' '.join(TAGS)}); got {tags!r}")
    else:
        notes.append(f"add __tags__ = [...] with tags from: {' '.join(TAGS)}")
    used = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        keywords = {k.arg for k in node.keywords}
        if func == "declare_settings":
            if len(node.args) >= 2 or "schema" in keywords:
                used.append("declare_settings(schema)")
            else:
                notes.append("declare_settings has no schema: describe and bound each setting with SCHEMA")
        elif func in ("register_css", "register_keybinding", "keybinding", "complete_text", "progress"):
            used.append(func)
        elif func in ("register_tool", "tool"):
            if "read_only" in keywords:
                used.append("read_only")
            elif "confirm" not in keywords:
                notes.append("a tool says neither read_only=True (changes nothing, thread-safe) nor confirm: say which")
        elif func in ("register_panel", "register_widget"):
            ui = keywords & {"title", "collapsible", "order"}
            used += [f"{func}({name})" for name in sorted(ui)]
            if "title" not in keywords:
                notes.append(f"{func} has no title=: give panels a heading the user can collapse")
    api = _api_tuple(meta.get("__api__", ""))
    if used and api is not None and api < FEATURE_API:
        needed = ".".join(map(str, FEATURE_API))
        problems.append(
            f'__api__ is "{meta["__api__"]}" but the code uses API {needed} features ({", ".join(sorted(set(used)))}): '
            f'set __api__ = "{needed}"'
        )
    return problems, list(dict.fromkeys(notes))


def ext_new(input, ctx, settings=DEFAULTS):
    """Write a skeleton extension, tool, widget or theme into the extensions folder."""
    kind, name, scope = _kind(input.get("kind")), _name(input.get("name")), input.get("scope", settings["default_scope"])
    if scope not in ("global", "project"):
        raise ValueError("scope must be 'global' or 'project'")
    root = dict(_roots(ctx.cwd))[scope]
    category = CATEGORIES[kind]
    path = (root if category == "extensions" else root / category) / f"{name}.py"
    if path.exists():
        raise ValueError(f"{path} exists; edit it instead")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATES[kind].replace("__NAME__", name), encoding="utf-8")
    return f"Created {path}. Edit it, run ext_check, then reload_extensions."


def ext_template(input, ctx):
    """The skeleton of a kind, with ``__NAME__`` where the name goes; writes nothing."""
    return TEMPLATES[_kind(input.get("kind"))]


def ext_check(input, ctx, settings=DEFAULTS):
    """Run ``minimal ext check`` on a file or package folder, then :func:`lint` it; return the report."""
    path = _resolve(input["path"], ctx.cwd)
    if not path.exists():
        raise ValueError(f"{path} does not exist")
    timeout = settings["check_timeout"]
    try:
        result = subprocess.run(
            [sys.executable, "-m", "minimal", "ext", "check", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=ctx.cwd,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"ext check timed out after {timeout}s; raise the check_timeout setting if the item is slow to load"
        ) from None
    if result.returncode != 0:
        raise RuntimeError((result.stdout + result.stderr).strip() or f"ext check exited with {result.returncode}")
    report = result.stdout.strip()
    entry = _entry_file(path)
    if not settings["lint"] or not entry.is_file():
        return report
    problems, notes = lint(entry.read_text(encoding="utf-8"))
    lines = [f"LINT {problem}" for problem in problems] + [f"note {note}" for note in notes]
    if problems:
        raise RuntimeError("\n".join([report, *lines]))
    return "\n".join([report, *lines])


def ext_api(input, ctx, settings=DEFAULTS):
    """The conventions of API 2.3 and the source of ``minimal.api``, the authoritative extension API, headed by its version."""
    guide = GUIDE + "\n" if settings["guide"] else ""
    return f"# minimal extension API {API_VERSION}\n{guide}" + inspect.getsource(minimal.api)


def ext_list(input, ctx):
    """One line per extension, tool, widget and theme in the global and project extensions folders."""
    scope = input.get("scope", "all")
    if scope not in ("global", "project", "all"):
        raise ValueError("scope must be 'global', 'project' or 'all'")
    lines = []
    for where, root in _roots(ctx.cwd):
        if scope not in (where, "all"):
            continue
        for category, path in _items(root):
            name = path.stem if path.is_file() else path.name
            entry = _entry_file(path)
            lines.append(f"{where} {category}/{name} {_version(entry)} — {_description(entry)} {path}")
    return "\n".join(lines) or "No extensions found."


def ext_bump(input, ctx):
    """Raise the top-level ``__version__`` of an item (minor by default) and return ``old -> new``."""
    part = input.get("part", "minor")
    if part not in ("minor", "major"):
        raise ValueError("part must be 'minor' or 'major'")
    path = _resolve(input["path"], ctx.cwd)
    entry = _entry_file(path)
    if not entry.is_file():
        raise ValueError(f"{entry} does not exist")
    source = entry.read_text(encoding="utf-8")
    match = VERSION_RE.search(source)
    if match is None:
        raise ValueError('set __version__ = "1.0" first')
    major, minor = int(match.group(1)), int(match.group(2))
    old = f"{major}.{minor}"
    new = f"{major + 1}.0" if part == "major" else f"{major}.{minor + 1}"
    entry.write_text(source[: match.start()] + f'__version__ = "{new}"' + source[match.end() :], encoding="utf-8")
    return f"{old} -> {new}"


def ext_remove(input, ctx):
    """Delete an extension file or package folder from the global or project extensions folder."""
    path = _resolve(input["path"], ctx.cwd).resolve()
    if not path.name.startswith((".", "_")):
        for _, root in _roots(ctx.cwd):
            root = root.resolve()
            is_item = (path.parent == root and path.name not in SUBFOLDERS) or (
                path.parent.parent == root and path.parent.name in SUBFOLDERS
            )
            if is_item:
                if not path.exists():
                    raise ValueError(f"{path} does not exist")
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                return f"Removed {path}. Call reload_extensions."
    raise ValueError("only extensions under ~/.minimal/extensions or ./.minimal/extensions can be removed")


def ext_catalogue_row(input, ctx):
    """The marketplace README catalogue row for an item about to be published."""
    path = _resolve(input["path"], ctx.cwd)
    if not path.exists():
        raise ValueError(f"{path} does not exist")
    name = path.name if path.is_dir() else path.stem
    category = _category_of(path)
    description = _description(_entry_file(path))
    if not description:
        raise ValueError(f"{path}: add a module docstring; its first line is the description")
    ident = name if category == "extensions" else f"{category}/{name}"
    location = f"{category}/{name}/" if path.is_dir() else f"{category}/{name}.py"
    return f"| `{ident}` | `{location}` | {description} |"


def create(args, ctx):
    """/create <kind> <name> [description…]: ask the model to build one."""
    words = args.split(None, 2)
    if len(words) < 2:
        raise ValueError(f"usage: /create <{'|'.join(CATEGORIES)}> <name> [description…]")
    kind, name = _kind(words[0]), _name(words[1])
    description = words[2] if len(words) > 2 else "ask me what it should do"
    ctx.queue_user_message(f"Create a minimal {kind} named {name}: {description}. Follow the creator workflow.")


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    kinds = {"type": "string", "enum": list(CATEGORIES), "description": "What to create"}
    path = {"type": "string", "description": "A file or package folder, relative to the project or absolute"}
    minimal.register_tool(
        name="ext_new",
        run=lambda input, ctx: ext_new(input, ctx, settings),
        description="Create a skeleton extension, tool, widget or theme file in ~/.minimal/extensions (or the project's). "
        "Refuses to overwrite.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Lowercase letters, digits and _"},
                "kind": kinds,
                "scope": {"type": "string", "enum": ["global", "project"], "description": f"Default: {settings['default_scope']}"},
            },
            "required": ["name", "kind"],
        },
        confirm=True,
    )
    minimal.register_tool(
        name="ext_template",
        run=ext_template,
        read_only=True,
        description="Return the skeleton source of an extension, tool, widget or theme without writing anything.",
        input_schema={"type": "object", "properties": {"kind": kinds}, "required": ["kind"]},
    )
    minimal.register_tool(
        name="ext_check",
        run=lambda input, ctx: ext_check(input, ctx, settings),
        read_only=True,
        description="Validate an extension file or package folder (`minimal ext check`, then a lint of tags, __api__ and "
        "settings schemas); an error result lists the problems, `note` lines are advice.",
        input_schema={"type": "object", "properties": {"path": path}, "required": ["path"]},
    )
    minimal.register_tool(
        name="ext_api",
        run=lambda input, ctx: ext_api(input, ctx, settings),
        read_only=True,
        description="Return the conventions of the current API (settings, tools, panels, keys, CSS) and the source of "
        "minimal.api: the authoritative public API for extensions.",
        input_schema={"type": "object", "properties": {}},
    )
    minimal.register_tool(
        name="ext_list",
        run=ext_list,
        read_only=True,
        description="List the installed extensions, tools, widgets and themes: scope, id, version, description, path.",
        input_schema={
            "type": "object",
            "properties": {"scope": {"type": "string", "enum": ["global", "project", "all"], "description": "Default: all"}},
        },
    )
    minimal.register_tool(
        name="ext_bump",
        run=ext_bump,
        description="Raise an item's __version__ (minor by default). Do it on every change.",
        input_schema={
            "type": "object",
            "properties": {"path": path, "part": {"type": "string", "enum": ["minor", "major"]}},
            "required": ["path"],
        },
        confirm=True,
    )
    minimal.register_tool(
        name="ext_remove",
        run=ext_remove,
        description="Delete an extension file or package folder from ~/.minimal/extensions or ./.minimal/extensions.",
        input_schema={"type": "object", "properties": {"path": path}, "required": ["path"]},
        confirm=True,
    )
    minimal.register_tool(
        name="ext_catalogue_row",
        run=ext_catalogue_row,
        read_only=True,
        description="Return the marketplace README catalogue row for an item about to be published.",
        input_schema={"type": "object", "properties": {"path": path}, "required": ["path"]},
    )
    minimal.register_command("create", create, description="ask the model to create an extension, tool, widget or theme")
    if settings["prompt"]:
        minimal.append_system_prompt(settings["prompt"])
