"""A compact map of a codebase for the model: every source file with its classes and functions and their line numbers.

`repo_map(path?, focus?)` answers "what is in this repository and where" in one call instead of many ``glob`` and
``grep`` calls. No external dependency: Python is read with ``ast`` (classes, functions and methods with their
parameter names); JavaScript, TypeScript, Go, Rust, Java and Ruby by one regular expression per language for
top-level declarations. Files come from ``git ls-files`` (tracked and untracked, minus ignored) or, outside a
repository, a walk that skips the ``ignore`` folders. ``focus`` paths or globs are listed first; the map is cut at
``max_chars`` with a note saying how to narrow it. Settings (``/ext settings tools/repo_map``): ``max_chars``,
``ignore``, ``max_file_bytes`` (larger files are listed without symbols) and ``max_files``.

Install it with ``/ext``.
"""

import ast
import fnmatch
import os
import re
import subprocess

__version__ = "1.0"
__api__ = "2.4"
__tags__ = ["search", "context"]

DEFAULTS = {
    "max_chars": 8000,
    "ignore": [".git", "node_modules", "__pycache__", ".venv", "dist", "build"],
    "max_file_bytes": 500_000,
    "max_files": 5000,
}

SCHEMA = {
    "max_chars": {"description": "Longest map in characters; the rest is summarised as a count.", "min": 500, "max": 1_000_000},
    "ignore": {"description": "Folder names skipped when the folder is not a git repository."},
    "max_file_bytes": {"description": "Files larger than this are listed without their symbols.", "min": 1000, "max": 50_000_000},
    "max_files": {"description": "Most files read for symbols in one call.", "min": 10, "max": 100_000},
}

PATTERNS = {
    ".js": r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?P<kind>class|function\*?|interface|enum|type)\s+(?P<name>\w+)",
    ".go": r"^(?:func\s+(?:\(\s*\w+\s+\*?(?P<recv>\w+)\s*\)\s*)?(?P<name>\w+)(?P<kind>)|type\s+(?P<tname>\w+)\s+(?P<tkind>struct|interface))",
    ".rs": r"^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?(?P<kind>fn|struct|enum|trait|impl)\s*(?:<[^>]*>\s*)?(?P<name>\w+)",
    ".java": r"^(?:(?:public|private|protected|static|final|abstract)\s+)*(?P<kind>class|interface|enum|record)\s+(?P<name>\w+)",
    ".rb": r"^(?P<indent>\s*)(?P<kind>class|module|def)\s+(?P<name>[\w:.?!]+)",
}
ALIASES = {".ts": ".js", ".tsx": ".js", ".jsx": ".js", ".mjs": ".js", ".cjs": ".js"}
SOURCE = {".py", *PATTERNS, *ALIASES}
"""Extensions the map reads symbols from."""


def python_symbols(text):
    """``[(depth, line, kind, text)]`` for the classes, functions and methods of Python source."""
    tree = ast.parse(text)
    found = []

    def args_of(node):
        a = node.args
        names = [x.arg for x in [*a.posonlyargs, *a.args] if x.arg not in ("self", "cls")]
        if a.vararg:
            names.append("*" + a.vararg.arg)
        names += [x.arg for x in a.kwonlyargs]
        if a.kwarg:
            names.append("**" + a.kwarg.arg)
        return ", ".join(names)

    def walk(body, depth):
        for node in body:
            if isinstance(node, ast.ClassDef):
                bases = ", ".join(ast.unparse(b) for b in node.bases)
                found.append((depth, node.lineno, "class", f"{node.name}({bases})" if bases else node.name))
                walk(node.body, depth + 1)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                found.append((depth, node.lineno, kind, f"{node.name}({args_of(node)})"))

    walk(tree.body, 0)
    return found


