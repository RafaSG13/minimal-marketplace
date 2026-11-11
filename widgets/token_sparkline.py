"""Token sparkline: input tokens per request as a sparkline, session totals and an estimated cost."""

from textual.content import Content
from textual.widgets import Static

__version__ = "1.1"
__requires__ = ">=0.2"

# Model-name prefix -> USD per million tokens (input, output, cache_read, cache_write).
# Checked 2026-11-10 against platform.claude.com/docs/en/about-claude/pricing,
# developers.openai.com/api/docs/pricing and ai.google.dev/gemini-api/docs/pricing.
# Anthropic cache writes use the 5-minute rate; OpenAI and Gemini list no cache-write rate for
# these models, so cache writes cost the input price. OpenAI prices are for <272K-token prompts.
# Gemini 3.8 Flash prices are valid through 2026-12-31 (they double on 2027-01-01).
# The longest prefix that matches the model name wins.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-8": (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-7": (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-6": (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-5": (5.0, 25.0, 0.50, 6.25),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10, 2.50),
    "claude-sonnet-5": (2.0, 10.0, 0.20, 2.50),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30, 3.75),
    "claude-sonnet-4-5": (3.0, 15.0, 0.30, 3.75),
    "claude-haiku-4-5": (1.0, 5.0, 0.10, 1.25),
    "gpt-5.5": (5.0, 30.0, 0.50, 5.0),
    "gpt-5.5-pro": (30.0, 180.0, 30.0, 30.0),
    "gpt-5.4": (2.50, 15.0, 0.25, 2.50),
    "gpt-5.4-pro": (30.0, 180.0, 30.0, 30.0),
    "gpt-5.4-mini": (0.75, 4.50, 0.075, 0.75),
    "gpt-5.4-nano": (0.20, 1.25, 0.02, 0.20),
    "gemini-3.8-flash": (0.75, 3.75, 0.075, 0.75),
}

SPARK = "▁▂▃▄▅▆▇█"
SPARK_LEN = 28


def _usages(messages: list) -> list[dict]:
    """The ``usage`` of each assistant message, in order."""
    return [
        m["usage"]
        for m in messages
        if isinstance(m, dict) and m.get("role") == "assistant" and m.get("usage")
    ]


def _tokens(n: int) -> str:
    """A token count in at most five columns: ``950``, ``12.3k``, ``310k``, ``1.2M``."""
    if n < 1000:
        return str(n)
    if n < 100_000:
        return f"{n / 1000:.1f}k"
    if n < 1_000_000:
        return f"{n // 1000}k"
    return f"{n / 1e6:.1f}M"


def _cost(ctx, prices) -> float | None:
    """Estimated USD cost of the session so far, or None if the model has no known price."""
    model = ctx.model or ""
    keys = [k for k in prices if model.startswith(k)]
    if not keys:
        return None
    p_in, p_out, p_cr, p_cw = prices[max(keys, key=len)]
    total = 0.0
    for u in _usages(ctx.messages):
        inp = u.get("input_tokens") or 0
        cr = u.get("cache_read_tokens") or 0
        cw = u.get("cache_write_tokens") or 0
        out = u.get("output_tokens") or 0
        total += (inp - cr - cw) * p_in + cr * p_cr + cw * p_cw + out * p_out
    return total / 1e6


class TokenSparkline(Static):
    DEFAULT_CSS = "TokenSparkline { padding: 0 1; margin-bottom: 1; height: auto; }"

    def __init__(self, prices) -> None:
        super().__init__()
        self.prices = prices

    def refresh_state(self, ctx) -> None:
        self._draw(ctx)

    def refresh_live(self, ctx, event: dict) -> None:
        self._draw(ctx)

    def _draw(self, ctx) -> None:
        usages = _usages(ctx.messages)
        if not usages:
            self.display = False
            return
        values = [u.get("input_tokens") or 0 for u in usages][-SPARK_LEN:]
        top = max(values) or 1
        spark = "".join(SPARK[min(7, v * 8 // top)] for v in values)
        total_in = sum(u.get("input_tokens") or 0 for u in usages)
        total_out = sum(u.get("output_tokens") or 0 for u in usages)
        total_read = sum(u.get("cache_read_tokens") or 0 for u in usages)
        cache = total_read / total_in if total_in else 0
        lines = [
            Content.assemble(("TOKENS", "bold $muted"), (f"  {len(usages)} requests", "$dim")),
            Content.styled(spark, "$accent"),
            Content.styled(
                f"in {_tokens(total_in)} · out {_tokens(total_out)} · cache {cache:.0%}", "$muted"
            ),
        ]
        cost = _cost(ctx, self.prices)
        if cost is not None:
            lines.append(Content(f"≈ ${cost:.2f}"))
        self.update(Content("\n").join(lines))
        self.display = True


def register(minimal):
    settings = minimal.declare_settings({"prices": PRICES})
    prices = {**PRICES, **settings["prices"]}
    minimal.register_widget("token_sparkline", lambda ctx: TokenSparkline(prices), area="sidebar")
    minimal.register_status(
        "cost",
        lambda ctx: f"≈${c:.2f}" if (c := _cost(ctx, prices)) is not None else None,
        side="right",
    )
