"""Plan board: a `plan` tool the model keeps updated, shown as a checklist with a progress bar."""

import re

from minimal.api import WIDGET_AREAS, theme

__version__ = "1.5"
__api__ = "2.3"
__tags__ = ["workflow", "ui"]

STATUSES = ("pending", "active", "done")

DEFAULT_GLYPHS = {"done": theme.SUCCESS, "active": "◐", "pending": "○", "bar_empty": "░"}
"""Marks of a done, active and pending step, and the empty part of the progress bar."""

DEFAULT_STYLES = {"done": "dim", "done_mark": "success", "active": "bold accent", "pending": "muted", "bar": "success"}
"""Style of a done step's text and mark, of the active and pending steps, and of the filled progress bar."""

PROMPT_HINT = (
    "For tasks with three or more steps, call the plan tool with the full list of steps first, "
    "and again with the whole updated list whenever a step changes status; keep at most one step active."
)

DEFAULTS = {
    "enabled": True,
    "title": "PLAN",
    "area": "sidebar",
    "order": 0,
    "max_steps": 20,
    "bar_width": 24,
    "step_width": 32,
    "glyphs": DEFAULT_GLYPHS,
    "styles": DEFAULT_STYLES,
    "prompt_hint": True,
}

SCHEMA = {
    "enabled": {"description": "Offer the plan tool and show the panel; false registers nothing."},
    "title": {"description": "Heading above the panel (empty: no heading)."},
    "area": {"description": "Where the panel goes by default (/ui move changes it).", "enum": list(WIDGET_AREAS)},
    "order": {"description": "Position among the panels of the area (lower first)."},
    "max_steps": {"description": "Most steps a plan may have; the model is told when it sends more.", "min": 1, "max": 100},
    "bar_width": {"description": "Cells of the progress bar (0: no bar).", "min": 0, "max": 80},
    "step_width": {"description": "Columns of a step's text; longer steps are cut with an ellipsis.", "min": 8, "max": 200},
    "glyphs": {"description": "Glyphs by key: done, active, pending (step marks), bar_empty. Missing keys keep the default."},
    "styles": {
        "description": "Styles by key: done (text), done_mark, active, pending, bar. Names, $theme_var or #rrggbb, "
        "space-separated, e.g. 'bold $accent'."
    },
    "prompt_hint": {"description": "Add a sentence about the plan tool to the system prompt (costs a few tokens)."},
}

_STYLE_TOKEN = re.compile(
    r"^(?:\$[A-Za-z][\w-]*|#[0-9A-Fa-f]{6}|bold|italic|underline|reverse|foreground|accent|secondary|success|warning"
    r"|error|muted|dim|diff_added|diff_removed)$"
)


def merge(kind, defaults, user, check):
    """``defaults`` with the user's ``user`` overrides; ``ValueError`` naming ``kind`` for a bad key or value."""
    merged = dict(defaults)
    for key, value in user.items():
        if key not in defaults:
            raise ValueError(f"{kind}: unknown key {key!r} (known: {', '.join(defaults)})")
        if not isinstance(value, str) or not check(value):
            raise ValueError(f"{kind}.{key}: invalid value {value!r}")
        merged[key] = value
    return merged


def valid_style(value):
    return bool(value.split()) and all(_STYLE_TOKEN.match(token) for token in value.split())


def clean(text, width=None):
    """``text`` as one printable line (control characters become spaces), cut with ``…`` beyond ``width``."""
    out = " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())
    return out if width is None or len(out) <= width else out[: max(width - 1, 0)].rstrip() + "…"


def _schema(max_steps):
    return {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "maxItems": max_steps,
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "status": {"type": "string", "enum": list(STATUSES)},
                    },
                    "required": ["text", "status"],
                },
            }
        },
        "required": ["steps"],
    }


