"""Creator: lets the model write, check, version, list, remove and catalogue extensions, tools, widgets and themes (/create)."""

import ast
import inspect
import re
import shutil
import subprocess
import sys
from pathlib import Path

import minimal.api
from minimal.api import API_VERSION

__version__ = "1.0"
__api__ = "2"
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
__api__ = "2"


def register(minimal):
    turns = 0

    @minimal.on("turn_end")
    def count(event):
        nonlocal turns
        turns += 1

    def show(args, ctx):
        print(f"__NAME__: {turns} turns finished since the last reload")

    minimal.register_command("__NAME__", show, description="show how many turns finished")
'''

TOOL_TEMPLATE = '''"""__NAME__ tool: one line saying what the model gets from it."""

__version__ = "1.0"
__api__ = "2"


def run(input, ctx):
    text = str(input.get("text", "")).strip()
    if not text:
        raise ValueError("__NAME__ needs a non-empty text")
    return text.upper()


def register(minimal):
    minimal.register_tool(
        name="__NAME__",
        run=run,
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

__version__ = "1.0"
__api__ = "2"


def render(ctx):
    return f"{Path(ctx.cwd).name}\\n{ctx.provider_name} · {ctx.model}"


def register(minimal):
    minimal.register_panel("__NAME__", render, area="sidebar")
'''

THEME_TEMPLATE = '''"""__NAME__: a dark theme; only background, foreground and accent are required."""

__version__ = "1.0"
__api__ = "2"


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
    "and ext_publish if asked. Read ext_api for the API; keep state in minimal.data_dir(). ext_remove deletes an "
    "extension you created."
)


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


def ext_new(input, ctx):
    """Write a skeleton extension, tool, widget or theme into the extensions folder."""
    kind, name, scope = _kind(input.get("kind")), _name(input.get("name")), input.get("scope", "global")
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


def ext_check(input, ctx):
    """Run ``minimal ext check`` on a file or package folder and return its report."""
    path = _resolve(input["path"], ctx.cwd)
    if not path.exists():
        raise ValueError(f"{path} does not exist")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "minimal", "ext", "check", str(path)],
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT,
            cwd=ctx.cwd,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ext check timed out after {CHECK_TIMEOUT}s") from None
    if result.returncode != 0:
        raise RuntimeError((result.stdout + result.stderr).strip() or f"ext check exited with {result.returncode}")
    return result.stdout.strip()


def ext_api(input, ctx):
    """The source of ``minimal.api``, the authoritative extension API, headed by its version."""
    return f"# minimal extension API {API_VERSION}\n" + inspect.getsource(minimal.api)


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
    kinds = {"type": "string", "enum": list(CATEGORIES), "description": "What to create"}
    path = {"type": "string", "description": "A file or package folder, relative to the project or absolute"}
    minimal.register_tool(
        name="ext_new",
        run=ext_new,
        description="Create a skeleton extension, tool, widget or theme file in ~/.minimal/extensions (or the project's). "
        "Refuses to overwrite.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Lowercase letters, digits and _"},
                "kind": kinds,
                "scope": {"type": "string", "enum": ["global", "project"], "description": "Default: global"},
            },
            "required": ["name", "kind"],
        },
        confirm=True,
    )
    minimal.register_tool(
        name="ext_template",
        run=ext_template,
        description="Return the skeleton source of an extension, tool, widget or theme without writing anything.",
        input_schema={"type": "object", "properties": {"kind": kinds}, "required": ["kind"]},
    )
    minimal.register_tool(
        name="ext_check",
        run=ext_check,
        description="Validate an extension file or package folder (`minimal ext check`); an error result lists the problems.",
        input_schema={"type": "object", "properties": {"path": path}, "required": ["path"]},
    )
    minimal.register_tool(
        name="ext_api",
        run=ext_api,
        description="Return the source of minimal.api: the authoritative public API for extensions.",
        input_schema={"type": "object", "properties": {}},
    )
    minimal.register_tool(
        name="ext_list",
        run=ext_list,
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
        description="Return the marketplace README catalogue row for an item about to be published.",
        input_schema={"type": "object", "properties": {"path": path}, "required": ["path"]},
    )
    minimal.register_command("create", create, description="ask the model to create an extension, tool, widget or theme")
    minimal.append_system_prompt(PROMPT)
