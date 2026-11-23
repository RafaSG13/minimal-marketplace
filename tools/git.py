"""Git tools for the model: status, diff, log, show, blame, branch (read-only) and add, commit, switch (they ask first).

Each tool runs one ``git`` command in the working folder and returns compact text, so prefer them over ``bash git ...``:
the output is bounded, several read calls run side by side and the read ones need no permission prompt. Nothing here can
rewrite history (no amend, rebase, reset, force push) or skip hooks (no ``--no-verify``). Settings (``/ext settings
tools/git``): ``max_chars`` (output cut, with a note how to narrow the call), ``timeout`` (seconds per command),
``log_max`` (most commits ``git_log`` returns), ``mutations`` (false removes ``git_add``, ``git_commit`` and
``git_switch``) and ``commit_trailer`` (a paragraph added to every commit message, e.g. a ``Co-authored-by:`` line).

Install it with ``/ext``.
"""

import os
import shutil
import signal
import subprocess
import threading
import time

__version__ = "1.0"
__api__ = "2.4"
__tags__ = ["git"]

DEFAULTS = {
    "max_chars": 30000,
    "timeout": 30,
    "log_max": 200,
    "mutations": True,
    "commit_trailer": "",
}

SCHEMA = {
    "max_chars": {"description": "Longest output of one call in characters; the rest is cut.", "min": 1000, "max": 1_000_000},
    "timeout": {"description": "Seconds one git command may run before it is killed.", "min": 1, "max": 600},
    "log_max": {"description": "Most commits git_log may return.", "min": 1, "max": 5000},
    "mutations": {"description": "Register git_add, git_commit and git_switch; false leaves only the read-only tools."},
    "commit_trailer": {"description": "Paragraph added to every commit message git_commit makes (empty: none)."},
}

SECRET_ENV = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BRAVE_API_KEY")
"""Variables a child process never inherits."""
CAPTURE = 1_000_000
"""Bytes kept of each stream of a command; the rest is read and dropped."""


def _env():
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    env.update(GIT_TERMINAL_PROMPT="0", PAGER="cat", GIT_PAGER="cat", NO_COLOR="1")
    return env


def _drain(pipe, chunks):
    kept = 0
    for chunk in iter(lambda: pipe.read(65536), b""):
        if kept < CAPTURE:
            chunks.append(chunk[: CAPTURE - kept])
            kept += len(chunk)


