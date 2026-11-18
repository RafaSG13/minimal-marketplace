"""Agent monitor: a live tree of the agents of the session (main, subagents, ...) and /agents to inspect one.

A sidebar panel lists one line per agent, indented under the agent that started it: status glyph, name, model, tool
calls and elapsed time. It is hidden while only the idle main agent exists. ``/agents`` opens a browser in the
terminal UI: Up/Down select an agent and show its prompt, status, usage, error, recent tool calls and last reply;
``c`` interrupts the selected running agent (``ctx.cancel_agent``); Esc closes. ``/agents <id|name>`` prints one
agent's detail, and ``/agents`` without the terminal UI prints the tree.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import NamedTuple

from minimal.api import MAIN_AGENT, theme
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.content import Content
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

__version__ = "1.0"
__api__ = "2.2"

PANEL = "agent_monitor"
BROWSER = "agent_browser"

MAX_PANEL_ROWS = 12
"""Agents drawn in the panel; when there are more, the oldest rows are replaced by a count."""

LABEL_WIDTH = 24
"""Characters of an agent's name before it is cut with ``…`` (its id is always kept)."""

MODEL_WIDTH = 24
"""Characters of the model name shown in a row."""

TRACE_LINES = 6
"""Recent tool calls kept and shown per agent."""

REPLY_LINES = 6
"""Lines of an agent's last reply shown in its detail."""

PROMPT_CHARS = 1500
"""Characters of an agent's prompt shown in its detail."""

MAX_TRACKED = 200
"""Agents whose recent calls are remembered; the oldest is forgotten beyond that."""

STATUS_STYLE = {
    "running": (theme.RUNNING, "warning"),
    "done": (theme.SUCCESS, "success"),
    "error": (theme.ERROR, "error"),
    "interrupted": (theme.WARNING, "warning"),
    "max_turns": (theme.WARNING, "warning"),
}
"""Glyph and theme colour of each agent status."""

CALL_ARGS = ("path", "command", "pattern", "url", "query", "prompt", "name")
"""Tool input keys, in order of preference, shown next to a tool's name in the recent calls."""


# --- text helpers --------------------------------------------------------------


def _escape(ch: str) -> str:
    return ch.encode("unicode_escape").decode("ascii")


def one_line(text: object, width: int | None = None) -> str:
    """``text`` as one line: whitespace collapses to single spaces and other control characters are shown
    escaped (``\\x1b``), never sent to the terminal. Cut with ``…`` beyond ``width`` characters."""
    chars = (" " if ch.isspace() else ch if ch.isprintable() else _escape(ch) for ch in str(text))
    out = " ".join("".join(chars).split())
    return out if width is None or len(out) <= width else out[: max(width - 1, 0)].rstrip() + "…"


def block(text: object, limit: int) -> str:
    """``text`` keeping its line breaks, with other whitespace as spaces and control characters escaped; cut
    with ``…`` beyond ``limit`` characters."""
    text = str(text)
    cut = len(text) > limit
    chars = (
        "\n" if ch == "\n" else " " if ch.isspace() else ch if ch.isprintable() else _escape(ch) for ch in text[:limit]
    )
    out = "".join(chars).strip("\n")
    return out + "…" if cut else out


def elapsed(agent, now: float) -> float:
    """Seconds the agent has run: until it finished, or until ``now`` while it runs."""
    end = now if agent.finished is None else agent.finished
    return max(0.0, end - agent.started)


def format_elapsed(seconds: float) -> str:
    """``3.2s``, ``42s``, ``2m05s`` or ``1h02m``."""
    seconds = max(0.0, seconds)
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    return f"{minutes // 60}h{minutes % 60:02d}m"


# --- tree ----------------------------------------------------------------------


