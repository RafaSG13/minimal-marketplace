"""Context gauge: a one-line bar of how full the context window is, with the prompt-cache hit rate."""

from textual.content import Content
from textual.widgets import Static

__version__ = "1.2"
__api__ = "1"

DEFAULTS = {"limit": 200_000, "warn": 0.5, "crit": 0.8}
"""Context window size in tokens, and the fill fractions from which the bar turns warning / error."""

WIDTH = 24
"""Width of the bar in cells."""

EIGHTHS = "▏▎▍▌▋▊▉"


def _bar(fraction: float, width: int, color: str) -> Content:
    """A ``width``-cell gauge filled to ``fraction`` in ``color``, padded with dim ``░``."""
    eighths = round(max(0.0, min(fraction, 1.0)) * width * 8)
    full, part = divmod(eighths, 8)
    filled = "█" * full + (EIGHTHS[part - 1] if part else "")
    return Content.assemble((filled, color), ("░" * (width - len(filled)), "$dim"))


def _last_usage(messages: list) -> dict | None:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("usage"):
            return message["usage"]
    return None


class ContextGauge(Static):
    DEFAULT_CSS = "ContextGauge { height: 1; padding: 0 2; }"

    def refresh_state(self, ctx) -> None:
        self._draw(ctx)

    def refresh_live(self, ctx, event: dict) -> None:
        self._draw(ctx)

    def __init__(self, settings) -> None:
        super().__init__()
        self.settings = settings

    def _draw(self, ctx) -> None:
        tokens = ctx.context_tokens
        if tokens is None:
            self.display = False
            return
        limit, warn, crit = self.settings["limit"], self.settings["warn"], self.settings["crit"]
        frac = min(tokens / limit, 1)
        color = "$success" if frac < warn else "$warning" if frac < crit else "$error"
        parts = [
            ("ctx ", "$muted"),
            "▕",
            _bar(frac, WIDTH, color),
            "▏ ",
            f"{tokens / 1000:.1f}k/{limit // 1000}k {frac:.0%}",
        ]
        usage = _last_usage(ctx.messages)
        if usage:
            inp, read = usage.get("input_tokens") or 0, usage.get("cache_read_tokens") or 0
            if inp > 0 and read > 0:
                parts.append((f" · cache {read / inp:.0%}", "$dim"))
        self.update(Content.assemble(*parts))
        self.display = True


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS)
    minimal.register_widget("context_gauge", lambda ctx: ContextGauge(settings), area="bottom")
