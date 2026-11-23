"""Run the project's tests and return a short verdict: the runner, the exit status, the failing tests and the end of the output.

`run_tests(target?)` detects the runner from the working folder (``package.json`` with a ``test`` script: npm, yarn
or pnpm by lockfile; ``Cargo.toml``: cargo; ``go.mod``: go; pytest configuration: pytest; a ``tests/`` folder:
unittest; ``uv run`` in front when there is a ``uv.lock``), runs it without a shell and reports the failures it can
parse (pytest, unittest, go, cargo) before the last lines of output, so the model sees what broke without the whole log.
It asks first, like any command. Settings (``/ext settings tools/run_tests``): ``command`` (your own argv, instead of
the detection), ``timeout``, ``max_chars`` and ``tail_lines``.

Install it with ``/ext``.
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
__tags__ = ["workflow", "diagnostics"]

DEFAULTS = {"command": [], "timeout": 600, "max_chars": 30000, "tail_lines": 60}

SCHEMA = {
    "command": {"description": "Test command as an argv list, e.g. [\"make\", \"test\"] (empty: detect the runner)."},
    "timeout": {"description": "Seconds the tests may run before they are killed.", "min": 1, "max": 3600},
    "max_chars": {"description": "Longest output in characters; the rest is cut.", "min": 1000, "max": 1_000_000},
    "tail_lines": {"description": "Lines from the end of the output shown after the failure list.", "min": 5, "max": 1000},
}

FAILURE_PATTERNS = {
    "pytest": re.compile(r"^FAILED \S.*$", re.M),
    "unittest": re.compile(r"^(?:FAIL|ERROR): .+ \(.+\)$", re.M),
    "go": re.compile(r"^--- FAIL: \S+.*$", re.M),
    "cargo": re.compile(r"^test \S+ \.\.\. FAILED$", re.M),
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



def python_argv():
    exe = shutil.which("python3") or shutil.which("python")
    if exe is None:
        raise ValueError("python is not installed or not on PATH; install it or set the command setting")
    return [os.path.basename(exe)]


def detect(cwd):
    """``(kind, argv)`` of the project's test runner, or ``None``."""
    def has(name):
        return os.path.exists(os.path.join(cwd, name))

    uv = ["uv", "run"] if has("uv.lock") and shutil.which("uv") else []
    if has("package.json"):
        try:
            with open(os.path.join(cwd, "package.json"), encoding="utf-8") as f:
                scripts = (json.load(f).get("scripts") or {})
        except (OSError, ValueError):
            scripts = {}
        if "test" in scripts:
            manager = "pnpm" if has("pnpm-lock.yaml") else "yarn" if has("yarn.lock") else "npm"
            return "npm", [manager, "test"]
    if has("Cargo.toml"):
        return "cargo", ["cargo", "test"]
    if has("go.mod"):
        return "go", ["go", "test", "./..."]
    for name in ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg"):
        if has(name):
            try:
                with open(os.path.join(cwd, name), encoding="utf-8", errors="replace") as f:
                    mentioned = "pytest" in f.read()
            except OSError:
                mentioned = False
            if mentioned or name == "pytest.ini":
                return "pytest", [*uv, *python_argv(), "-m", "pytest", "-q", "-rf", "--tb=short"]
    if os.path.isdir(os.path.join(cwd, "tests")):
        return "unittest", [*uv, *python_argv(), "-m", "unittest", "discover", "-s", "tests"]
    return None


def with_target(kind, argv, target):
    """``argv`` aimed at ``target``; ``ValueError`` where the runner cannot take one."""
    if kind == "npm":
        raise ValueError(
            "target is not supported for npm, yarn or pnpm test; set the command setting (for example "
            '["npx", "jest"]) and pass the path through it'
        )
    if kind == "go":
        return [*argv[:-1], target] if argv[-1] == "./..." else [*argv, target]
    if kind == "unittest":
        return [*argv[: argv.index("discover")], target]
    return [*argv, target]


def failures(kind, text):
    patterns = [FAILURE_PATTERNS[kind]] if kind in FAILURE_PATTERNS else list(FAILURE_PATTERNS.values())
    found = []
    for pattern in patterns:
        found += [m.group(0).strip() for m in pattern.finditer(text)]
    return list(dict.fromkeys(found))


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)

    def run_tests(input, ctx):
        target = input.get("target")
        if target is not None and (not isinstance(target, str) or not target.strip() or target.startswith("-")):
            raise ValueError("target must be a test path or name that does not start with '-'")
        timeout = input.get("timeout", settings["timeout"])
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be a number of seconds")
        timeout = max(1, min(3600, timeout))
        if settings["command"]:
            kind, argv = "custom", [str(p) for p in settings["command"]]
            if target:
                argv = [*argv, target]
        else:
            found = detect(ctx.cwd)
            if found is None:
                raise ValueError("no test runner detected; set the command setting")
            kind, argv = found
            if target:
                argv = with_target(kind, argv, target)
        exe = shutil.which(argv[0])
        if exe is None:
            raise ValueError(f"{argv[0]} is not installed or not on PATH; install it or set the command setting")
        ctx.progress(f"running tests: {' '.join(argv)}")
        started = time.monotonic()
        try:
            code, out, err = _run([exe, *argv[1:]], ctx.cwd, timeout, ctx)
        except RuntimeError as e:
            if "timed out" in str(e):
                raise RuntimeError(f"{e}; raise the timeout or pass a narrower target") from None
            raise
        finally:
            ctx.progress(None)
        seconds = time.monotonic() - started
        text = out + ("\n" + err if err.strip() else "")
        lines = [f"runner: {' '.join(argv)}  exit {code}  {seconds:.1f}s"]
        failed = failures(kind, text)
        if failed:
            lines += [f"FAILED ({len(failed)}):", *[f"  {f}" for f in failed], ""]
        tail = text.rstrip().splitlines()[-settings["tail_lines"] :]
        lines += tail or ["(no output)"]
        return _clip("\n".join(lines), settings["max_chars"], "lower tail_lines or pass a narrower target")

    minimal.register_tool(
        "run_tests",
        run_tests,
        "Run the project's tests (the runner is detected: pytest, unittest, npm/yarn/pnpm, go, cargo) and return the exit "
        "status, the failing tests and the end of the output. Prefer it over `bash` for running tests: failures are listed "
        "first and the output is bounded. target narrows to a file, test id or package.",
        {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "A test file, test id or package (not for npm/yarn/pnpm)"},
                "timeout": {"type": "number", "description": "Seconds before the tests are killed"},
            },
        },
        confirm=True,
    )
