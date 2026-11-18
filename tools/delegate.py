"""Delegate tool: runs a self-contained task in a fresh agent with its own history and reports how it went.

The delegate uses the current provider and model (``model`` picks another one), starts from an empty history and
may use every tool the current mode allows, or only the ``tools`` the model names. Only its final message returns
to the caller, which keeps long searches and investigations out of the main conversation. A delegate that fails,
runs out of turns (``max_turns``) or is interrupted comes back as a tool error that names the status and carries its
partial text. The user sees its tool calls, answers the same confirmations and can interrupt it. It supersedes
``tools/subagent`` on minimal with API 2.2 (the agent has a name and an id, and reports its status); delegates do
not start delegates unless the ``max_depth`` setting allows it.

Install it with ``/ext``.
"""

__version__ = "1.1"
__api__ = "2.2"
__tags__ = ["agents"]

NAME = "delegate"
DEFAULT_ROLE = "delegate"
MAX_ROLE_CHARS = 60
MAX_TURNS_LIMIT = 50
NOTE = (
    "You are a delegate started by another agent{role}. Do the task with the tools you have and finish with a "
    "concise report: the caller sees only your last message and cannot answer questions, so state any assumption "
    "you made instead of asking."
)


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


def _clean_max_turns(value):
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_TURNS_LIMIT
    ):
        raise ValueError(f"delegate: max_turns must be an integer from 1 to {MAX_TURNS_LIMIT}")
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


def register(minimal):
    settings = minimal.declare_settings({"max_depth": 1})

    def run_delegate(input, ctx):
        task = str(input.get("task", "")).strip()
        if not task:
            raise ValueError("delegate: task must be a non-empty string with everything the delegate needs")
        role = " ".join(str(input.get("role") or "").split())[:MAX_ROLE_CHARS] or DEFAULT_ROLE
        model = input.get("model") or None
        if model is not None and not isinstance(model, str):
            raise ValueError("delegate: model must be a model name")
        max_turns = _clean_max_turns(input.get("max_turns"))
        max_depth = settings["max_depth"]
        if max_depth < 1:
            raise ValueError("delegate: the max_depth setting must be at least 1")
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
        elif stop_nesting:
            limits["exclude_tools"] = {NAME}
        result = ctx.run_agent_result(
            task,
            name=role,
            system_note=NOTE.format(role="" if role == DEFAULT_ROLE else f" with the role: {role}"),
            model=model,
            max_turns=max_turns,
            **limits,
        )
        if result.status != "done":
            raise RuntimeError(_failure(result))
        return result.text or "(the delegate returned no text)"

    minimal.register_tool(
        name=NAME,
        run=run_delegate,
        description=(
            "Hand a self-contained task to a delegate: a fresh agent with an empty history that works alone and "
            "returns only its final message. Use it for research and investigations whose intermediate output is not "
            "worth keeping in this conversation (searching a codebase, reading many files, comparing options). "
            "The delegate sees nothing of this conversation, so the task must contain everything it needs: the "
            "goal, the paths or names involved, constraints, and the form of the report you want. It cannot ask "
            "you questions. Do not delegate what you can do in a call or two. Pass tools to limit what it may use "
            "(for example only read-only tools), and max_turns to bound its work. If it fails, runs out of turns or "
            "is interrupted you get an error with its partial text."
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
                    "maximum": MAX_TURNS_LIMIT,
                    "description": f"Most model requests the delegate may make (1-{MAX_TURNS_LIMIT}, default 50)",
                },
            },
            "required": ["task"],
        },
    )