def _bar(fraction, width, color, empty):
    """A gauge of ``width`` cells, filled to ``fraction`` with eighth-cell precision."""
    fraction = max(0.0, min(1.0, fraction))
    eighths = round(fraction * width * 8)
    full, part = divmod(eighths, 8)
    filled = "█" * full + ("▏▎▍▌▋▊▉"[part - 1] if part and full < width else "")
    return [(filled, color), (empty * (width - len(filled)), "dim")]


def _validate(steps, max_steps):
    """Raise ``ValueError`` unless ``steps`` is a list of 1..``max_steps`` valid step dicts."""
    if not isinstance(steps, list) or not 1 <= len(steps) <= max_steps:
        raise ValueError(f"steps must be a list of 1-{max_steps} items")
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("each step must be an object with text and status")
        if not isinstance(step.get("text"), str) or not step["text"].strip():
            raise ValueError("each step needs a non-empty text")
        if step.get("status") not in STATUSES:
            raise ValueError(f"step status must be one of {', '.join(STATUSES)}")


def _last_plan(messages):
    """Steps of the last ``plan`` call whose result exists and is not an error."""
    results = {}
    calls = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "plan":
                calls.append(block)
            elif block.get("type") == "tool_result":
                results[block.get("tool_use_id")] = block
    for call in reversed(calls):
        result = results.get(call.get("id"))
        if result is not None and not result.get("is_error"):
            return (call.get("input") or {}).get("steps")
    return None


class PlanBoard:
    def __init__(self, settings):
        self.settings = settings
        self.glyphs = merge("glyphs", DEFAULT_GLYPHS, settings["glyphs"], lambda v: bool(v) and v.isprintable())
        self.styles = merge("styles", DEFAULT_STYLES, settings["styles"], valid_style)
        self.override = None
        self.version = 0
        self._key = None
        self._lines = None

    def live(self, ctx, event):
        before = self.override
        if event["kind"] == "start":
            self.override = None
        elif event["kind"] == "tool_result":
            call, result = event["call"], event["result"]
            if call.get("name") == "plan" and not result.get("is_error"):
                self.override = (call.get("input") or {}).get("steps")
        elif event["kind"] == "end":
            self.override = None
        if self.override is not before:
            self.version += 1

    def run(self, input, ctx):
        steps = input.get("steps")
        _validate(steps, self.settings["max_steps"])
        done = sum(step["status"] == "done" for step in steps)
        return f"Plan updated: {done}/{len(steps)} done"

    def render(self, ctx):
        messages = ctx.messages
        key = (
            id(messages),
            len(messages),
            id(messages[0]) if messages else 0,
            id(messages[-1]) if messages else 0,
            self.version,
        )
        if key != self._key:
            self._lines = self._build(messages)
            self._key = key
        return self._lines

    def _build(self, messages):
        s = self.settings
        steps = self.override if self.override is not None else _last_plan(messages)
        try:
            _validate(steps, s["max_steps"])
        except ValueError:
            return None
        n = len(steps)
        done = sum(step["status"] == "done" for step in steps)
        lines = [[(f"{done}/{n}", "dim")]]
        if s["bar_width"]:
            lines.append(_bar(done / n, s["bar_width"], self.styles["bar"], self.glyphs["bar_empty"]))
        room = s["step_width"]
        for step in steps:
            status = step["status"]
            text = clean(step["text"], room)
            if status == "done":
                lines.append([(self.glyphs["done"], self.styles["done_mark"]), " ", (text, self.styles["done"])])
            else:
                lines.append([(f"{self.glyphs[status]} {text}", self.styles[status])])
        return lines


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    panel = PlanBoard(settings)
    minimal.register_tool(
        name="plan",
        description=(
            "Show the user your plan as a checklist. Pass the full list of steps every time, "
            "each with a status: pending, active or done."
        ),
        input_schema=_schema(settings["max_steps"]),
        run=panel.run,
        confirm=False,
    )
    if settings["prompt_hint"]:
        minimal.append_system_prompt(PROMPT_HINT)
    minimal.register_panel(
        "plan_board",
        panel.render,
        area=settings["area"],
        live=panel.live,
        order=settings["order"],
        title=settings["title"] or None,
        collapsible=True,
    )
