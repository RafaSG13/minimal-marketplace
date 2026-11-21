"""Delegate tool: runs a self-contained task in a fresh agent with its own history and reports how it went.

The delegate uses the current provider and model (``model`` picks another one), starts from an empty history and
may use every tool the current mode allows, or only the ``tools`` the model names. Only its final message returns
to the caller, which keeps long searches and investigations out of the main conversation. A delegate that fails,
runs out of turns (``max_turns``) or is interrupted comes back as a tool error that names the status and carries its
partial text. The user sees its tool calls (and the one running now next to the working indicator), answers the same
confirmations and can interrupt it. Delegates do not start delegates unless the ``max_depth`` setting allows it.

Settings (``/ext settings delegate``): ``max_depth`` (nesting), ``default_max_turns`` (0: the ``agent.max_turns``
setting) and ``max_turns_limit`` (the most the model may ask for), ``reasoning_effort`` (how hard a delegate thinks;
the model may pass its own per call; "" follows the session), ``progress`` (show what it is doing), ``parallel`` (true
makes several delegates in one reply run side by side and confines them to ``read_only`` tools, so nothing they do can
clash), ``default_role``, ``role_chars`` and ``note`` (the text added to its system prompt, ``{role}`` is replaced).

Install it with ``/ext``.
"""

import threading

__version__ = "2.0"
__api__ = "2.3"
__tags__ = ["agents"]

NAME = "delegate"
DEFAULT_ROLE = "delegate"
MAX_ROLE_CHARS = 60
MAX_TURNS_LIMIT = 50
EFFORTS = ("low", "medium", "high")
NOTE = (
    "You are a delegate started by another agent{role}. Do the task with the tools you have and finish with a "
    "concise report: the caller sees only your last message and cannot answer questions, so state any assumption "
    "you made instead of asking."
)

DEFAULTS = {
    "max_depth": 1,
    "default_max_turns": 0,
    "max_turns_limit": MAX_TURNS_LIMIT,
    "reasoning_effort": "",
    "progress": True,
    "parallel": False,
    "default_role": DEFAULT_ROLE,
    "role_chars": MAX_ROLE_CHARS,
    "note": NOTE,
}

SCHEMA = {
    "max_depth": {
        "description": "How many levels of delegates may nest (1: delegates cannot delegate).",
        "min": 1,
        "max": 10,
    },
    "default_max_turns": {
        "description": "Turn limit of a delegate when the model passes none (0: the agent.max_turns setting).",
        "min": 0,
        "max": 1000,
    },
    "max_turns_limit": {"description": "The most turns the model may ask a delegate for.", "min": 1, "max": 1000},
    "reasoning_effort": {
        "description": "How hard delegates think (\"\" follows the session's reasoning effort).",
        "enum": ["", *EFFORTS],
    },
    "progress": {"description": "Show the delegate's role and the tool it runs next to the working indicator."},
    "parallel": {
        "description": "Run delegates called in one reply side by side. They are then limited to read_only tools."
    },
    "default_role": {"description": "Name of a delegate whose role the model leaves out."},
    "role_chars": {"description": "Longest role label kept.", "min": 1, "max": 200},
    "note": {"description": "Text added to the delegate's system prompt; {role} becomes ' with the role: ...' or nothing."},
}


def _depth(ctx):
    """How many agents lie between ``ctx``'s agent and the user's turn (``"main"`` is 0)."""
    parents = {agent.id: agent.parent_id for agent in ctx.agents()}
    depth, agent_id = 0, ctx.agent_id
    while parents.get(agent_id) is not None and depth <= len(parents):
        depth, agent_id = depth + 1, parents[agent_id]
    return depth


def _clean_tools(tools, ctx):
    """The allow-list as a list of registered tool names; ``ValueError`` if it is malformed or names an unknown tool."""
    if not isinstance(tools, list) or not all(isinstance(name, str) for name in tools):
        raise ValueError("delegate: tools must be an array of tool names")
    unknown = sorted(set(tools) - ctx.tools.keys())
    if unknown:
        raise ValueError(f"delegate: unknown tool(s): {', '.join(unknown)}. Valid tools: {', '.join(ctx.tools)}")
    return list(dict.fromkeys(tools))


def _clean_max_turns(value, limit):
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= limit):
        raise ValueError(f"delegate: max_turns must be an integer from 1 to {limit} (setting max_turns_limit)")
    return value


def _failure(result):
    """The tool error text for a delegate that did not finish, with what it had written so far."""
    what = {"interrupted": "was interrupted before it finished", "max_turns": "ran out of turns"}.get(
        result.status, "failed"
    )
    message = f"The delegate {what} (status: {result.status}{': ' + result.error if result.error else ''})."
    if result.status == "max_turns":
        message += " Split the task or raise max_turns."
    if result.text.strip():
        message += f"\nIts last message:\n{result.text.strip()}"
    return message


