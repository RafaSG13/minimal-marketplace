"""Token sparkline: input tokens per request as a sparkline, session totals and an estimated cost."""

from __future__ import annotations

from collections import deque

from minimal.api import styled_line

__version__ = "2.0"
__api__ = "2.3"
__tags__ = ["context", "diagnostics", "ui"]

# Model-name prefix -> USD per million tokens (input, output, cache_read, cache_write).
# Checked 2026-11-10 against platform.claude.com/docs/en/about-claude/pricing,
# developers.openai.com/api/docs/pricing and ai.google.dev/gemini-api/docs/pricing.
# Anthropic cache writes use the 5-minute rate; OpenAI and Gemini list no cache-write rate for
# these models, so cache writes cost the input price. OpenAI prices are for <272K-token prompts.
# Gemini 3.8 Flash prices are valid through 2026-12-31 (they double on 2027-01-01).
# The longest prefix that matches the model name wins. The `prices` setting adds to or overrides these rows.
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

GLYPHS = {"spark": "▁▂▃▄▅▆▇█"}
"""The sparkline's levels, lowest first (any 2 to 16 characters)."""

STYLES = {"requests": "dim", "spark": "accent", "totals": "muted", "cost": "", "status": ""}
"""Style of each part; ``status`` is the cost in the status line."""

MAX_SPARK = 60
"""Most requests kept for the sparkline (the ``spark_len`` setting's top)."""

DEFAULTS = {
    "enabled": True,
    "title": "TOKENS",
    "area": "sidebar",
    "order": 0,
    "spark_len": 28,
    "show_spark": True,
    "show_totals": True,
    "show_cache": True,
    "show_cost": True,
    "cost_status": True,
    "cost_side": "right",
    "cost_order": 0,
    "cost_format": "≈ ${cost:.2f}",
    "status_format": "≈${cost:.2f}",
    "prices": {},
    "glyphs": {},
    "styles": {},
}

SCHEMA = {
    "enabled": {"description": "Show the panel and the cost segment; false registers nothing."},
    "title": {"description": "The heading above the panel; empty for none (collapsible by click when set)."},
    "area": {
        "description": "Where the panel sits (the user's /ui move overrides it).",
        "enum": ["top", "bottom", "sidebar", "left", "footer"],
    },
    "order": {"description": "Position among the area's panels and widgets, lower first."},
    "spark_len": {"description": "Requests drawn in the sparkline.", "min": 2, "max": MAX_SPARK},
    "show_spark": {"description": "Draw the sparkline of input tokens per request."},
    "show_totals": {"description": "Draw the session's input, output and cache totals."},
    "show_cache": {"description": "Include the prompt-cache hit rate in the totals."},
    "show_cost": {"description": "Draw the estimated cost under the totals when the model has a price."},
    "cost_status": {
        "description": "Also show the estimated cost as the 'cost' status segment (place it with /ui or cost_side); "
        "the statusline_kit item does not draw a cost of its own."
    },
    "cost_side": {"description": "Which side of the status line the cost goes.", "enum": ["left", "right"]},
    "cost_order": {"description": "Position among that side's status segments, lower first."},
    "cost_format": {
        "description": "The panel's cost line: a Python format string using {cost} (USD, or your price currency), "
        "e.g. \"{cost:.3f} EUR\"."
    },
    "status_format": {"description": "The status segment's text: a format string using {cost}."},
    "prices": {
        "description": "Prices per million tokens by model-name prefix, added to the built-in table (PRICES in the "
        "file): "
        "{\"my-model\": [input, output]} or [input, output, cache_read, cache_write]. Malformed entries are "
        "reported and ignored."
    },
    "glyphs": {"description": "Override the sparkline's levels: {\"spark\": \"_.-=#\"}."},
    "styles": {"description": "Override a part's style: " + ", ".join(STYLES) + "."},
}
"""Description, enum and range of each setting (``/ext settings widgets/token_sparkline``)."""


