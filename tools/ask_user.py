"""Ask-user tool: lets the model ask you a clarifying question instead of guessing.

The question appears in the terminal as a prompt (free text) or a menu (when the model offers options). Your answer
returns to the model as the tool result. If you cancel, reply with nothing, or there is no terminal to ask in, the
model gets an error telling it to continue with an explicit assumption.

Install it with ``/ext``.
"""

__version__ = "1.0"
__api__ = "2"

MAX_OPTIONS = 9

NO_ANSWER = (
    "The user gave no answer (cancelled, empty reply, or there is no terminal to ask in). "
    "Continue with your best assumption and say which one, or finish and explain what you need."
)


def _clean_options(options):
    """Return the non-empty, stripped, de-duplicated options (order kept, at most ``MAX_OPTIONS``)."""
    seen = []
    for option in options or []:
        if isinstance(option, str) and option.strip() and option.strip() not in seen:
            seen.append(option.strip())
    return seen[:MAX_OPTIONS]


def ask_user(input, ctx):
    """Ask ``input["question"]`` (with optional ``input["options"]``) and return the user's answer."""
    question = str(input.get("question", "")).strip()
    if not question:
        raise ValueError("ask_user needs a non-empty question")
    options = _clean_options(input.get("options"))
    if options:
        answer = ctx.ui.choose(question, [(option, option) for option in options])
    else:
        answer = ctx.ui.ask_text(question)
    if answer is None:
        raise ValueError(NO_ANSWER)
    return answer


def register(minimal):
    minimal.register_tool(
        name="ask_user",
        run=ask_user,
        description=(
            "Ask the user a question and wait for the answer. Use it only when a decision is ambiguous and a wrong "
            "guess would be costly. Ask one question per call. Pass `options` when the answers are a short closed "
            "set (the user picks one); omit it for an open question (the user types a reply). Do not ask what "
            "files or tools can tell you."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The single question to ask"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional closed set of answers to pick from (at most 9 are used)",
                },
            },
            "required": ["question"],
        },
    )