def _read_only_names(ctx, exclude=()):
    """The registered tools that are ``read_only``, in registration order, without ``exclude``."""
    return [name for name, tool in ctx.tools.items() if tool.read_only and name not in exclude]


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    running = threading.local()  # ``role`` and ``effort`` of the delegate running on this thread; unset when none runs

    @minimal.on("before_request")
    def delegate_effort(event):
        effort = getattr(running, "effort", None)
        if event["nested"] and effort:
            return {"options": {"reasoning_effort": effort}}

    @minimal.on("tool_call")
    def delegate_progress(event):
        role = getattr(running, "role", None)
        if role and settings["progress"]:
            event["ctx"].progress(f"{role}: {event['name']}")

    def run_delegate(input, ctx):
        task = str(input.get("task", "")).strip()
        if not task:
            raise ValueError("delegate: task must be a non-empty string with everything the delegate needs")
        default_role = settings["default_role"]
        role = " ".join(str(input.get("role") or "").split())[: settings["role_chars"]] or default_role
        model = input.get("model") or None
        if model is not None and not isinstance(model, str):
            raise ValueError("delegate: model must be a model name")
        max_turns = _clean_max_turns(input.get("max_turns"), settings["max_turns_limit"])
        if max_turns is None and settings["default_max_turns"]:
            max_turns = settings["default_max_turns"]
        effort = input.get("reasoning_effort") or settings["reasoning_effort"] or None
        if effort is not None and effort not in EFFORTS:
            raise ValueError(f"delegate: reasoning_effort must be one of: {', '.join(EFFORTS)}")
        max_depth = settings["max_depth"]
        depth = _depth(ctx)
        if depth >= max_depth:
            raise ValueError(
                f"delegate: delegates may nest at most {max_depth} level(s) deep (setting max_depth); "
                "do this task yourself with your own tools"
            )
        # The delegate may delegate again only while its own depth stays below max_depth.
        stop_nesting = depth + 1 >= max_depth
        limits = {}
        if input.get("tools") is not None:
            allowed = _clean_tools(input["tools"], ctx)
            limits["tools"] = [name for name in allowed if not (stop_nesting and name == NAME)]
        elif settings["parallel"]:
            limits["tools"] = _read_only_names(ctx, {NAME} if stop_nesting else ())
        elif stop_nesting:
            limits["exclude_tools"] = {NAME}
        if settings["parallel"]:
            writers = [name for name in limits["tools"] if not ctx.tools[name].read_only]
            if writers:
                raise ValueError(
                    f"delegate: the parallel setting limits delegates to read_only tools; {', '.join(writers)} "
                    "is not one. Drop it from tools, or set parallel to false to allow it"
                )
        previous = getattr(running, "role", None), getattr(running, "effort", None)
        running.role, running.effort = role, effort
        if settings["progress"]:
            ctx.progress(f"{role}: started")
        try:
            result = ctx.run_agent_result(
                task,
                name=role,
                system_note=settings["note"].replace(
                    "{role}", "" if role == default_role else f" with the role: {role}"
                ),
                model=model,
                max_turns=max_turns,
                **limits,
            )
        finally:
            running.role, running.effort = previous
            if settings["progress"]:
                ctx.progress(None)
        if result.status != "done":
            raise RuntimeError(_failure(result))
        return result.text or "(the delegate returned no text)"

    limit = settings["max_turns_limit"]
    minimal.register_tool(
        name=NAME,
        run=run_delegate,
        read_only=settings["parallel"],
        description=(
            "Hand a self-contained task to a delegate: a fresh agent with an empty history that works alone and "
            "returns only its final message. Use it for research and investigations whose intermediate output is not "
            "worth keeping in this conversation (searching a codebase, reading many files, comparing options). "
            "The delegate sees nothing of this conversation, so the task must contain everything it needs: the "
            "goal, the paths or names involved, constraints, and the form of the report you want. It cannot ask "
            "you questions. Do not delegate what you can do in a call or two. Pass tools to limit what it may use "
            "(for example only read-only tools), and max_turns to bound its work. If it fails, runs out of turns or "
            "is interrupted you get an error with its partial text."
            + (
                " Delegates here are limited to read-only tools, so call several in one reply to run them side by side."
                if settings["parallel"]
                else ""
            )
        ),
        input_schema={
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Complete instructions for the delegate"},
                "role": {
                    "type": "string",
                    "description": "A short label for the delegate, e.g. 'reviewer'; shown as its name",
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The only tools the delegate may use (default: all the current mode allows)",
                },
                "model": {"type": "string", "description": "Model for the delegate (default: the current one)"},
                "max_turns": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": limit,
                    "description": f"Most model requests the delegate may make (1-{limit}, default "
                    + (str(settings["default_max_turns"]) if settings["default_max_turns"] else "the session's limit")
                    + ")",
                },
                "reasoning_effort": {
                    "type": "string",
                    "enum": list(EFFORTS),
                    "description": "How hard the delegate thinks (default: the session's)",
                },
            },
            "required": ["task"],
        },
    )
