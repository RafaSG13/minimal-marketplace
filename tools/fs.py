"""Filesystem tools for the model: tree, stat, read many files, find (read-only) and mkdir, move, copy, delete.

Prefer them over `bash ls/find/cat/mv/cp/rm`: bounded output, several reads run side by side, the read ones need no
permission prompt and a delete goes to a trash folder you can restore from instead of vanishing. Every path must stay
inside the working folder (symlinks that lead out are refused) unless ``allow_outside`` is set. Settings (``/ext
settings tools/fs``): ``max_chars`` (output cut), ``ignore`` (folder names ``fs_tree`` and ``fs_find`` skip outside a
git repository), ``max_files`` and ``max_chars_each`` (``fs_read_many``), ``trash`` (``fs_delete`` moves to
``<project data>/trash/<time>/`` instead of deleting) and ``allow_outside``.

Install it with `/ext`.
"""

import datetime
import fnmatch
import os
import shutil
import stat as statmod
import subprocess
import time

__version__ = "1.0"
__api__ = "2.4"
__tags__ = ["files"]

DEFAULTS = {
    "max_chars": 30000,
    "ignore": [".git", "node_modules", "__pycache__", ".venv", "dist", "build"],
    "max_files": 20,
    "max_chars_each": 20000,
    "trash": True,
    "allow_outside": False,
}

SCHEMA = {
    "max_chars": {"description": "Longest output of one call in characters; the rest is cut.", "min": 1000, "max": 1_000_000},
    "ignore": {"description": "Folder names fs_tree and fs_find skip when the folder is not a git repository."},
    "max_files": {"description": "Most files one fs_read_many call may read.", "min": 1, "max": 200},
    "max_chars_each": {"description": "Longest text fs_read_many returns per file.", "min": 100, "max": 1_000_000},
    "trash": {"description": "fs_delete moves to the project's trash folder instead of deleting for good."},
    "allow_outside": {"description": "Let the tools touch paths outside the working folder."},
}


def _clip(text, limit, how):
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n[clipped {len(text) - limit} chars; {how}]"


def _int(input, key, default, low, high):
    value = input.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return max(low, min(high, value))


def _list(value, field):
    if not isinstance(value, list) or not value or not all(isinstance(p, str) and p for p in value):
        raise ValueError(f"{field} must be a non-empty list of paths")
    return value


def _order(entry):
    """Sort key of a ``(parts, is_dir)`` entry: at every level folders come before files, then by name."""
    parts, is_dir = entry
    return [(not (is_dir or i < len(parts) - 1), name) for i, name in enumerate(parts)]