def flatten(agents) -> list[tuple[object, int]]:
    """``(agent, depth)`` in tree order: each agent is followed by the agents it started, oldest first.

    An agent whose parent is not in ``agents`` (or is itself) is a root, so nothing is lost; agents that only
    appear in a parent cycle are appended as roots, so nothing is listed twice either."""
    ids = {a.id for a in agents}
    children: dict[str, list] = {}
    roots = []
    for agent in agents:
        if agent.parent_id is None or agent.parent_id == agent.id or agent.parent_id not in ids:
            roots.append(agent)
        else:
            children.setdefault(agent.parent_id, []).append(agent)
    out: list[tuple[object, int]] = []
    seen: set[str] = set()

    def walk(start: list) -> None:
        stack = [(a, 0) for a in reversed(start)]
        while stack:
            agent, depth = stack.pop()
            if agent.id in seen:
                continue
            seen.add(agent.id)
            out.append((agent, depth))
            stack.extend((child, depth + 1) for child in reversed(children.get(agent.id, ())))

    walk(roots)
    walk([a for a in agents if a.id not in seen])
    return out


def visible(agents) -> bool:
    """Whether the panel shows: not when there is no agent or only the idle main agent."""
    if not agents:
        return False
    return not (len(agents) == 1 and agents[0].id == MAIN_AGENT and agents[0].status != "running")


class Row(NamedTuple):
    """One agent's line: ``indent glyph label  details``; ``style`` is the theme colour name of the glyph."""

    indent: str
    glyph: str
    style: str
    label: str
    details: str

    def text(self) -> str:
        return f"{self.indent}{self.glyph} {self.label}  {self.details}"


def _calls(agent) -> str:
    return f"{agent.tool_calls} call{'' if agent.tool_calls == 1 else 's'}"


def make_row(agent, depth: int, now: float) -> Row:
    """The row of ``agent`` drawn ``depth`` levels deep."""
    glyph, style = STATUS_STYLE.get(agent.status, ("?", "muted"))
    name = one_line(agent.name, LABEL_WIDTH) or "agent"
    label = name if agent.id == name else f"{name}#{one_line(agent.id)}"
    parts = [one_line(agent.model, MODEL_WIDTH), _calls(agent), format_elapsed(elapsed(agent, now))]
    return Row("  " * depth, glyph, style, label, " · ".join(p for p in parts if p))


def panel_lines(agents, now: float) -> list | None:
    """The panel's lines for ``agents`` (``None`` to hide it)."""
    if not visible(agents):
        return None
    flat = flatten(agents)
    running = sum(a.status == "running" for a in agents)
    header = [("agents", "bold"), (f" · {running} running · {len(agents)} total", "dim")]
    lines: list = [header]
    if len(flat) > MAX_PANEL_ROWS:
        lines.append([(f"… {len(flat) - MAX_PANEL_ROWS} earlier", "muted")])
        flat = flat[-MAX_PANEL_ROWS:]
    for agent, depth in flat:
        row = make_row(agent, depth, now)
        lines.append([row.indent, (row.glyph, row.style), " ", (row.label, "bold"), (f"  {row.details}", "dim")])
    return lines


def tree_text(agents, now: float) -> str:
    """The tree as plain text, one row per agent."""
    return "\n".join(make_row(agent, depth, now).text() for agent, depth in flatten(agents))


def find_agent(agents, query: str):
    """The agent whose id is ``query`` or, failing that, the newest one named ``query``; ``None`` if none."""
    query = query.strip()
    for agent in agents:
        if agent.id == query:
            return agent
    named = [a for a in agents if a.name == query]
    return named[-1] if named else None


# --- what the agents did, from events ------------------------------------------------


def _call_line(event: dict) -> str:
    glyph = theme.ERROR if event.get("is_error") else theme.SUCCESS
    args = event.get("input") if isinstance(event.get("input"), dict) else {}
    arg = next((args[key] for key in CALL_ARGS if isinstance(args.get(key), str) and args[key].strip()), "")
    line = f"{glyph} {one_line(event.get('name', '?'), 40)} {one_line(arg, 60)}".rstrip()
    if event.get("is_error"):
        line += f" - {one_line(event.get('output', ''), 80)}"
    return line