def _run(argv, cwd, timeout, ctx, env=None, stdin=None):
    """Run ``argv`` in ``cwd``; return ``(exit code, stdout, stderr)``.

    The command gets its own process group: a timeout or the user's interrupt kills all of it. Raises ``RuntimeError``
    for either (``<program> timed out after Ns`` / ``interrupted``).
    """
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=_env() if env is None else env,
        stdin=subprocess.DEVNULL if stdin is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    out, err = [], []
    readers = [
        threading.Thread(target=_drain, args=(proc.stdout, out), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, err), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        if stdin is not None:
            try:
                proc.stdin.write(stdin.encode("utf-8"))
                proc.stdin.close()
            except OSError:
                pass
        deadline = time.monotonic() + timeout
        while True:
            try:
                proc.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                pass
            failure = None
            if ctx.cancelled:
                failure = "interrupted"
            elif time.monotonic() >= deadline:
                failure = f"{os.path.basename(argv[0])} timed out after {timeout}s"
            if failure:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                proc.wait()
                raise RuntimeError(failure)
    finally:
        for reader in readers:
            reader.join(2)
        proc.stdout.close()
        proc.stderr.close()
    return proc.returncode, _decode(out), _decode(err)


def _decode(chunks):
    return b"".join(chunks).decode("utf-8", errors="replace").replace("\r\n", "\n")


def _clip(text, limit, how):
    """``text`` cut to ``limit`` characters, ending with how to narrow the call."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n[clipped {len(text) - limit} chars; {how}]"


def _plain(field, value):
    """``value`` as text that cannot be read as a git option."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if value.startswith("-"):
        raise ValueError(f"{field} must not start with '-'")
    return value


def _paths(value, field="paths"):
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(p, str) and p for p in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return value


def _int(input, key, default, low, high):
    value = input.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return max(low, min(high, value))


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)

    def git(sub, args, ctx, *, how, mutating=False, empty="(no output)"):
        """Run ``git <sub> <args>`` in ``ctx.cwd``; the output clipped, ``empty`` when there is none."""
        exe = shutil.which("git")
        if exe is None:
            raise ValueError("git is not installed or not on PATH; install it with brew install git")
        prefix = [exe, "--no-pager", "-c", "color.ui=never", "-c", "core.quotepath=false"]
        if not mutating:
            prefix.append("--no-optional-locks")
        code, out, err = _run([*prefix, sub, *args], ctx.cwd, settings["timeout"], ctx)
        if code != 0:
            if "not a git repository" in err.lower():
                raise ValueError(f"not a git repository: {ctx.cwd}; run git from the project folder or git init")
            raise RuntimeError(f"git {sub} failed (exit {code}): {(err.strip() or out.strip())[:500]}")
        if mutating:
            ctx.git_refresh()
        return _clip(out, settings["max_chars"], how) if out.strip() else empty

    def status(input, ctx):
        args = ["--short", "--branch", "--untracked-files=normal"]
        if input.get("path"):
            args += ["--", input["path"]]
        return git("status", args, ctx, how="pass path to look at one folder")

    def diff(input, ctx):
        args = ["--no-ext-diff", f"-U{_int(input, 'context', 3, 0, 20)}"]
        if input.get("staged"):
            args.append("--cached")
        if input.get("stat"):
            args.append("--stat")
        if input.get("ref"):
            args.append(_plain("ref", input["ref"]))
        paths = _paths(input.get("paths"))
        if paths:
            args += ["--", *paths]
        return git("diff", args, ctx, how="pass paths, stat=true or a narrower ref", empty="(no differences)")

    def log(input, ctx):
        n = _int(input, "n", 20, 1, settings["log_max"])
        args = ["-n", str(n), "--date=short", "--format=%h %ad %an %s"]
        if input.get("author"):
            args.append(f"--author={_plain('author', input['author'])}")
        if input.get("since"):
            args.append(f"--since={_plain('since', input['since'])}")
        if input.get("grep"):
            args.append(f"--grep={input['grep']}")
        if input.get("ref"):
            args.append(_plain("ref", input["ref"]))
        if input.get("path"):
            args += ["--", input["path"]]
        return git("log", args, ctx, how="lower n or pass path, author or since", empty="(no commits)")

    def show(input, ctx):
        args = ["--no-ext-diff"]
        if input.get("stat"):
            args.append("--stat")
        args.append(_plain("rev", input.get("rev")))
        if input.get("path"):
            args += ["--", input["path"]]
        return git("show", args, ctx, how="pass stat=true or path")

    def blame(input, ctx):
        path = input.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("path is required")
        args = ["-w", "--date=short"]
        start, end = input.get("start"), input.get("end")
        if start is not None or end is not None:
            first = _int(input, "start", 1, 1, 10**9)
            args += ["-L", f"{first},{_int(input, 'end', first, first, 10**9)}" if end is not None else f"{first},"]
        return git("blame", [*args, "--", path], ctx, how="pass start and end to blame a line range")

    def branch(input, ctx):
        return git("branch", ["-vv", "--all"], ctx, how="there are many branches", empty="(no branches)")

    def add(input, ctx):
        paths = _paths(input.get("paths"))
        if not paths:
            raise ValueError('paths is required: a list of files or folders to stage ("." for everything)')
        git("add", ["--", *paths], ctx, how="", mutating=True)
        return git("status", ["--short", "--branch"], ctx, how="", mutating=True)

    def commit(input, ctx):
        message = input.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message is required: say what the commit changes")
        paths = _paths(input.get("paths"))
        if paths:
            git("add", ["--", *paths], ctx, how="", mutating=True)
        args = ["-m", message]
        if input.get("all"):
            args.insert(0, "-a")
        if settings["commit_trailer"].strip():
            args += ["-m", settings["commit_trailer"]]
        git("commit", args, ctx, how="", mutating=True)
        return git("log", ["-1", "--stat"], ctx, how="", mutating=True)

    def switch(input, ctx):
        args = ["-c"] if input.get("create") else []
        args.append(_plain("branch", input.get("branch")))
        git("switch", args, ctx, how="", mutating=True)
        return git("status", ["--short", "--branch"], ctx, how="", mutating=True)

    S = {"type": "string"}
    PATH_LIST = {"type": "array", "items": S, "description": "Files or folders, relative to the working folder"}
    PREFER = " Prefer it over `bash git ...`: smaller output, runs in parallel and needs no permission prompt."

    def read_tool(name, run, description, properties, required=()):
        minimal.register_tool(
            name,
            run,
            description + PREFER,
            {"type": "object", "properties": properties, "required": list(required)},
            read_only=True,
        )

    def write_tool(name, run, description, properties, required=(), subject_key=None):
        minimal.register_tool(
            name,
            run,
            description,
            {"type": "object", "properties": properties, "required": list(required)},
            confirm=True,
            subject_key=subject_key,
        )

    read_tool("git_status", status, "Short git status with the branch line.", {"path": {**S, "description": "Limit to this path"}})
    read_tool(
        "git_diff",
        diff,
        "Show changes: the working tree, the index (staged) or against a ref such as main...HEAD.",
        {
            "staged": {"type": "boolean", "description": "Changes staged for commit"},
            "ref": {**S, "description": "A commit or range, e.g. main...HEAD"},
            "paths": PATH_LIST,
            "stat": {"type": "boolean", "description": "Only the per-file summary"},
            "context": {"type": "integer", "description": "Context lines, 0-20 (default 3)"},
        },
    )
    read_tool(
        "git_log",
        log,
        "Recent commits, one per line: hash, date, author, subject.",
        {
            "n": {"type": "integer", "description": f"How many (default 20, at most {settings['log_max']})"},
            "path": S,
            "author": S,
            "since": {**S, "description": "e.g. 2.weeks or 2025-01-01"},
            "grep": {**S, "description": "Commit messages matching this pattern"},
            "ref": {**S, "description": "Start from this branch or commit"},
        },
    )
    read_tool(
        "git_show",
        show,
        "Show one commit (message and diff), optionally one file of it.",
        {"rev": {**S, "description": "Commit, tag or branch"}, "path": S, "stat": {"type": "boolean"}},
        required=["rev"],
    )
    read_tool(
        "git_blame",
        blame,
        "Who last changed each line of a file, optionally for a line range.",
        {"path": S, "start": {"type": "integer"}, "end": {"type": "integer"}},
        required=["path"],
    )
    read_tool("git_branch", branch, "List local and remote branches with their last commit.", {})
    if not settings["mutations"]:
        return
    write_tool(
        "git_add",
        add,
        "Stage files for commit. Returns the short status afterwards.",
        {"paths": {**PATH_LIST, "description": 'Files or folders to stage; "." stages everything'}},
        required=["paths"],
    )
    write_tool(
        "git_commit",
        commit,
        "Create a commit from what is staged (or from `paths` / `all`). Hooks run; it never amends and never skips them. "
        "Returns the new commit's summary.",
        {
            "message": {**S, "description": "The commit message"},
            "paths": {**PATH_LIST, "description": "Stage these files first, then commit"},
            "all": {"type": "boolean", "description": "Also stage every modified tracked file (git commit -a)"},
        },
        required=["message"],
    )
    write_tool(
        "git_switch",
        switch,
        "Switch to a branch, or create it with create=true. Returns the short status afterwards.",
        {"branch": S, "create": {"type": "boolean"}},
        required=["branch"],
        subject_key="branch",
    )