def _iso(timestamp):
    return datetime.datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)

    def resolve(ctx, path):
        """``(joined path, real path)`` of ``path``; ``ValueError`` when it leads outside the working folder."""
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        joined = os.path.join(ctx.cwd, path)
        real = os.path.realpath(joined)
        root = os.path.realpath(ctx.cwd)
        if not settings["allow_outside"] and real != root and not real.startswith(root + os.sep):
            raise ValueError(
                f"{path} is outside the working folder; use a path inside {root} "
                "(symlinks that lead out count) or set the allow_outside setting"
            )
        return joined, real

    def protected(ctx, real):
        """Why ``real`` may not be changed (the working folder itself, anything of ``.git``), or ``None``."""
        root = os.path.realpath(ctx.cwd)
        if real == root:
            return "the working folder itself"
        rel = os.path.relpath(real, root)
        if ".git" in rel.split(os.sep):
            return "the .git folder"
        return None

    def walk(base, depth, ignore, dirs_only=False):
        """``(relative parts, is_dir)`` of the entries under ``base`` up to ``depth`` levels, sorted dirs first."""
        found = []

        def go(folder, parts):
            try:
                names = sorted(os.listdir(folder))
            except OSError:
                return
            dirs = [n for n in names if os.path.isdir(os.path.join(folder, n)) and not os.path.islink(os.path.join(folder, n))]
            files = [n for n in names if n not in dirs]
            for n in dirs:
                if n in ignore:
                    continue
                found.append((parts + (n,), True))
                if len(parts) + 1 < depth:
                    go(os.path.join(folder, n), parts + (n,))
            if not dirs_only:
                found.extend((parts + (n,), False) for n in files)

        go(base, ())
        return found

    def listed_by_git(ctx, rel):
        try:
            result = subprocess.run(
                ["git", "ls-files", "-co", "--exclude-standard", "-z", "--", rel],
                cwd=ctx.cwd,
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return [p for p in result.stdout.decode("utf-8", errors="replace").split("\0") if p]

    def tree(input, ctx):
        base_input = input.get("path") or "."
        joined, real = resolve(ctx, base_input)
        if not os.path.isdir(real):
            raise ValueError(f"{base_input} is not a folder; pass a folder or use fs_stat")
        depth = _int(input, "depth", 3, 1, 10)
        limit = _int(input, "max_entries", 500, 1, 100_000)
        dirs_only = bool(input.get("dirs_only"))
        rel = os.path.relpath(real, os.path.realpath(ctx.cwd))
        files = listed_by_git(ctx, rel) if not rel.startswith("..") else None
        if files is not None:
            seen = set()
            for f in files:
                parts = tuple(f.split("/"))
                if rel != ".":
                    parts = parts[len(rel.split(os.sep)) :]
                for i in range(1, min(len(parts), depth) + 1):
                    seen.add((parts[:i], i < len(parts)))
            entries = sorted(seen, key=_order)
            entries = [e for e in entries if e[1] or not dirs_only]
        else:
            entries = walk(real, depth, set(settings["ignore"]), dirs_only)
            entries.sort(key=_order)
        lines = [f"{base_input}/" if base_input != "." else "./"]
        for parts, is_dir in entries[:limit]:
            lines.append("  " * len(parts) + parts[-1] + ("/" if is_dir else ""))
        if len(entries) > limit:
            lines.append(f"[{len(entries) - limit} more entries; narrow path or depth]")
        elif not entries:
            lines.append("  (empty)")
        return _clip("\n".join(lines), settings["max_chars"], "narrow path or depth")

    def stat(input, ctx):
        lines = []
        for p in _list(input.get("paths"), "paths"):
            joined, _ = resolve(ctx, p)
            try:
                st = os.lstat(joined)
            except FileNotFoundError:
                lines.append(f"{p}  missing")
                continue
            mode = st.st_mode
            kind = "symlink" if statmod.S_ISLNK(mode) else "dir" if statmod.S_ISDIR(mode) else "file" if statmod.S_ISREG(mode) else "other"
            line = f"{p}  {kind}  {st.st_size} bytes  {_iso(st.st_mtime)}  {oct(statmod.S_IMODE(mode))[2:]}"
            if kind == "symlink":
                line += f"  -> {os.readlink(joined)}"
            lines.append(line)
        return "\n".join(lines)

    def read_many(input, ctx):
        paths = _list(input.get("paths"), "paths")
        if len(paths) > settings["max_files"]:
            raise ValueError(f"{len(paths)} paths is too many; read at most {settings['max_files']} files per call")
        each = settings["max_chars_each"]
        blocks = []
        for p in paths:
            _, real = resolve(ctx, p)
            head = f"==> {p} <=="
            if not os.path.exists(real):
                blocks.append(f"{head}\n[missing]")
            elif os.path.isdir(real):
                blocks.append(f"{head}\n[directory; use fs_tree]")
            else:
                size = os.path.getsize(real)
                with open(real, "rb") as f:
                    raw = f.read(each * 4 + 4)
                if b"\0" in raw[:8000]:
                    blocks.append(f"{head}\n[binary, {size} bytes]")
                    continue
                text = raw.decode("utf-8", errors="replace")
                if len(text) > each or size > len(raw):
                    text = text[:each] + f"\n[clipped; {size} bytes in the file; read it alone with the read tool for the rest]"
                blocks.append(f"{head}\n{text}")
        return _clip("\n\n".join(blocks), settings["max_chars"], "pass fewer paths")

    def find(input, ctx):
        base_input = input.get("path") or "."
        _, real = resolve(ctx, base_input)
        if not os.path.isdir(real):
            raise ValueError(f"{base_input} is not a folder")
        pattern, kind = input.get("name"), input.get("type")
        if kind not in (None, "f", "d"):
            raise ValueError('type must be "f" (files) or "d" (folders)')
        limit = _int(input, "limit", 200, 1, 10_000)
        lo, hi = input.get("min_size"), input.get("max_size")
        days = input.get("modified_within_days")
        cutoff = None if days is None else time.time() - float(days) * 86400
        ignore = set(settings["ignore"])
        matches, more = [], False
        for folder, dirs, files in os.walk(real):
            dirs[:] = sorted(d for d in dirs if d not in ignore)
            candidates = [(d, True) for d in dirs] + [(f, False) for f in sorted(files)]
            for name, is_dir in candidates:
                if kind == "f" and is_dir or kind == "d" and not is_dir:
                    continue
                if pattern and not fnmatch.fnmatch(name, pattern):
                    continue
                full = os.path.join(folder, name)
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                if (lo is not None and st.st_size < lo) or (hi is not None and st.st_size > hi):
                    continue
                if cutoff is not None and st.st_mtime < cutoff:
                    continue
                if len(matches) >= limit:
                    more = True
                    break
                matches.append(os.path.relpath(full, ctx.cwd) + ("/" if is_dir else ""))
            if more:
                break
        if not matches:
            return "(no matches)"
        out = "\n".join(matches)
        if more:
            out += f"\n[more matches; narrow path or name, or raise limit above {limit}]"
        return _clip(out, settings["max_chars"], "narrow path or name")

    def mkdir(input, ctx):
        _, real = resolve(ctx, input.get("path"))
        if ".git" in os.path.relpath(real, os.path.realpath(ctx.cwd)).split(os.sep):
            raise ValueError("refusing to create anything inside the .git folder")
        if os.path.isfile(real):
            raise ValueError(f"{input['path']} exists and is a file")
        os.makedirs(real, exist_ok=True)
        return f"created {input['path']}"

    def guard_target(ctx, real, role):
        why = protected(ctx, real)
        if why:
            raise ValueError(f"refusing to change {why} ({role})")

    def prepare(input, ctx, verb):
        src_in, dest_in = input.get("src"), input.get("dest")
        _, src = resolve(ctx, src_in)
        _, dest = resolve(ctx, dest_in)
        guard_target(ctx, src, "source")
        guard_target(ctx, dest, "destination")
        if not os.path.lexists(os.path.join(ctx.cwd, src_in)):
            raise ValueError(f"{src_in} does not exist; check the path with fs_stat or fs_find")
        if os.path.lexists(dest):
            if not input.get("overwrite"):
                raise ValueError(f"{dest_in} already exists; pass overwrite=true to replace it")
            if os.path.isdir(dest) and not os.path.islink(dest) and verb == "move":
                raise ValueError(f"{dest_in} is a folder; overwrite only replaces files: move into it or delete it first")
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        return os.path.join(ctx.cwd, src_in), dest

    def move(input, ctx):
        src, dest = prepare(input, ctx, "move")
        if os.path.lexists(dest):
            os.remove(dest)
        shutil.move(src, dest)
        return f"moved {input['src']} -> {input['dest']}"

    def copy(input, ctx):
        src, dest = prepare(input, ctx, "copy")
        if os.path.isdir(src) and not os.path.islink(src):
            shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=bool(input.get("overwrite")))
        else:
            shutil.copy2(src, dest, follow_symlinks=False)
        return f"copied {input['src']} -> {input['dest']}"

    def delete(input, ctx):
        path = input.get("path")
        joined, real = resolve(ctx, path)
        guard_target(ctx, real, "target")
        if not os.path.lexists(joined):
            raise ValueError(f"{path} does not exist; check the path with fs_stat or fs_find")
        if input.get("permanent") or not settings["trash"]:
            if os.path.isdir(joined) and not os.path.islink(joined):
                shutil.rmtree(joined)
            else:
                os.remove(joined)
            return f"deleted {path} for good"
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        root = os.path.realpath(ctx.cwd)
        rel = os.path.relpath(real, root)
        if rel.startswith(".."):
            rel = os.path.basename(real)
        target = os.path.join(str(minimal.data_dir("project")), "trash", stamp, rel)
        n = 1
        while os.path.lexists(target):
            target = os.path.join(str(minimal.data_dir("project")), "trash", f"{stamp}-{n}", rel)
            n += 1
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.move(joined, target)
        return f"moved {path} to the trash: {target} (restore it with fs_move)"

    S = {"type": "string"}
    PATHS = {"type": "array", "items": S, "description": "Paths relative to the working folder"}
    PREFER = " Prefer it over `bash`: bounded output, no permission prompt, runs in parallel with other reads."

    def read_tool(name, run, description, properties, required=()):
        minimal.register_tool(
            name,
            run,
            description + PREFER,
            {"type": "object", "properties": properties, "required": list(required)},
            read_only=True,
        )

    def write_tool(name, run, description, properties, required, subject_key):
        minimal.register_tool(
            name,
            run,
            description,
            {"type": "object", "properties": properties, "required": list(required)},
            confirm=True,
            subject_key=subject_key,
        )

    read_tool(
        "fs_tree",
        tree,
        "Indented tree of a folder; in a git repository it lists tracked and untracked files minus ignored ones.",
        {
            "path": {**S, "description": "Folder (default: the working folder)"},
            "depth": {"type": "integer", "description": "Levels, 1-10 (default 3)"},
            "max_entries": {"type": "integer", "description": "Most entries (default 500)"},
            "dirs_only": {"type": "boolean"},
        },
    )
    read_tool("fs_stat", stat, "Type, size, modified time and mode of paths; `missing` when absent.", {"paths": PATHS}, ["paths"])
    read_tool(
        "fs_read_many",
        read_many,
        "Read several text files at once, each under a `==> path <==` header; binary files are only sized.",
        {"paths": PATHS},
        ["paths"],
    )
    read_tool(
        "fs_find",
        find,
        "Find files or folders by name glob, type, size or recent change.",
        {
            "path": S,
            "name": {**S, "description": "Glob on the file name, e.g. *.py"},
            "type": {**S, "enum": ["f", "d"]},
            "min_size": {"type": "integer", "description": "Bytes"},
            "max_size": {"type": "integer", "description": "Bytes"},
            "modified_within_days": {"type": "number"},
            "limit": {"type": "integer", "description": "Most results (default 200)"},
        },
    )
    write_tool("fs_mkdir", mkdir, "Create a folder (and its parents).", {"path": S}, ["path"], "path")
    write_tool(
        "fs_move",
        move,
        "Move or rename a file or folder; creates parent folders; refuses an existing destination unless overwrite=true.",
        {"src": S, "dest": S, "overwrite": {"type": "boolean"}},
        ["src", "dest"],
        "src",
    )
    write_tool(
        "fs_copy",
        copy,
        "Copy a file or folder; creates parent folders; refuses an existing destination unless overwrite=true.",
        {"src": S, "dest": S, "overwrite": {"type": "boolean"}},
        ["src", "dest"],
        "src",
    )
    write_tool(
        "fs_delete",
        delete,
        "Delete a file or folder: it moves to the project's trash folder (restore it with fs_move) unless permanent=true. "
        "Refuses the working folder and anything under .git.",
        {"path": S, "permanent": {"type": "boolean", "description": "Delete for good instead of using the trash"}},
        ["path"],
        "path",
    )