class Monitor:
    """What ``ctx.agents()`` does not carry: each agent's recent tool calls and last reply, from the events.

    The agent's own transcript (``AgentResult.messages``) is only handed to whoever started it, so the monitor
    keeps what it can see."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[str, deque[str]] = {}
        self._replies: dict[str, str] = {}

    def tool_result(self, event: dict) -> None:
        agent_id = event.get("agent_id")
        if not isinstance(agent_id, str):
            return
        line = _call_line(event)
        with self._lock:
            calls = self._calls.get(agent_id)
            if calls is None:
                if len(self._calls) >= MAX_TRACKED:
                    self._calls.pop(next(iter(self._calls)))
                calls = self._calls[agent_id] = deque(maxlen=TRACE_LINES)
            calls.append(line)

    def agent_end(self, event: dict) -> None:
        agent_id, text = event.get("agent_id"), event.get("text")
        if isinstance(agent_id, str) and isinstance(text, str):
            with self._lock:
                if agent_id not in self._replies and len(self._replies) >= MAX_TRACKED:
                    self._replies.pop(next(iter(self._replies)))
                self._replies[agent_id] = text[-4000:]

    def clear(self, _event: dict | None = None) -> None:
        with self._lock:
            self._calls.clear()
            self._replies.clear()

    def trace(self, agent_id: str) -> tuple[list[str], str]:
        """``(recent tool call lines, last reply)`` of the agent."""
        with self._lock:
            return list(self._calls.get(agent_id, ())), self._replies.get(agent_id, "")


def format_detail(agent, now: float, calls: list[str] = (), reply: str = "") -> str:
    """Everything known about one agent, as plain text."""
    row = make_row(agent, 0, now)
    usage = agent.usage
    tokens = f"{usage.input_tokens:,} in · {usage.output_tokens:,} out"
    if usage.cache_read_tokens or usage.cache_write_tokens:
        tokens += f" · cache {usage.cache_read_tokens:,} read / {usage.cache_write_tokens:,} written"
    lines = [
        f"{row.glyph} {row.label} · {agent.status} · {format_elapsed(elapsed(agent, now))}",
        f"parent: {one_line(agent.parent_id) if agent.parent_id else '-'} · "
        f"model: {one_line(agent.model)} ({one_line(agent.provider)}) · {_calls(agent)}",
        f"tokens: {tokens}",
    ]
    if agent.error:
        lines.append(f"error: {block(agent.error, 600)}")
    lines += ["", "prompt:", *(f"  {line.rstrip()}" for line in block(agent.prompt, PROMPT_CHARS).splitlines())]
    if calls:
        lines += ["", "recent tool calls:", *(f"  {one_line(line, 200)}" for line in calls)]
    reply_lines = [line.rstrip() for line in block(reply, 4000).splitlines() if line.strip()][-REPLY_LINES:]
    if reply_lines:
        lines += ["", "last reply:", *(f"  {one_line(line, 200)}" for line in reply_lines)]
    return "\n".join(lines)


# --- terminal UI -----------------------------------------------------------------


class AgentsScreen(ModalScreen[None]):
    """The agent tree with the selected agent's detail; refreshes while open."""

    DEFAULT_CSS = """
    AgentsScreen { align: center middle; background: $modal-overlay; }
    AgentsScreen > Vertical {
        width: 90%; max-width: 120; height: auto; max-height: 90%;
        padding: 1 2; background: $surface;
    }
    AgentsScreen .title { width: 100%; text-style: bold; margin-bottom: 1; }
    AgentsScreen OptionList { height: auto; max-height: 10; background: $surface; }
    AgentsScreen OptionList:focus { background-tint: $foreground 0%; }
    AgentsScreen OptionList > .option-list--option-highlighted,
    AgentsScreen OptionList:focus > .option-list--option-highlighted {
        color: $foreground; background: $panel; text-style: bold;
    }
    AgentsScreen VerticalScroll { height: auto; max-height: 18; margin-top: 1; border-top: solid $border-muted; }
    AgentsScreen #detail { height: auto; padding: 1 0 0 0; }
    AgentsScreen .hint { color: $dim; margin-top: 1; }
    """

    BINDINGS = [
        Binding("escape,q", "close", "Close"),
        Binding("c", "cancel_agent", "Cancel agent"),
    ]

    def __init__(self, ctx, monitor: Monitor) -> None:
        super().__init__()
        self.ctx = ctx
        self.monitor = monitor
        self.selected: str | None = None
        self.ids: list[str] = []
        self.rows: list[str] = []
        self.shown = ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Agents", classes="title")
            yield OptionList(id="agents")
            with VerticalScroll():
                yield Static("", id="detail", markup=False)
            yield Label("↑↓ select · c interrupt the selected running agent · esc close", classes="hint")

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()
        self.refresh_agents()
        self.set_interval(0.5, self.refresh_agents)

    def _content(self, agent, depth: int, now: float) -> Content:
        row = make_row(agent, depth, now)
        return Content.assemble(row.indent, (row.glyph, f"${row.style}"), " ", row.label, f"  {row.details}")

    def refresh_agents(self) -> None:
        agents = self.ctx.agents()
        flat = flatten(agents)
        now = time.time()
        ids = [agent.id for agent, _ in flat]
        rows = [make_row(agent, depth, now).text() for agent, depth in flat]
        options = self.query_one(OptionList)
        if ids == self.ids:
            for index, ((agent, depth), text) in enumerate(zip(flat, rows)):
                if text != self.rows[index]:
                    options.replace_option_prompt_at_index(index, self._content(agent, depth, now))
        else:
            options.clear_options()
            options.add_options([Option(self._content(agent, depth, now), id=agent.id) for agent, depth in flat])
            if ids:
                index = ids.index(self.selected) if self.selected in ids else 0
                options.highlighted = index
                self.selected = ids[index]
        self.ids, self.rows = ids, rows
        self.show_detail(agents, now)

    def show_detail(self, agents, now: float) -> None:
        agent = next((a for a in agents if a.id == self.selected), None)
        text = "No agents yet." if agent is None else format_detail(agent, now, *self.monitor.trace(agent.id))
        if text != self.shown:
            self.shown = text
            self.query_one("#detail", Static).update(text)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        self.selected = event.option.id
        self.show_detail(self.ctx.agents(), time.time())

    def action_cancel_agent(self) -> None:
        agent = next((a for a in self.ctx.agents() if a.id == self.selected), None)
        if agent is None:
            return
        if agent.status != "running" or not self.ctx.cancel_agent(agent.id):
            self.app.notify(f"Agent {one_line(agent.id)} is not running ({agent.status}): nothing to interrupt.",
                            severity="warning", markup=False)
            return
        self.app.notify(f"Interrupting agent {one_line(agent.id)}.", markup=False)
        self.refresh_agents()

    def action_close(self) -> None:
        self.dismiss(None)