def regex_symbols(suffix, text):
    """``[(depth, line, kind, name)]`` from the declarations the language's regular expression finds."""
    pattern = re.compile(PATTERNS[ALIASES.get(suffix, suffix)], re.M)
    found = []
    for m in pattern.finditer(text):
        groups = m.groupdict()
        line = text.count("\n", 0, m.start()) + 1
        if suffix == ".go":
            if groups.get("tname"):
                found.append((0, line, groups["tkind"], groups["tname"]))
            else:
                name = f"{groups['recv']}.{groups['name']}" if groups.get("recv") else groups["name"]
                found.append((1 if groups.get("recv") else 0, line, "func", name))
        elif suffix == ".rb":
            found.append((len(groups["indent"]) // 2, line, groups["kind"], groups["name"]))
        else:
            kind = groups["kind"].rstrip("*")
            found.append((0, line, kind, groups["name"]))
    return found


def symbols_of(path, suffix):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if suffix == ".py":
        return python_symbols(text)
    return regex_symbols(suffix, text)


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)

    def listed(base, cwd):
        """Relative file paths (to ``cwd``) under ``base``: git's list when it is a repository, else a walk."""
        rel = os.path.relpath(base, cwd)
        try:
            result = subprocess.run(
                ["git", "ls-files", "-co", "--exclude-standard", "-z", "--", rel],
                cwd=cwd,
                capture_output=True,
                timeout=20,
            )
            if result.returncode == 0:
                return sorted(p for p in result.stdout.decode("utf-8", errors="replace").split("\0") if p and os.path.isfile(os.path.join(cwd, p)))
        except (OSError, subprocess.TimeoutExpired):
            pass
        ignore = set(settings["ignore"])
        found = []
        for folder, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in ignore)
            found += [os.path.relpath(os.path.join(folder, f), cwd) for f in files]
        return sorted(found)

    def repo_map(input, ctx):
        root = os.path.realpath(ctx.cwd)
        base_input = input.get("path") or "."
        base = os.path.realpath(os.path.join(ctx.cwd, base_input))
        if base != root and not base.startswith(root + os.sep):
            raise ValueError(f"{base_input} is outside the working folder; pass a folder inside {root}")
        if not os.path.isdir(base):
            raise ValueError(f"{base_input} is not a folder; pass a folder or use the read tool for one file")
        focus = input.get("focus") or []
        if not isinstance(focus, list) or not all(isinstance(f, str) and f for f in focus):
            raise ValueError("focus must be a list of paths or globs")
        limit = settings["max_chars"]
        if input.get("max_chars") is not None:
            if isinstance(input["max_chars"], bool) or not isinstance(input["max_chars"], int):
                raise ValueError("max_chars must be an integer")
            limit = max(500, min(settings["max_chars"], input["max_chars"]))

        files = listed(base, ctx.cwd)
        source = [f for f in files if os.path.splitext(f)[1].lower() in SOURCE]
        others = len(files) - len(source)

        def focused(path):
            return any(fnmatch.fnmatch(path, g) or path == g.rstrip("/") or path.startswith(g.rstrip("/") + "/") for g in focus)

        ordered = [f for f in source if focused(f)] + [f for f in source if not focused(f)]
        blocks = []
        for index, path in enumerate(ordered):
            full = os.path.join(ctx.cwd, path)
            lines = [f"{path}:"]
            if index < settings["max_files"]:
                try:
                    if os.path.getsize(full) <= settings["max_file_bytes"]:
                        for depth, line, kind, text in symbols_of(full, os.path.splitext(path)[1].lower()):
                            lines.append(f"{'  ' * (depth + 1)}L{line} {kind} {text}")
                except (OSError, SyntaxError, ValueError):
                    pass
            blocks.append("\n".join(lines))
        out, used = [], 0
        for i, block in enumerate(blocks):
            if used + len(block) + 1 > limit and out:
                out.append(f"[{len(blocks) - i} more files; pass path= or focus= to narrow the map]")
                break
            out.append(block)
            used += len(block) + 1
        if not out:
            return "(no source files found; repo_map reads Python, JavaScript, TypeScript, Go, Rust, Java and Ruby)"
        if others and not out[-1].startswith("["):
            out.append(f"(+{others} other files without symbols)")
        return "\n".join(out)

    minimal.register_tool(
        "repo_map",
        repo_map,
        "A map of the codebase: each source file with its classes, functions and methods and their line numbers. Use it to "
        "orient yourself in an unfamiliar repository before reading files; prefer it over many glob and grep calls. Pass focus "
        "(paths or globs) to list the files you care about first.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Folder to map (default: the working folder)"},
                "focus": {"type": "array", "items": {"type": "string"}, "description": "Paths or globs to list first"},
                "max_chars": {"type": "integer", "description": "Cut the map to this many characters"},
            },
        },
        read_only=True,
    )
