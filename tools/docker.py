"""Docker tools for the model: ps, images, logs, inspect, stats, compose (read-only parts) and exec, start/stop, compose up/down.

Each tool runs one ``docker`` command and returns compact text, so prefer them over ``bash docker ...``: JSON is
turned into short lines, logs are bounded and filtered, read calls run side by side without a prompt. Starting,
stopping, restarting, ``docker exec`` and the compose commands that change things ask first. There is no ``rm``,
``kill``, ``prune`` or ``compose down -v``. Settings (``/ext settings tools/docker``): ``max_chars`` (output cut),
``timeout`` (seconds per command) and ``logs_max`` (most log lines ``docker_logs`` returns).

Install it with ``/ext``. Needs Docker (Docker Desktop, or ``brew install --cask docker``).
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
__tags__ = ["docker"]

DEFAULTS = {"max_chars": 30000, "timeout": 60, "logs_max": 2000}

SCHEMA = {
    "max_chars": {"description": "Longest output of one call in characters; the rest is cut.", "min": 1000, "max": 1_000_000},
    "timeout": {"description": "Seconds one docker command may run before it is killed.", "min": 1, "max": 600},
    "logs_max": {"description": "Most log lines docker_logs may return.", "min": 1, "max": 100_000},
}

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]*")
"""What a container, image or compose service name may look like."""
COMPOSE_READ = ("ps", "config", "logs")
"""The compose actions that change nothing."""
COMPOSE_ACTIONS = ("ps", "config", "logs", "up", "down", "restart", "stop", "start", "build")
INSTALL = "Docker Desktop or brew install --cask docker"

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



def _name(field, value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError(f"{field} {value!r} is not a valid name; use letters, digits and _ . : / @ - (not starting with -)")
    return value


def _names(field, value):
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list of names")
    return [_name(field, v) for v in value]


def _lines(out):
    """The JSON objects of ``docker ... --format '{{json .}}'`` output."""
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                raise RuntimeError(f"unexpected docker output: {line[:200]}") from None
    return rows


def _columns(rows):
    """``rows`` (lists of cells) as lines with two spaces between aligned columns."""
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows)


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)

    def docker(args, ctx, *, how, merge=False):
        """Run ``docker <args>``; the output clipped (stdout and stderr together when ``merge``)."""
        exe = shutil.which("docker")
        if exe is None:
            raise ValueError(f"docker is not installed or not on PATH; install it with {INSTALL}")
        code, out, err = _run([exe, *args], ctx.cwd, settings["timeout"], ctx)
        if code != 0:
            if "Cannot connect to the Docker daemon" in err:
                raise RuntimeError("the Docker daemon is not running; start Docker Desktop and retry")
            raise RuntimeError(f"docker {args[0]} failed (exit {code}): {(err.strip() or out.strip())[:500]}")
        text = out + err if merge else out
        return text if how is None else _clip(text, settings["max_chars"], how)

    def ps(input, ctx):
        out = docker(["ps", *(["-a"] if input.get("all") else []), "--format", "{{json .}}"], ctx, how=None)
        rows = [[r.get("Names", ""), r.get("Image", ""), r.get("Status", ""), r.get("Ports", "")] for r in _lines(out)]
        return _clip(_columns(rows), settings["max_chars"], "pass all=false") if rows else "(no containers)"

    def images(input, ctx):
        out = docker(["images", "--format", "{{json .}}"], ctx, how=None)
        rows = [
            [f"{r.get('Repository', '')}:{r.get('Tag', '')}", r.get("ID", ""), r.get("Size", ""), r.get("CreatedSince", "")]
            for r in _lines(out)
        ]
        return _clip(_columns(rows), settings["max_chars"], "there are many images") if rows else "(no images)"

    def logs(input, ctx):
        container = _name("container", input.get("container"))
        tail = input.get("tail", 200)
        if isinstance(tail, bool) or not isinstance(tail, int):
            raise ValueError("tail must be an integer")
        args = ["logs", "--tail", str(max(1, min(settings["logs_max"], tail)))]
        if input.get("since"):
            args += ["--since", _name("since", input["since"])]
        text = docker([*args, container], ctx, how=None, merge=True)
        if input.get("grep"):
            try:
                pattern = re.compile(input["grep"])
            except re.error as e:
                raise ValueError(f"grep is not a valid regular expression: {e}") from None
            text = "".join(line for line in text.splitlines(keepends=True) if pattern.search(line))
        return _clip(text, settings["max_chars"], "lower tail or pass since or grep") if text.strip() else "(no log lines)"

    def inspect(input, ctx):
        args = ["inspect"]
        if input.get("format"):
            args.append(f"--format={input['format']}")
        return docker([*args, _name("target", input.get("target"))], ctx, how="pass format to pick fields")

    def stats(input, ctx):
        out = docker(["stats", "--no-stream", "--format", "{{json .}}"], ctx, how=None)
        rows = [
            [r.get("Name", ""), r.get("CPUPerc", ""), r.get("MemUsage", ""), r.get("MemPerc", ""), r.get("NetIO", ""), r.get("PIDs", "")]
            for r in _lines(out)
        ]
        if not rows:
            return "(no running containers)"
        return _clip(_columns([["NAME", "CPU", "MEM", "MEM%", "NET I/O", "PIDS"], *rows]), settings["max_chars"], "there are many containers")

    def compose_read_only(input, ctx):
        return input.get("action") in COMPOSE_READ

    def compose_confirm(input, ctx):
        return input.get("action") not in COMPOSE_READ

    def compose(input, ctx):
        action = input.get("action")
        if action not in COMPOSE_ACTIONS:
            raise ValueError(f"action must be one of: {', '.join(COMPOSE_ACTIONS)}")
        args = ["compose"]
        if input.get("file"):
            file = input["file"]
            if not isinstance(file, str) or file.startswith("-"):
                raise ValueError("file must be a path that does not start with '-'")
            args += ["-f", file]
        args.append(action)
        if action == "up":
            args.append("-d")
        elif action == "logs":
            tail = input.get("tail", 200)
            if isinstance(tail, bool) or not isinstance(tail, int):
                raise ValueError("tail must be an integer")
            args += ["--no-color", "--tail", str(max(1, min(settings["logs_max"], tail)))]
        if input.get("service"):
            args.append(_name("service", input["service"]))
        text = docker(args, ctx, how="pass service, or tail for logs", merge=True)
        return text if text.strip() else "(no output)"

    def exec_(input, ctx):
        container = _name("container", input.get("container"))
        command = input.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(c, str) and c for c in command):
            raise ValueError('command must be a non-empty list of strings, e.g. ["ls", "-la"] (it runs without a shell)')
        out = docker(["exec", container, *command], ctx, how="pipe less output: narrow the command", merge=True)
        return out if out.strip() else "(no output)"

    def container(input, ctx):
        action = input.get("action")
        if action not in ("start", "stop", "restart"):
            raise ValueError("action must be start, stop or restart (there is no rm or kill here)")
        names = _names("containers", input.get("containers"))
        docker([action, *names], ctx, how=None)
        return f"{action}: {', '.join(names)}"

    S = {"type": "string"}
    PREFER = " Prefer it over `bash docker ...`: compact output, bounded size and no permission prompt."

    def read_tool(name, run, description, properties, required=()):
        minimal.register_tool(
            name,
            run,
            description + PREFER,
            {"type": "object", "properties": properties, "required": list(required)},
            read_only=True,
        )

    read_tool("docker_ps", ps, "List containers: name, image, status, ports.", {"all": {"type": "boolean", "description": "Include stopped containers"}})
    read_tool("docker_images", images, "List images: name:tag, id, size, age.", {})
    read_tool(
        "docker_logs",
        logs,
        "Recent log lines of a container (stdout and stderr, no follow), optionally filtered by a regex.",
        {
            "container": S,
            "tail": {"type": "integer", "description": f"Lines from the end (default 200, at most {settings['logs_max']})"},
            "since": {**S, "description": "e.g. 10m or 2025-01-01T10:00:00"},
            "grep": {**S, "description": "Keep only lines matching this regular expression"},
        },
        ["container"],
    )
    read_tool(
        "docker_inspect",
        inspect,
        "Low-level details of a container, image or network as JSON; pass format to pick fields.",
        {"target": S, "format": {**S, "description": "Go template, e.g. {{.State.Status}}"}},
        ["target"],
    )
    read_tool("docker_stats", stats, "One snapshot of CPU, memory, network and PIDs of the running containers.", {})
    minimal.register_tool(
        "docker_compose",
        compose,
        "Docker Compose: ps, config and logs only read; up (always detached), down (never removes volumes), restart, stop, "
        "start and build ask first. Prefer it over `bash docker compose ...`.",
        {
            "type": "object",
            "properties": {
                "action": {**S, "enum": list(COMPOSE_ACTIONS)},
                "service": S,
                "file": {**S, "description": "Compose file (default: the project's)"},
                "tail": {"type": "integer", "description": "Log lines per service for logs (default 200)"},
            },
            "required": ["action"],
        },
        read_only=compose_read_only,
        confirm=compose_confirm,
    )
    minimal.register_tool(
        "docker_exec",
        exec_,
        "Run a command inside a running container, without a shell: pass the argv as a list.",
        {
            "type": "object",
            "properties": {"container": S, "command": {"type": "array", "items": S}},
            "required": ["container", "command"],
        },
        confirm=True,
        subject_key="container",
    )
    minimal.register_tool(
        "docker_container",
        container,
        "Start, stop or restart containers (never remove or kill them).",
        {
            "type": "object",
            "properties": {"action": {**S, "enum": ["start", "stop", "restart"]}, "containers": {"type": "array", "items": S}},
            "required": ["action", "containers"],
        },
        confirm=True,
    )