class AgentBrowser(Widget):
    """Invisible: opens the :class:`AgentsScreen` for ``/agents`` and blocks the command until it closes."""

    DEFAULT_CSS = "AgentBrowser { display: none; height: 0; }"

    def __init__(self, monitor: Monitor) -> None:
        super().__init__()
        self.monitor = monitor
        self._done: threading.Event | None = None

    def browse(self, ctx) -> None:
        """Called from the command's worker thread: show the screen and wait until it is closed."""
        done = threading.Event()
        self._done = done
        self.app.call_from_thread(self.app.push_screen, AgentsScreen(ctx, self.monitor), lambda _result: done.set())
        done.wait()
        self._done = None

    def on_unmount(self) -> None:  # e.g. extensions reloaded while open: release the waiting command
        if self._done is not None:
            self._done.set()


# --- registration ----------------------------------------------------------------------


def register(minimal) -> None:
    monitor = Monitor()

    def render(ctx):
        return panel_lines(ctx.agents(), time.time())

    def agents(args, ctx):
        found = ctx.agents()
        if not found:
            print("No agents yet: the main agent appears after the first turn, the others when a tool starts one.")
            return
        now = time.time()
        if args:
            agent = find_agent(found, args)
            if agent is None:
                raise ValueError(f"no agent {one_line(args, 40)!r}; run /agents to list them")
            print(format_detail(agent, now, *monitor.trace(agent.id)))
            return
        browser = ctx.widget(BROWSER)
        if browser is None:
            print(tree_text(found, now))
            print("(The interactive browser needs the terminal UI; /agents <id|name> prints one agent in full.)")
            return
        browser.browse(ctx)

    minimal.on("tool_result", monitor.tool_result)
    minimal.on("agent_end", monitor.agent_end)
    minimal.on("session_switch", monitor.clear)
    minimal.register_panel(PANEL, render, area="sidebar", interval=1.0)
    minimal.register_widget(BROWSER, lambda ctx: AgentBrowser(monitor), area="bottom")
    minimal.register_command(
        "agents", agents, description="show the agent tree; /agents opens a browser, /agents <id|name> prints one agent"
    )
