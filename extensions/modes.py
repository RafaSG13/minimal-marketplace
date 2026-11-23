"""Plan and build modes with a plan gate: investigate read-only first, then approve and execute.

Adds two modes: ``plan`` (read-only: the model can read, search and ask you, but not write, edit or run commands, and
ends with a numbered plan) and ``build`` (no restriction: the model executes the approved plan). Cycle them with
Shift+Tab or ``/mode``. Switching from ``plan`` to ``build`` after the model proposed a plan asks you to approve it;
yes sends "The plan is approved. Execute it.", no returns to ``plan``. Every text, the gate and the plan detection are
settings (``/ext settings modes``): ``default`` picks the mode to start in (``"plan"``, ``"build"`` or ``""`` for none),
``approve_gate`` turns the question off, ``plan_note`` and ``build_note`` are the system-prompt notes of the two modes,
``approve_message`` is what yes sends, ``min_steps`` how many numbered steps make a reply a plan and ``preview_chars``
how much of the plan the question shows.

Install it with ``/ext``.
"""

__version__ = "1.3"
__api__ = "2.3"
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
PLAN_BLOCKED = ("ast_grep_rewrite", "docker_compose")
"""Tools that change things but decide per call whether to ask (``confirm`` is a function), which ``read_only`` does
not block, so plan mode names them (a mode may name tools that are not installed)."""
MIN_STEPS = 2
PREVIEW_CHARS = 1500


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


def looks_like_plan(text, min_steps=MIN_STEPS):
    """Whether ``text`` has a numbered list of at least ``min_steps`` steps."""
    return len(NUMBERED_STEP.findall(text)) >= min_steps


def register(minimal):
    settings = minimal.declare_settings(
        {
            "default": "",
            "approve_gate": True,
            "plan_note": PLAN_NOTE,
            "build_note": BUILD_NOTE,
            "approve_message": APPROVED,
            "min_steps": MIN_STEPS,
            "preview_chars": PREVIEW_CHARS,
        },
        {
            "default": {
                "description": "Mode to start in; \"\" (or off/none) starts with no mode.",
                "enum": list(CHOICES),
            },
            "approve_gate": {
                "description": "Ask to approve the plan when you switch from plan to build. False switches without asking."
            },
            "plan_note": {"description": "System-prompt note while in plan mode (what the model may do, how to end its reply)."},
            "build_note": {"description": "System-prompt note while in build mode."},
            "approve_message": {"description": "Message sent to the model when you approve the plan at the gate."},
            "min_steps": {
                "description": "Numbered steps (1., 2., ...) the last reply needs to count as a plan and open the gate.",
                "min": 1,
                "max": 50,
            },
            "preview_chars": {
                "description": "Characters of the plan shown in the approval question.",
                "min": 100,
                "max": 20000,
            },
        },
    )
    gate_open = threading.Lock()

    minimal.register_mode(
        "plan",
        description="investigate and propose a numbered plan; nothing is changed",
        read_only=True,
        exclude_tools=PLAN_BLOCKED,
        system_note=settings["plan_note"],
    )
    minimal.register_mode(
        "build",
        description="execute the approved plan with every tool",
        system_note=settings["build_note"],
    )

    def gate(ctx, plan_text):
        """Ask whether to approve the plan; runs in a thread of its own, holding ``gate_open``."""
        try:
            if ctx.ui.ask(f"Approve this plan and start building?\n\n{plan_text.strip()[: settings['preview_chars']]}"):
                if ctx.mode == "build" and settings["approve_message"]:
                    ctx.queue_user_message(settings["approve_message"])
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
        if not settings["approve_gate"] or event["old"] != "plan" or event["new"] != "build":
            return
        try:
            ctx = event["ctx"]
            plan_text = _last_assistant_text(ctx.messages)
            if not looks_like_plan(plan_text, settings["min_steps"]) or not gate_open.acquire(blocking=False):
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
        wanted = settings["default"]
        if wanted not in NO_MODE and ctx.mode is None:
            ctx.set_mode(wanted)
