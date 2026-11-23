"""Structural code search and rewrite for the model through ast-grep: `ast_grep_search` and `ast_grep_rewrite`.

ast-grep matches code by syntax tree, not text: the pattern ``console.log($ARG)`` finds every call whatever the
spacing or arguments, and ``$$$`` matches a list. ``ast_grep_search`` is read-only; ``ast_grep_rewrite`` only prints
the diff it would make unless ``apply`` is true, and applying asks first. The program is ``ast-grep`` (not ``sg``,
which clashes with a system command). Settings (``/ext settings tools/ast_grep``): ``max_chars``, ``timeout`` and
``limit`` (most matches listed).

Install it with ``/ext``. Needs ``ast-grep`` (``brew install ast-grep``).
"""

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time

__version__ = "1.0"
__api__ = "2.4"
__tags__ = ["search"]

DEFAULTS = {"max_chars": 30000, "timeout": 60, "limit": 100}

SCHEMA = {
    "max_chars": {"description": "Longest output in characters; the rest is cut.", "min": 1000, "max": 1_000_000},
    "timeout": {"description": "Seconds ast-grep may run before it is killed.", "min": 1, "max": 600},
    "limit": {"description": "Most matches ast_grep_search lists.", "min": 1, "max": 10_000},
}

INSTALL = "brew install ast-grep"

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



def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)

    def base_args(input, ctx, with_rewrite):
        pattern = input.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("pattern is required, e.g. console.log($ARG)")
        args = ["run", f"--pattern={pattern}"]
        if with_rewrite:
            rewrite = input.get("rewrite")
            if not isinstance(rewrite, str):
                raise ValueError("rewrite is required: the replacement code, using the same $VARIABLES")
            args.append(f"--rewrite={rewrite}")
        lang = input.get("lang")
        if lang is not None:
            if not isinstance(lang, str) or not re.fullmatch(r"[A-Za-z0-9_+-]+", lang):
                raise ValueError("lang must be a language name such as python, ts, go or rust")
            args.append(f"--lang={lang}")
        paths = input.get("paths") or []
        if not isinstance(paths, list) or not all(isinstance(p, str) and p for p in paths):
            raise ValueError("paths must be a list of files or folders")
        root = os.path.realpath(ctx.cwd)
        for p in paths:
            real = os.path.realpath(os.path.join(ctx.cwd, p))
            if real != root and not real.startswith(root + os.sep):
                raise ValueError(f"{p} is outside the working folder; pass paths inside it")
        return args, paths

    def ast_grep(args, paths, ctx):
        exe = shutil.which("ast-grep")
        if exe is None:
            raise ValueError(f"ast-grep is not installed or not on PATH; install it with {INSTALL}")
        argv = [exe, *args, *(["--", *paths] if paths else [])]
        code, out, err = _run(argv, ctx.cwd, settings["timeout"], ctx)
        if code != 0:
            raise RuntimeError(f"ast-grep failed (exit {code}): {(err.strip() or out.strip())[:500]}")
        return out

    def search(input, ctx):
        args, paths = base_args(input, ctx, False)
        limit = input.get("limit", settings["limit"])
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        limit = max(1, min(settings["limit"] * 10, limit))
        out = ast_grep([*args, "--json=stream"], paths, ctx)
        matches = []
        for line in out.splitlines():
            if line.strip():
                try:
                    matches.append(json.loads(line))
                except ValueError:
                    continue
        if not matches:
            return "(no matches)"
        rows = []
        for m in matches[:limit]:
            start = (m.get("range") or {}).get("start") or {}
            first = " ".join((m.get("lines") or m.get("text") or "").strip().splitlines()[:1])
            rows.append(f"{m.get('file', '?')}:{start.get('line', 0) + 1}:{start.get('column', 0) + 1}  {first}")
        if len(matches) > limit:
            rows.append(f"[{len(matches) - limit} more matches; narrow paths or the pattern, or raise limit]")
        return _clip("\n".join(rows), settings["max_chars"], "narrow paths or the pattern")

    def rewrite(input, ctx):
        args, paths = base_args(input, ctx, True)
        apply = bool(input.get("apply"))
        out = ast_grep([*args, *(["--update-all"] if apply else [])], paths, ctx)
        if apply:
            ctx.git_refresh()
            return out.strip() or "rewrite applied"
        if not out.strip():
            return "(no matches; nothing would change)"
        return _clip(out + "\n[preview only: pass apply=true to write these changes]", settings["max_chars"], "narrow paths or the pattern")

    S = {"type": "string"}
    PATHS = {"type": "array", "items": S, "description": "Files or folders (default: the working folder)"}
    minimal.register_tool(
        "ast_grep_search",
        search,
        "Find code by syntax with ast-grep patterns ($NAME matches one node, $$$ a list), e.g. `console.log($ARG)` or "
        "`def $F($$$): $$$`. Prefer it over grep when spacing, arguments or nesting vary. Returns file:line:column and the first line.",
        {
            "type": "object",
            "properties": {
                "pattern": {**S, "description": "ast-grep pattern in the language's own syntax"},
                "lang": {**S, "description": "python, ts, tsx, js, go, rust, java, ... (default: by file extension)"},
                "paths": PATHS,
                "limit": {"type": "integer"},
            },
            "required": ["pattern"],
        },
        read_only=True,
    )
    minimal.register_tool(
        "ast_grep_rewrite",
        rewrite,
        "Rewrite code structurally: replace every match of pattern with rewrite (same $VARIABLES). Without apply it only shows the diff; "
        "apply=true writes the files (it asks first). Prefer it over sed for refactors that must respect syntax.",
        {
            "type": "object",
            "properties": {
                "pattern": S,
                "rewrite": {**S, "description": "Replacement code"},
                "lang": S,
                "paths": PATHS,
                "apply": {"type": "boolean", "description": "Write the changes (default false: preview the diff)"},
            },
            "required": ["pattern", "rewrite"],
        },
        read_only=lambda input, ctx: not input.get("apply"),
        confirm=lambda input, ctx: bool(input.get("apply")),
    )
