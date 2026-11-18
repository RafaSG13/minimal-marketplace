"""Plan and build modes with a plan gate: investigate read-only first, then approve and execute.

Adds two modes: ``plan`` (read-only: the model can read, search and ask you, but not write, edit or run commands, and
ends with a numbered plan) and ``build`` (no restriction: the model executes the approved plan). Cycle them with
Shift+Tab or ``/mode``. Switching from ``plan`` to ``build`` after the model proposed a plan asks you to approve it;
yes sends "The plan is approved. Execute it.", no returns to ``plan``. The ``default`` setting
(``extensions.settings.modes``) picks the mode to start in: ``"plan"``, ``"build"`` or ``""`` for none (default).

Install it with ``/ext``.
"""

__version__ = "1.1"
__api__ = "2.2"
__tags__ = ["workflow", "safety"]

import re
import threading

PLAN_NOTE = (
    "You are in plan mode. Investigate with the read-only tools you have (read, grep, glob) and ask the user when a "
    "decision is theirs; do not change anything: writing, editing and running commands are blocked until the user "
    "switches to build mode. When you understand the task, end your reply with a concise numbered plan (1., 2., ...) "
    "naming the files you would change and how, so the user can approve it."
)
BUILD_NOTE = (
    "You are in build mode. If a plan was approved earlier in this conversation, execute it step by step and verify "
    "the result; say so if you must deviate from it."
)
APPROVED = "The plan is approved. Execute it."
NO_MODE = ("", "off", "none")
CHOICES = ("plan", "build", *NO_MODE)
NUMBERED_STEP = re.compile(r"^\s{0,3}\d+[.)]\s+\S", re.MULTILINE)
MIN_STEPS = 2


def _last_assistant_text(messages):
    """The text of the last assistant message of ``messages`` ("" if there is none)."""
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        return "\n".join(
            block.get("text", "") for block in content or [] if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def looks_like_plan(text):
    """Whether ``text`` has a numbered list of at least ``MIN_STEPS`` steps."""
    return len(NUMBERED_STEP.findall(text)) >= MIN_STEPS


def register(minimal):
    settings = minimal.declare_settings({"default": ""})
    gate_open = threading.Lock()

    minimal.register_mode(
        "plan",
        description="investigate and propose a numbered plan; nothing is changed",
        read_only=True,
        system_note=PLAN_NOTE,
    )
    minimal.register_mode(
        "build",
        description="execute the approved plan with every tool",
        system_note=BUILD_NOTE,
    )

    def gate(ctx, plan_text):
        """Ask whether to approve the plan; runs in a thread of its own, holding ``gate_open``."""
        try:
            if ctx.ui.ask(f"Approve this plan and start building?\n\n{plan_text.strip()[:1500]}"):
                if ctx.mode == "build":
                    ctx.queue_user_message(APPROVED)
            elif ctx.mode == "build":
                ctx.set_mode("plan")
                ctx.notify("Plan not approved: back in plan mode.", "info")
        except Exception as exc:
            ctx.notify(f"modes: the plan gate failed ({exc}); switch modes with /mode.", "warning")
        finally:
            gate_open.release()

    @minimal.on("mode_change")
    def on_mode_change(event):
        # Only plan -> build asks. The denial's set_mode("plan") fires build -> plan, which does nothing,
        # and gate_open stops a second gate while one is waiting for an answer.
        if event["old"] != "plan" or event["new"] != "build":
            return
        try:
            ctx = event["ctx"]
            plan_text = _last_assistant_text(ctx.messages)
            if not looks_like_plan(plan_text) or not gate_open.acquire(blocking=False):
                return
            try:
                # Shift+Tab fires this on the UI thread, where a question would block the interface: ask elsewhere.
                threading.Thread(target=gate, args=(ctx, plan_text), name="modes-gate", daemon=True).start()
            except BaseException:
                gate_open.release()
                raise
        except Exception as exc:
            event["ctx"].notify(f"modes: the plan gate failed ({exc}); switch modes with /mode.", "warning")

    @minimal.on("session_start")
    def start(event):
        ctx = event["ctx"]
        wanted = settings["default"].strip().lower()
        if wanted not in CHOICES:
            ctx.notify(
                f"modes: setting 'default' is {settings['default']!r}; use 'plan', 'build' or '' for no mode "
                "under extensions.settings.modes in settings.json. Starting with no mode.",
                "warning",
            )
        elif wanted not in NO_MODE and ctx.mode is None:
            ctx.set_mode(wanted)
