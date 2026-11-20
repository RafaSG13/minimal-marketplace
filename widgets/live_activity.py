"""Live activity: the tool running now, its elapsed time and the turn's call count, while the model works."""

import threading
import time

from minimal.api import WIDGET_AREAS, theme

__version__ = "1.5"
__api__ = "2.3"
__tags__ = ["ui", "diagnostics"]

DEFAULTS = {
    "enabled": True,
    "title": "",
    "area": "bottom",
    "order": 0,
    "interval": 0.25,
    "cmd_chars": 40,
    "label_width": 60,
    "thinking_text": "⋯ thinking",
    "show_last": True,
    "show_counts": True,
    "idle": "reserve",
    "idle_text": "idle",
}

SCHEMA = {
    "enabled": {"description": "Show the activity line; false registers nothing."},
    "title": {"description": "Heading above the line (empty: no heading)."},
    "area": {"description": "Where the line goes by default (/ui move changes it).", "enum": list(WIDGET_AREAS)},
    "order": {"description": "Position among the widgets of the area (lower first)."},
    "interval": {
        "description": "Seconds between redraws while a turn runs, for the elapsed times (0: only on tool events).",
        "min": 0,
        "max": 10,
    },
    "cmd_chars": {"description": "Characters of a bash command shown.", "min": 5, "max": 200},
    "label_width": {"description": "Characters of the whole tool label (path, command) before it is cut.", "min": 10, "max": 300},
    "thinking_text": {"description": "Text while the model thinks and no tool runs."},
    "show_last": {"description": "While thinking, also show the last tool's result and duration."},
    "show_counts": {"description": "Show the turn's call count and elapsed time at the end of the line."},
    "idle": {
        "description": "Between turns: 'reserve' keeps one row (so the prompt does not jump), 'hide' removes it.",
        "enum": ["reserve", "hide"],
    },
    "idle_text": {"description": "Text of the reserved row between turns (empty: a blank row)."},
}


def clean(text, width=None):
    """``text`` as one printable line (control characters become spaces), cut with ``…`` beyond ``width``."""
    out = " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())
    return out if width is None or len(out) <= width else out[: max(width - 1, 0)].rstrip() + "…"


def _label(call: dict, cmd_chars: int = 40, width: int = 60) -> str:
    name = clean(call.get("name", ""), 40)
    inp = call.get("input") or {}
    if name == "bash":
        lines = str(inp.get("command", "")).splitlines()
        return clean("$ " + clean(lines[0] if lines else "", cmd_chars), width)
    if name in ("read", "write", "edit"):
        return clean(f"{name} {clean(inp.get('path', ''))}", width)
    return name


class LiveActivity:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.state: dict | None = None
        self.ctx = None
        self.active = threading.Event()
        self.stopped = threading.Event()
        self.thread: threading.Thread | None = None

    # -- redraw ticker: runs only while a turn does, and asks the UI for a redraw --

    def _tick(self) -> None:
        while True:
            self.active.wait()
            if self.stopped.is_set():
                return
            ctx = self.ctx
            if ctx is not None:
                ctx.invalidate()
            self.stopped.wait(self.settings["interval"])

    def _start_ticker(self) -> None:
        if self.settings["interval"] <= 0 or self.stopped.is_set():
            return
        if self.thread is None:
            self.thread = threading.Thread(target=self._tick, name="live-activity", daemon=True)
            self.thread.start()
        self.active.set()

    def dispose(self) -> None:
        self.stopped.set()
        self.active.set()
        thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        self.thread = None
        self.state = None

    def live(self, ctx, event: dict) -> None:
        kind, now = event.get("kind"), time.monotonic()
        self.ctx = ctx
        if kind == "end":
            self.state = None
            self.active.clear()
        elif kind == "start":
            if not event.get("turn"):
                return
            self.state = {"t0": now, "calls": 0, "current": None, "since": None, "last": None}
            self._start_ticker()
        elif self.state is None:
            return
        elif kind == "tool_call":
            s = self.settings
            self.state.update(current=_label(event["call"], s["cmd_chars"], s["label_width"]), since=now)
            self.state["calls"] += 1
        elif kind == "tool_result" and self.state["current"] is not None:
            ok = not event["result"].get("is_error")
            self.state["last"] = (self.state["current"], ok, now - self.state["since"])
            self.state["current"] = None

    def render(self, ctx):
        s = self.state
        settings = self.settings
        if s is None:
            if settings["idle"] == "hide":
                return None
            return [[(settings["idle_text"], "dim")]] if settings["idle_text"] else [""]
        now = time.monotonic()
        if s["current"] is not None:
            parts = [
                (theme.RUNNING, "warning"),
                " ",
                (s["current"], "bold"),
                (f" · {now - s['since']:.1f}s", "dim"),
            ]
        else:
            parts = [(settings["thinking_text"], "muted")]
            if settings["show_last"] and s["last"] is not None:
                label, ok, dur = s["last"]
                parts += [
                    " · last ",
                    (theme.SUCCESS if ok else theme.ERROR, "success" if ok else "error"),
                    f" {label} {dur:.1f}s",
                ]
        if settings["show_counts"]:
            parts.append((f"  │ {s['calls']} calls · {now - s['t0']:.0f}s", "dim"))
        return [parts]


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    panel = LiveActivity(settings)
    minimal.on_dispose(panel.dispose)
    title = settings["title"]
    minimal.register_panel(
        "live_activity",
        panel.render,
        area=settings["area"],
        live=panel.live,
        order=settings["order"],
        title=title or None,
        collapsible=bool(title),
    )
