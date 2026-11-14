"""Go TUI: a terminal UI built with Bubble Tea, Bubbles and Lip Gloss, run with `--ui go`.

A second terminal interface next to the Textual one. This package holds a small Go program and the
bridge that runs it: minimal builds the program once with your Go toolchain (Go 1.26 or later is
needed; the binary is cached in minimal's data folder) and talks to it in JSON lines. Run it with
`minimal --ui go`, or set `"ui": "go"` in settings.json.

It draws the transcript with Markdown, tool calls, questions, panels (`register_panel`), status segments
and renderers (`register_renderer`). Extensions that need Textual (`__frontend__ = "textual"`) are skipped.
Keys: enter sends, esc or ctrl+c interrupts a turn, ctrl+d quits, ctrl+o expands tool output, ctrl+b
hides the sidebar, page up/down scroll.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import itertools
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from minimal.api import ConsoleFrontend, ExitRepl, __version__ as MINIMAL_VERSION

from .views import Views

__version__ = "1.0"
__api__ = "1.3"

PROTOCOL = 1
"""Version of the JSON-lines protocol; the Go program refuses another one."""

REPLAY_LIMIT = 200
"""Most messages of a resumed session sent to be drawn."""

GO_MISSING = (
    "the go frontend needs the Go toolchain (1.26 or later) to build its terminal UI: "
    "install it from https://go.dev/dl, or run minimal --ui tui or --ui console"
)

QUEUED = object()
"""Put in the inbox when an extension queues a user message, to wake the main loop."""


def source_files(folder: Path) -> list[Path]:
    """The Go program's files: every ``*.go`` plus ``go.mod`` and ``go.sum``, sorted by name."""
    return sorted(p for p in folder.iterdir() if p.suffix == ".go" or p.name in ("go.mod", "go.sum"))


