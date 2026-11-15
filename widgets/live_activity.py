"""Live activity: the tool running now, its elapsed time and the turn's call count, while the model works."""

import time

from minimal.api import theme

__version__ = "1.3"
__api__ = "2"


def _label(call: dict) -> str:
    name = call.get("name", "")
    inp = call.get("input") or {}
    if name == "bash":
        lines = str(inp.get("command", "")).splitlines()
        return "$ " + (lines[0] if lines else "")[:40]
    if name in ("read", "write", "edit"):
        return f"{name} {inp.get('path', '')}"
    return name


class LiveActivity:
    def __init__(self) -> None:
        self.state: dict | None = None

    def live(self, ctx, event: dict) -> None:
        kind, now = event.get("kind"), time.monotonic()
        if kind == "end":
            self.state = None
        elif kind == "start":
            if not event.get("turn"):
                return
            self.state = {"t0": now, "calls": 0, "current": None, "since": None, "last": None}
        elif self.state is None:
            return
        elif kind == "tool_call":
            self.state.update(current=_label(event["call"]), since=now)
            self.state["calls"] += 1
        elif kind == "tool_result" and self.state["current"] is not None:
            ok = not event["result"].get("is_error")
            self.state["last"] = (self.state["current"], ok, now - self.state["since"])
            self.state["current"] = None

    def render(self, ctx):
        s = self.state
        if s is None:
            return None
        now = time.monotonic()
        if s["current"] is not None:
            parts = [
                (theme.RUNNING, "warning"),
                " ",
                (s["current"], "bold"),
                (f" · {now - s['since']:.1f}s", "dim"),
            ]
        else:
            parts = [("⋯ thinking", "muted")]
            if s["last"] is not None:
                label, ok, dur = s["last"]
                parts += [
                    " · last ",
                    (theme.SUCCESS if ok else theme.ERROR, "success" if ok else "error"),
                    f" {label} {dur:.1f}s",
                ]
        parts.append((f"  │ {s['calls']} calls · {now - s['t0']:.0f}s", "dim"))
        return [parts]


def register(minimal):
    panel = LiveActivity()
    minimal.register_panel("live_activity", panel.render, area="bottom", live=panel.live, interval=0.25)
