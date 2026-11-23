"""Terminal title: names the terminal window or tab from a template (default "minimal: <project> [idle|working]") and restores it on exit."""

from __future__ import annotations

import string
import sys
from pathlib import Path

from textual.widgets import Static

__version__ = "1.3"
__api__ = "2.4"
__tags__ = ["ui"]

NAME = "term_title"

PLACEHOLDERS = ("prefix", "project", "state", "branch", "model", "provider", "mode", "cwd")
"""The names a ``template`` may use: ``{project}`` is the working directory's folder, ``{branch}`` the git branch
(empty outside a repository), ``{mode}`` the current mode (empty for none), ``{cwd}`` the full path."""

DEFAULTS = {
    "enabled": True,
    "template": "{prefix}: {project} [{state}]",
    "prefix": "minimal",
    "idle": "idle",
    "working": "working",
    "max_length": 100,
    "restore": "",
    "push_pop": True,
}

SCHEMA = {
    "enabled": {"description": "Set the terminal title. False registers nothing and never touches the title."},
    "template": {
        "description": (
            "The title, with placeholders " + ", ".join("{" + name + "}" for name in PLACEHOLDERS)
            + ". Example: {prefix}: {project}@{branch} {model} [{state}]. Empty parts leave their text blank."
        )
    },
    "prefix": {"description": "Text of the {prefix} placeholder."},
    "idle": {"description": "Text of the {state} placeholder between turns."},
    "working": {"description": "Text of the {state} placeholder while a turn runs."},
    "max_length": {
        "description": "Characters of the title; a longer one loses the end of {project}, then of the whole title.",
        "min": 10,
        "max": 500,
    },
    "restore": {
        "description": (
            "The title to set on exit. Empty: pop the one the terminal had before (needs push_pop; most "
            "terminals support it, a few, such as Terminal.app, ignore it)."
        )
    },
    "push_pop": {
        "description": "Save the terminal's title when starting and bring it back on exit (xterm window operations)."
    },
}

PUSH = "\x1b[22;0t"
"""Save the terminal's current title on its stack (xterm window ops, also iTerm2, kitty, WezTerm, tmux)."""

POP = "\x1b[23;0t"
"""Bring back the title saved by PUSH."""


def clean(text: object) -> str:
    """``text`` as one printable line: control characters (the ones that would end or inject an escape sequence) become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def check_template(template: str) -> None:
    """Raise ``ValueError`` if ``template`` is not a format string over ``PLACEHOLDERS``."""
    try:
        fields = [field for _, field, _, _ in string.Formatter().parse(template) if field is not None]
    except ValueError as error:
        raise ValueError(f"term_title: template is not valid: {error}") from None
    for field in fields:
        if field not in PLACEHOLDERS:
            raise ValueError(f"term_title: template uses {{{field}}}; use only {', '.join(PLACEHOLDERS)}")


def build_title(template: str, values: dict[str, str], max_length: int = 100) -> str:
    """``template`` filled with ``values`` (each cleaned of control characters), cut to ``max_length``.

    A title over the limit first shortens the project, so what follows it (the state) survives; if that is not
    enough the end of the whole title is cut.
    """
    values = {name: clean(values.get(name, "")) for name in PLACEHOLDERS}
    title = clean(template.format(**values))
    excess = len(title) - max_length
    project = values["project"]
    if excess > 0 and len(project) > 1:
        values["project"] = project[: max(1, len(project) - excess - 1)] + "…"
        title = clean(template.format(**values))
    if len(title) > max_length:
        title = title[: max_length - 1] + "…"
    return title


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
        self.state = "idle"

    def values(self, ctx) -> dict[str, str]:
        """What the template's placeholders stand for right now."""
        settings = self.settings
        git = ctx.git() if "{branch}" in settings["template"] else None
        return {
            "prefix": settings["prefix"],
            "project": Path(ctx.cwd).name or ctx.cwd,
            "state": settings[self.state],
            "branch": (git.branch or "") if git else "",
            "model": ctx.model or "",
            "provider": ctx.provider_name or "",
            "mode": ctx.mode or "",
            "cwd": ctx.cwd,
        }

    def show(self, ctx, state: str | None = None) -> None:
        """Send the title for ``state`` (``"idle"`` or ``"working"``; ``None``: the last one) if it changed."""
        if state is not None:
            self.state = state
        title = build_title(self.settings["template"], self.values(ctx), self.settings["max_length"])
        if title == self.shown:
            return
        if self.settings["push_pop"] and not self.pushed:
            self.pushed = self.terminal.write(PUSH)
        if self.terminal.write(osc_title(title)):
            self.shown = title

    def restore(self) -> None:
        shown, pushed = self.shown, self.pushed
        self.pushed = False
        self.shown = ""
        restore = clean(self.settings["restore"])
        if restore and (shown or pushed):
            self.terminal.write(osc_title(restore))
        elif pushed:
            self.terminal.write(POP)


class Anchor(Static):
    """Invisible: gives the extension the running app and refreshes the title when the UI redraws (a git branch
    that changed, a reload, the end of a command)."""

    DEFAULT_CSS = "Anchor { display: none; }"

    def __init__(self, terminal: Terminal, tracker: Title) -> None:
        super().__init__()
        self.terminal = terminal
        self.tracker = tracker

    def on_mount(self) -> None:
        self.terminal.app = self.app

    def refresh_state(self, ctx) -> None:
        self.tracker.show(ctx)


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    try:
        check_template(settings["template"])
    except ValueError as exc:
        reason = str(exc).removeprefix("term_title: ")
        minimal.report_problem(
            f"extensions.settings.term_title.template: {reason}; the default template {DEFAULTS['template']!r} is used until you fix it"
        )
        settings = {**settings, "template": DEFAULTS["template"]}
    terminal = Terminal()
    title = Title(settings, terminal)

    minimal.on("session_start", lambda event: title.show(event["ctx"], "idle"))
    minimal.on("turn_start", lambda event: title.show(event["ctx"], "working"))
    minimal.on("turn_end", lambda event: None if event["nested"] else title.show(event["ctx"], "idle"))
    minimal.on("mode_change", lambda event: title.show(event["ctx"]))
    minimal.on_dispose(title.restore)
    minimal.register_widget(NAME, lambda ctx: Anchor(terminal, title), area="bottom")