def build(minimal) -> Path:
    """Build the Go program (or reuse the cached build of exactly these sources) and return its path.

    Raises:
        RuntimeError: if there is no Go toolchain, or the build fails.
    """
    go = shutil.which("go")
    if go is None:
        raise RuntimeError(GO_MISSING)
    folder = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in source_files(folder):
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    binary = minimal.data_dir("global") / f"tui-{digest.hexdigest()[:16]}{'.exe' if os.name == 'nt' else ''}"
    if binary.exists():
        return binary
    print("go frontend: building the terminal UI (first run only)…", file=sys.stderr)
    # proxy.golang.org sometimes cuts a module download short; the second try fetches from the source.
    for env in ({}, {"GOPROXY": "direct"}):
        result = subprocess.run(
            [go, "build", "-o", str(binary), "."],
            cwd=folder,
            env={**os.environ, "CGO_ENABLED": "0", **env},
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return binary
    raise RuntimeError(f"go build failed:\n{result.stdout}{result.stderr}".rstrip())


class Output:
    """File-like that forwards what commands and extensions print to the Go program."""

    def __init__(self, bridge: Bridge, stderr: bool) -> None:
        self.bridge = bridge
        self.stderr = stderr

    def write(self, text: str) -> int:
        if text:
            self.bridge.send(t="output", text=text, stderr=self.stderr)
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


class Bridge:
    """The Go program as seen from minimal: lines out to its stdin, lines in from its stdout."""

    def __init__(self, host, proc: subprocess.Popen) -> None:
        self.host = host
        self.proc = proc
        self.write_lock = threading.Lock()
        self.inbox: queue.Queue = queue.Queue()
        self.answers: dict[str, tuple[threading.Event, list]] = {}
        self.ids = itertools.count(1)
        self.closed = threading.Event()
        self.suspended = threading.Event()
        self.views: Views  # set by run() before the reader starts

    def send(self, **message) -> None:
        line = json.dumps(message, default=str) + "\n"
        with self.write_lock:
            try:
                assert self.proc.stdin is not None
                self.proc.stdin.write(line)
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass  # the Go program is gone; the reader notices and ends the session

    def question(self, **message):
        """Send a question and wait for the Go program's answer; ``None`` if it was cancelled or the program quit."""
        id = str(next(self.ids))
        done = threading.Event()
        slot: list = [None]
        self.answers[id] = (done, slot)
        self.send(id=id, **message)
        while not done.wait(0.2):
            if self.closed.is_set():
                break
        self.answers.pop(id, None)
        return slot[0]

    def read(self) -> None:
        """Run in a thread: turn the Go program's lines into submits, interrupts and answers."""
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            kind = message.get("t")
            if kind == "submit":
                self.inbox.put(str(message.get("text", "")).strip())
            elif kind == "interrupt":
                self.host.interrupt()
            elif kind == "answer":
                entry = self.answers.get(str(message.get("id")))
                if entry is not None:
                    entry[1][0] = message.get("value")
                    entry[0].set()
            elif kind == "render":
                self.views.request(message)
            elif kind == "suspended":
                self.suspended.set()
            elif kind == "quit":
                break
        self.closed.set()
        self.inbox.put(None)
        for done, _ in list(self.answers.values()):
            done.set()


class BridgeFrontend:
    """Shows turns in the Go program."""

    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge

    def text(self, chunk: str) -> None:
        self.bridge.send(t="text", chunk=chunk)

    def tool_call(self, call: dict) -> None:
        views = self.bridge.views
        self.bridge.send(t="tool_call", call=call, body=views.tool(call, None))
        views.refresh({"kind": "tool_call", "call": call})

    def tool_result(self, call: dict, result: dict) -> None:
        views = self.bridge.views
        self.bridge.send(t="tool_result", call=call, result=result, body=views.tool(call, result))
        views.refresh({"kind": "tool_result", "call": call, "result": result})

    def turn_end(self, error: str | None) -> None:
        self.bridge.send(t="turn_end", error=error)

    def ask(self, question: str) -> bool:
        return self.bridge.question(t="ask", question=question) is True

    def choose(self, title: str, options: list[tuple[str, str]]) -> str | None:
        value = self.bridge.question(t="choose", title=title, options=[{"value": v, "label": label} for v, label in options])
        return value if isinstance(value, str) else None

    def choose_many(self, title: str, options: list[tuple[str, str, bool]]) -> list[str] | None:
        value = self.bridge.question(
            t="choose_many",
            title=title,
            options=[{"value": v, "label": label, "checked": checked} for v, label, checked in options],
        )
        if not isinstance(value, list):
            return None
        ticked = {str(v) for v in value}
        return [v for v, _, _ in options if v in ticked]

    def ask_text(self, title: str) -> str | None:
        value = self.bridge.question(t="ask_text", title=title)
        return value.strip() or None if isinstance(value, str) else None

    def reloaded(self) -> None:
        views = self.bridge.views
        views.reset()
        self.bridge.send(t="reloaded", renderers=views.kinds(), **problems(self.bridge.host))
        views.refresh({"kind": "end"})

    def widget(self, name: str) -> object | None:
        return None

    def notify(self, text: str, kind: str) -> None:
        self.bridge.send(t="notify", text=text, kind=kind)

    def queued(self) -> None:
        self.bridge.inbox.put(QUEUED)


def problems(host) -> dict:
    """What the last reload reported: failed and skipped extensions, and the untrusted notice."""
    return {
        "errors": host.extension_errors,
        "skipped": host.extension_skipped,
        "notice": host.untrusted_notice(),
    }


def status(host) -> dict:
    return dataclasses.asdict(host.status())


@contextlib.contextmanager
def printing_to(bridge: Bridge):
    """Show what is printed meanwhile (command output, extension messages) in the Go program."""
    with contextlib.redirect_stdout(Output(bridge, False)), contextlib.redirect_stderr(Output(bridge, True)):  # type: ignore[type-var]
        yield


def execute(host, bridge: Bridge, line: str) -> None:
    """Run one user line: a ``/command`` or a message to the model. Raises ``ExitRepl`` for ``/exit``."""
    if line.startswith("/"):
        command = host.command(line[1:].partition(" ")[0])
        if command is not None and command.terminal:
            run_in_terminal(host, bridge, line)
            return
        with printing_to(bridge):
            host.run_command(line)
    else:
        with printing_to(bridge):
            host.submit(line)


def run_in_terminal(host, bridge: Bridge, line: str) -> None:
    """Run a command that reads the real terminal: the Go program gives it up meanwhile."""
    bridge.suspended.clear()
    bridge.send(t="suspend")
    bridge.suspended.wait(5)
    host.attach(ConsoleFrontend())
    try:
        host.run_command(line)
    finally:
        host.attach(BridgeFrontend(bridge))
        bridge.send(t="resume")


def run(minimal, host) -> None:
    try:
        binary = build(minimal)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    proc = subprocess.Popen(
        [str(binary)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    bridge = Bridge(host, proc)
    bridge.views = Views(host, bridge)
    bridge.views.start()
    threading.Thread(target=bridge.read, name="go-tui-reader", daemon=True).start()
    host.attach(BridgeFrontend(bridge))
    messages = host.messages[-REPLAY_LIMIT:]
    bridge.send(
        t="hello",
        protocol=PROTOCOL,
        version=MINIMAL_VERSION,
        status=status(host),
        messages=messages,
        hidden=len(host.messages) - len(messages),
        renderers=bridge.views.kinds(),
        bodies=bridge.views.bodies(messages),
        **problems(host),
    )
    try:
        with printing_to(bridge):
            host.begin()
        bridge.views.refresh({"kind": "end"})
        loop(host, bridge)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.send(t="quit")
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    if proc.returncode:
        print(f"go frontend: the terminal UI exited with code {proc.returncode}", file=sys.stderr)
        sys.exit(1)


def loop(host, bridge: Bridge) -> None:
    """Run what the user types, one line at a time, until the Go program quits or a command exits."""
    while True:
        line = host.next_queued()
        if line is None:
            item = bridge.inbox.get()
            if item is None:
                return
            if item is QUEUED or not item:
                continue
            line = item
        try:
            bridge.views.refresh({"kind": "start", "turn": not line.startswith("/")})
            execute(host, bridge, line)
        except ExitRepl:
            return
        bridge.views.refresh({"kind": "end"})
        bridge.send(t="idle", status=status(host))


def register(minimal):
    minimal.register_frontend(
        "go",
        lambda host: run(minimal, host),
        "a terminal UI written in Go with Bubble Tea (needs the Go toolchain; built on first run)",
    )