def parse_prices(raw: dict) -> tuple[dict[str, tuple[float, float, float, float]], list[str]]:
    """``(table, problems)``: the well-formed entries of the user's ``raw`` prices and a sentence per malformed one.

    An entry is two numbers (input, output; cache reads and writes then cost the input price) or four
    (input, output, cache read, cache write), none negative.
    """
    table: dict[str, tuple[float, float, float, float]] = {}
    problems = []
    for prefix, value in raw.items():
        numbers = isinstance(value, (list, tuple)) and all(
            isinstance(n, (int, float)) and not isinstance(n, bool) and n >= 0 for n in value
        )
        if not (isinstance(prefix, str) and prefix and numbers and len(value) in (2, 4)):
            problems.append(
                f"prices[{prefix!r}] = {value!r} is not [input, output] or [input, output, cache_read, cache_write]"
            )
        elif len(value) == 2:
            table[prefix] = (float(value[0]), float(value[1]), float(value[0]), float(value[0]))
        else:
            table[prefix] = (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    return table, problems


def merged(name: str, given: dict, defaults: dict, problems: list[str], style: bool = False) -> dict:
    """``defaults`` with the entries of ``given`` laid over them; each bad entry is added to ``problems``."""
    result = dict(defaults)
    for key, value in given.items():
        if key not in defaults:
            problems.append(f"'{name}' has no entry {key!r} (known: {', '.join(defaults)})")
        elif not isinstance(value, str):
            problems.append(f"'{name}.{key}' must be text, not {value!r}")
        elif style:
            try:
                styled_line((" ", value))
            except ValueError as error:
                problems.append(f"'{name}.{key}': {error}")
            else:
                result[key] = value
        else:
            result[key] = value
    return result


def check_settings(settings) -> tuple[list[str], dict, dict]:
    """``(problems, glyphs, styles)``: one sentence per problem with the fix, and the dicts over the defaults.

    Malformed ``prices`` are not among the problems: they are skipped and reported at the first draw.
    """
    problems: list[str] = []
    glyphs = merged("glyphs", settings["glyphs"], GLYPHS, problems)
    styles = merged("styles", settings["styles"], STYLES, problems, style=True)
    if not 2 <= len(glyphs["spark"]) <= 16:
        problems.append("'glyphs.spark' needs 2 to 16 characters, the levels from lowest to highest")
    for name in ("cost_format", "status_format"):
        try:
            settings[name].format(cost=1.0)
        except (KeyError, IndexError, ValueError, AttributeError):
            problems.append(f"'{name}' must be a format string using only {{cost}}, e.g. \"≈ ${{cost:.2f}}\"")
    return problems, glyphs, styles


def format_tokens(count: int) -> str:
    """A token count in at most five columns: ``950``, ``12.3k``, ``310k``, ``1.2M``."""
    if count < 1000:
        return str(count)
    if count < 100_000:
        return f"{count / 1000:.1f}k"
    if count < 1_000_000:
        return f"{count // 1000}k"
    return f"{count / 1e6:.1f}M"


class Digest:
    """What the session's replies spent, kept up to date by reading only the messages added since the last look.

    Redraws are cheap however long the session grows. A shorter list, or one whose last-seen message is not the
    same object any more (``/new``, a rewind), is read again from the start.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.count = 0
        self.last: object = None
        self.requests = 0
        self.input = self.output = self.cache_read = self.cache_write = 0
        self.recent: deque[int] = deque(maxlen=MAX_SPARK)

    def update(self, messages: list) -> "Digest":
        if self.count > len(messages) or (self.count and messages[self.count - 1] is not self.last):
            self.reset()
        for message in messages[self.count :]:
            usage = message.get("usage") if isinstance(message, dict) and message.get("role") == "assistant" else None
            if usage:
                self.requests += 1
                inp = usage.get("input_tokens") or 0
                self.input += inp
                self.output += usage.get("output_tokens") or 0
                self.cache_read += usage.get("cache_read_tokens") or 0
                self.cache_write += usage.get("cache_write_tokens") or 0
                self.recent.append(inp)
        self.count = len(messages)
        self.last = messages[-1] if messages else None
        return self

    def cost(self, model: str | None, prices: dict) -> float | None:
        """Estimated cost of everything read so far at ``model``'s price, or None if the model has no known price."""
        keys = [k for k in prices if (model or "").startswith(k)]
        if not keys:
            return None
        p_in, p_out, p_cr, p_cw = prices[max(keys, key=len)]
        fresh = self.input - self.cache_read - self.cache_write
        return (fresh * p_in + self.cache_read * p_cr + self.cache_write * p_cw + self.output * p_out) / 1e6


def spark_line(values: list[int], levels: str) -> str:
    """One ``levels`` character per value, scaled to the largest."""
    top = max(values) or 1
    return "".join(levels[min(len(levels) - 1, v * len(levels) // top)] for v in values)


def build_lines(digest: Digest, cost: float | None, settings, glyphs: dict, styles: dict) -> list | None:
    """The panel's lines, or None before the first reply."""
    if not digest.requests:
        return None
    lines: list = [[(f"{digest.requests} requests", styles["requests"])]]
    if settings["show_spark"]:
        lines.append([(spark_line(list(digest.recent)[-settings["spark_len"] :], glyphs["spark"]), styles["spark"])])
    if settings["show_totals"]:
        text = f"in {format_tokens(digest.input)} · out {format_tokens(digest.output)}"
        if settings["show_cache"]:
            text += f" · cache {digest.cache_read / digest.input if digest.input else 0:.0%}"
        lines.append([(text, styles["totals"])])
    if settings["show_cost"] and cost is not None:
        lines.append([(settings["cost_format"].format(cost=cost), styles["cost"])])
    return lines


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    problems, glyphs, styles = check_settings(settings)
    if problems:
        raise ValueError(f"token_sparkline settings: {'; '.join(problems)}")
    user_prices, price_problems = parse_prices(settings["prices"])
    prices = {**PRICES, **user_prices}
    digest = Digest()
    reported = []

    def report(ctx) -> None:
        """Tell the user once about malformed ``prices`` (the first draw has a ``ctx``; ``register`` has none)."""
        if price_problems and not reported:
            reported.append(True)
            ctx.notify("token_sparkline: ignoring " + "; ".join(price_problems), "warning")

    def render(ctx):
        report(ctx)
        digest.update(ctx.messages)
        return build_lines(digest, digest.cost(ctx.model, prices), settings, glyphs, styles)

    minimal.register_panel(
        "token_sparkline",
        render,
        area=settings["area"],
        order=settings["order"],
        title=settings["title"] or None,
        collapsible=True,
    )
    if settings["cost_status"]:

        def status(ctx):
            report(ctx)
            cost = digest.update(ctx.messages).cost(ctx.model, prices)
            return None if cost is None else (settings["status_format"].format(cost=cost), styles["status"])

        minimal.register_status("cost", status, side=settings["cost_side"], order=settings["cost_order"])
