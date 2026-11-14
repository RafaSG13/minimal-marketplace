"""Plan board: a `plan` tool the model keeps updated, shown as a checklist with a progress bar."""

from minimal.api import theme

__version__ = "1.3"
__api__ = "2"

STATUSES = ("pending", "active", "done")
MAX_STEPS = 20
BAR_WIDTH = 24

SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
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


def _bar(fraction, width, color):
    """A gauge of ``width`` cells, filled to ``fraction`` with eighth-cell precision."""
    fraction = max(0.0, min(1.0, fraction))
    eighths = round(fraction * width * 8)
    full, part = divmod(eighths, 8)
    filled = "█" * full + ("▏▎▍▌▋▊▉"[part - 1] if part and full < width else "")
    return [(filled, color), ("░" * (width - len(filled)), "dim")]


def _validate(steps):
    """Raise ``ValueError`` unless ``steps`` is a list of 1–20 valid step dicts."""
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError(f"steps must be a list of 1-{MAX_STEPS} items")
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("each step must be an object with text and status")
        if not isinstance(step.get("text"), str) or not step["text"].strip():
            raise ValueError("each step needs a non-empty text")
        if step.get("status") not in STATUSES:
            raise ValueError(f"step status must be one of {', '.join(STATUSES)}")


def _plan(input, ctx):
    steps = input.get("steps")
    _validate(steps)
    done = sum(step["status"] == "done" for step in steps)
    return f"Plan updated: {done}/{len(steps)} done"


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
            return call.get("input", {}).get("steps")
    return None


class PlanBoard:
    def __init__(self):
        self.override = None

    def live(self, ctx, event):
        if event["kind"] == "start":
            self.override = None
        elif event["kind"] == "tool_result":
            call, result = event["call"], event["result"]
            if call.get("name") == "plan" and not result.get("is_error"):
                self.override = call.get("input", {}).get("steps")
        elif event["kind"] == "end":
            self.override = None

    def render(self, ctx):
        steps = self.override if self.override is not None else _last_plan(ctx.messages)
        try:
            _validate(steps)
        except ValueError:
            return None
        n = len(steps)
        done = sum(step["status"] == "done" for step in steps)
        lines = [
            [("PLAN", "bold muted"), (f"  {done}/{n}", "dim")],
            _bar(done / n, BAR_WIDTH, "success"),
        ]
        for step in steps:
            if step["status"] == "done":
                lines.append([(theme.SUCCESS, "success"), " ", (step["text"], "dim")])
            elif step["status"] == "active":
                lines.append([(f"◐ {step['text']}", "bold accent")])
            else:
                lines.append([(f"○ {step['text']}", "muted")])
        return lines


def register(minimal):
    minimal.register_tool(
        name="plan",
        description=(
            "Show the user your plan as a checklist. Pass the full list of steps every time, "
            "each with a status: pending, active or done."
        ),
        input_schema=SCHEMA,
        run=_plan,
        confirm=False,
    )
    minimal.append_system_prompt(
        "For tasks with three or more steps, call the plan tool with the full list of steps first, "
        "and again with the whole updated list whenever a step changes status; keep at most one step active."
    )
    panel = PlanBoard()
    minimal.register_panel("plan_board", panel.render, area="sidebar", live=panel.live)
