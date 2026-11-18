"""Terminal title: names the terminal window or tab "minimal: <project> [idle|working]" and restores it on exit."""

from __future__ import annotations

import sys
from pathlib import Path

from textual.widgets import Static

__version__ = "1.1"
__api__ = "2"
__tags__ = ["ui"]

NAME = "term_title"

DEFAULTS = {"prefix": "minimal", "restore": ""}
"""``prefix``: what the title starts with; ``restore``: the title to set on exit (empty: pop the one the terminal
had before, which most terminals support but a few, such as Terminal.app, ignore)."""

MAX_LENGTH = 100
"""Characters of the title; longer ones lose their end."""

PUSH = "\x1b[22;0t"
"""Save the terminal's current title on its stack (xterm window ops, also iTerm2, kitty, WezTerm, tmux)."""

POP = "\x1b[23;0t"
"""Bring back the title saved by PUSH."""


def clean(text: object) -> str:
    """``text`` as one printable line: control characters (the ones that would end or inject an escape sequence) become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def build_title(prefix: str, cwd: str, state: str) -> str:
    """``"<prefix>: <project folder> [<state>]"`` with every control character removed, cut to ``MAX_LENGTH``.

    The ``[state]`` suffix always survives the cut; the project is the name of ``cwd``'s folder.
    """
    project = Path(cwd).name or cwd
    head = f"{clean(prefix)}: {clean(project)}"
    suffix = f" [{clean(state)}]"
    room = max(1, MAX_LENGTH - len(suffix))
    return (head if len(head) <= room else head[: room - 1] + "…") + suffix


def osc_title(title: str) -> str:
    """The escape sequence that sets the window and icon title (OSC 0) to ``title``."""
    return f"\x1b]0;{clean(title)}\x07"


class Terminal:
    """Where title sequences go: Textual's driver while the UI runs, else the real terminal if there is one."""

    def __init__(self) -> None:
        self.app = None  # the Textual app, set by the anchor widget once mounted

    def write(self, data: str) -> bool:
        """Send ``data`` to the terminal; False if there is none to send it to."""
        app = self.app
        if app is not None and app.is_running:
            driver = getattr(app, "_driver", None)  # Textual's writer thread: no interleaving with its own output
            if driver is None:
                return False
            driver.write(data)
            return True
        # No UI (console mode), or the UI has exited: stdout is the real terminal again. While the UI runs, stdout
        # is Textual's capture, never ``sys.__stdout__``, so this cannot write into the middle of its output.
        stream = sys.__stdout__
        if stream is None or sys.stdout is not stream or not stream.isatty():
            return False
        stream.write(data)
        stream.flush()
        return True


class Title:
    """Sets the title when the state changes and gives the terminal's own title back on exit."""

    def __init__(self, settings, terminal: Terminal) -> None:
        self.settings = settings
        self.terminal = terminal
        self.pushed = False
        self.shown = ""

    def show(self, cwd: str, state: str) -> None:
        title = build_title(self.settings["prefix"], cwd, state)
        if title == self.shown:
            return
        if not self.pushed:
            self.pushed = self.terminal.write(PUSH)
        if self.terminal.write(osc_title(title)):
            self.shown = title

    def restore(self) -> None:
        if not self.pushed:
            return
        self.pushed = False
        self.shown = ""
        restore = clean(self.settings["restore"])
        self.terminal.write(osc_title(restore) if restore else POP)


class Anchor(Static):
    """Invisible: gives the extension the running app and an ``idle`` signal after every turn, even a failed one."""

    DEFAULT_CSS = "Anchor { display: none; }"

    def __init__(self, terminal: Terminal, tracker: Title) -> None:
        super().__init__()
        self.terminal = terminal
        self.tracker = tracker

    def on_mount(self) -> None:
        self.terminal.app = self.app

    def refresh_state(self, ctx) -> None:
        self.tracker.show(ctx.cwd, "idle")


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS)
    terminal = Terminal()
    title = Title(settings, terminal)

    minimal.on("session_start", lambda event: title.show(event["ctx"].cwd, "idle"))
    minimal.on("turn_start", lambda event: title.show(event["ctx"].cwd, "working"))
    minimal.on("turn_end", lambda event: None if event["nested"] else title.show(event["ctx"].cwd, "idle"))
    minimal.on_dispose(title.restore)
    minimal.register_widget(NAME, lambda ctx: Anchor(terminal, title), area="bottom")
