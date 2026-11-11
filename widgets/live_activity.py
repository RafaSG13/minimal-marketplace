"""Live activity: the tool running now, its elapsed time and the turn's call count, while the model works."""

import time

from textual.content import Content
from textual.widgets import Static

from minimal.api import theme

__version__ = "1.0"


def _label(call: dict) -> str:
    name = call.get("name", "")
    inp = call.get("input") or {}
    if name == "bash":
        lines = str(inp.get("command", "")).splitlines()
        return "$ " + (lines[0] if lines else "")[:40]
    if name in ("read", "write", "edit"):
        return f"{name} {inp.get('path', '')}"
    return name


class LiveActivity(Static):
    DEFAULT_CSS = "LiveActivity { height: 1; padding: 0 2; }"

    def __init__(self) -> None:
        super().__init__()
        self.state: dict | None = None

    def on_mount(self) -> None:
        self.display = False
        self.ticker = self.set_interval(0.25, self._tick, pause=True)

    def refresh_live(self, ctx, event: dict) -> None:
        kind, now = event.get("kind"), time.monotonic()
        if kind == "start":
            if not event.get("turn"):
                return
            self.state = {"t0": now, "calls": 0, "current": None, "since": None, "last": None}
            self.display = True
            self.ticker.resume()
        elif self.state is None:
            return
        elif kind == "tool_call":
            self.state.update(current=_label(event["call"]), since=now)
            self.state["calls"] += 1
        elif kind == "tool_result" and self.state["current"] is not None:
            ok = not event["result"].get("is_error")
            self.state["last"] = (self.state["current"], ok, now - self.state["since"])
            self.state["current"] = None
        self._tick()

    def refresh_state(self, ctx) -> None:
        self.ticker.pause()
        self.display = False

    def _tick(self) -> None:
        s = self.state
        if s is None:
            return
        now = time.monotonic()
        if s["current"] is not None:
            parts = [
                (theme.RUNNING, "$warning"),
                " ",
                (s["current"], "bold"),
                (f" · {now - s['since']:.1f}s", "$dim"),
            ]
        else:
            parts = [("⋯ thinking", "$muted")]
            if s["last"] is not None:
                label, ok, dur = s["last"]
                parts += [
                    " · last ",
                    (theme.SUCCESS if ok else theme.ERROR, "$success" if ok else "$error"),
                    f" {label} {dur:.1f}s",
                ]
        parts.append((f"  │ {s['calls']} calls · {now - s['t0']:.0f}s", "$dim"))
        self.update(Content.assemble(*parts))


def register(minimal):
    minimal.register_widget("live_activity", lambda ctx: LiveActivity(), area="bottom")
