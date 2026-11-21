"""Compacts the history into a summary when the context grows, and adds /compact.

Compacting asks the model for a summary of the conversation and continues in
a new session holding that summary and the last exchange. The old session
stays on disk untouched: ``/resume <id>`` brings the full history back.

It runs by itself when the context reaches ``compact_at`` tokens: in the middle of a
turn, the requests that remain send a summary instead of the earlier history, and
when the turn ends the session is switched to that summary; at the end of a turn,
as ``/compact`` does. Providers that report no usage never trigger it. Run it on
demand with ``/compact``. Everything is a setting (``/ext settings compact``):
``compact_at`` or, to follow the model's real window, ``window_ratio`` (a fraction of
``ctx.context_window``; ``compact_at`` is used when the window is unknown), ``auto`` to compact
only on demand, ``keep_last`` (how many recent exchanges stay word for word), ``summary_prompt``,
``model`` and ``reasoning_effort`` of the summary request, and ``notify`` for a toast and a progress
note when it runs::

    {"extensions": {"settings": {"compact": {"window_ratio": 0.7, "keep_last": 2}}}}

Install it with ``/ext``.
"""

import sys

from minimal.api import REASONING_EFFORTS, TurnInterrupted

__version__ = "2.4"
__api__ = "2.3"
__tags__ = ["context", "workflow"]

COMPACT_AT = 100_000
"""Default context tokens (input + output of the last reply) that trigger a compaction."""

SUMMARY_REQUEST = (
    "Stop here and do not call any tools. Write a summary of this whole conversation that will replace it as your "
    "only memory: the user's goals and instructions, decisions made, files read or changed (with paths), commands "
    "run and their relevant results, the current state, and what remains to be done. Be specific and complete; "
    "plain text."
)

SUMMARY_PREFIX = "Summary of the earlier conversation (compacted):\n\n"

ACK = "Understood. I will continue from this summary."

DEFAULTS = {
    "auto": True,
    "compact_at": COMPACT_AT,
    "window_ratio": 0.0,
    "keep_last": 1,
    "summary_prompt": SUMMARY_REQUEST,
    "model": "",
    "reasoning_effort": "",
    "notify": False,
}

SCHEMA = {
    "auto": {"description": "Compact by itself when the context is full. False: only /compact compacts."},
    "compact_at": {
        "description": "Context tokens (input + output of the last reply) that trigger a compaction.",
        "min": 1,
        "max": 100_000_000,
    },
    "window_ratio": {
        "description": "Fraction of the model's context window that triggers a compaction, e.g. 0.7. "
        "0 uses compact_at; so does a model whose window is unknown (set the context_window setting).",
        "min": 0,
        "max": 1,
    },
    "keep_last": {
        "description": "Recent exchanges (your message and the model's final answer) kept word for word next to the summary.",
        "min": 0,
        "max": 50,
    },
    "summary_prompt": {"description": "The instruction that asks the model for the summary."},
    "model": {"description": "Model of the current provider that writes the summary (empty: the current model)."},
    "reasoning_effort": {
        "description": "How hard the model thinks while summarising (empty: the session's setting).",
        "enum": ["", *REASONING_EFFORTS],
    },
    "notify": {"description": "Show a toast when a compaction runs or is skipped, and a progress note while summarising."},
}


def check_settings(settings):
    """The problems of ``settings`` that the schema cannot express, each with its fix."""
    problems = []
    if not settings["summary_prompt"].strip():
        problems.append("summary_prompt must not be empty; remove it to use the default")
    return problems


def _text(blocks):
    return "".join(block["text"] for block in blocks if block["type"] == "text")


def threshold(ctx, settings=DEFAULTS):
    """Context tokens at which a compaction starts: ``window_ratio`` of the model's window when set and known, else ``compact_at``."""
    ratio = settings["window_ratio"]
    window = ctx.context_window if ratio else None
    return max(1, int(window * ratio)) if window else settings["compact_at"]


def _say(ctx, settings, text, kind="info"):
    """Show ``text`` as a toast when the ``notify`` setting is on."""
    if settings["notify"]:
        ctx.notify(text, kind)


def _request(ctx, messages, settings):
    """The model's summary of ``messages`` (which end with the summary request), asked as the settings say.

    Raises:
        ValueError: if the reply has no text or calls a tool, or the ``model`` setting names a model that fails.
    """
    model = settings["model"].strip() or None
    options = {"reasoning_effort": settings["reasoning_effort"]} if settings["reasoning_effort"] else None
    if settings["notify"]:
        ctx.progress("compact: summarising the conversation")
    try:
        # Another model has its own prompt cache: offering the tools would only cost tokens.
        reply = ctx.complete(messages, tools=model is None, options=options, model=model)
    except TurnInterrupted:
        raise
    except Exception as e:
        if model is None:
            raise
        raise ValueError(
            f"the summary request to model {model!r} failed ({e}); set extensions.settings.compact.model to a model "
            "of the current provider, or to \"\" for the current model"
        ) from e
    finally:
        if settings["notify"]:
            ctx.progress(None)
    summary = _text(reply.content)
    if not summary or any(block["type"] == "tool_use" for block in reply.content):
        raise ValueError("the model did not return a summary")
    return summary


def _summarise(ctx, messages, settings=DEFAULTS):
    """The model's summary of ``messages``, which must end with a ``user`` message.

    The summary request goes into a copy of that last message, so two ``user`` messages never
    follow each other.

    Raises:
        ValueError: if the reply has no text or calls a tool.
    """
    last = messages[-1]
    content = last["content"]
    prompt = settings["summary_prompt"]
    if isinstance(content, str):
        content = content + "\n\n" + prompt
    else:
        content = [*content, {"type": "text", "text": prompt}]
    return _request(ctx, [*messages[:-1], {**last, "content": content}], settings)


def _kept(messages, keep_last):
    """The last ``keep_last`` exchanges as ``user``/``assistant`` messages: your prompt and the text of the final answer.

    Earlier summaries (a session that was compacted before) are not kept again, and an exchange whose
    last message is not an answer with text is left out.
    """
    starts = [i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m["content"], str)]
    ends = {start: end for start, end in zip(starts, [*starts[1:], len(messages)])}
    kept = []
    window = [i for i in starts if not messages[i]["content"].startswith(SUMMARY_PREFIX)][-keep_last:] if keep_last else []
    for start in window:
        final = messages[ends[start] - 1]
        content = final["content"]
        answer = [{"type": "text", "text": content}] if isinstance(content, str) else [
            b for b in content if b["type"] == "text"
        ]
        if final["role"] == "assistant" and answer:  # an assistant message without content would be rejected by the API
            kept += [{"role": "user", "content": messages[start]["content"]}, {"role": "assistant", "content": answer}]
    return kept


def compact(ctx, settings=DEFAULTS):
    """Summarise ``ctx.messages`` and switch to a new session with the summary and the last exchanges.

    The summary request sends the same system prompt, tools and history plus
    one message, so it reads the provider's prompt cache. Nothing changes
    unless the model returns a summary.

    Returns:
        A line telling the user what happened.

    Raises:
        ValueError: if there is no finished exchange to compact, or the model returned no summary.
        TurnInterrupted: if the user interrupts before the session is switched; nothing is saved or changed then.
    """
    messages = ctx.messages
    asked = [i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m["content"], str)]
    if not asked or messages[-1]["role"] != "assistant":
        raise ValueError("nothing to compact")

    ctx.check_cancelled()
    summary = _request(ctx, [*messages, {"role": "user", "content": settings["summary_prompt"]}], settings)

    kept = [
        {"role": "user", "content": SUMMARY_PREFIX + summary},
        {"role": "assistant", "content": [{"type": "text", "text": ACK}]},
        *_kept(messages, settings["keep_last"]),
    ]

    ctx.check_cancelled()  # before anything is saved: the interrupted turn is dropped from history
    old = ctx.new_session(kept)
    return (
        f"[compact] {len(messages)} messages summarised into session {ctx.session_id}; "
        f"the full history stays in session {old}"
    )


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    problems = check_settings(settings)
    if problems:
        raise ValueError(f"compact settings: {'; '.join(problems)}")
    # A summary made in the middle of a turn: the requests that remain send it instead of
    # messages[:upto]. ``anchor`` is messages[upto - 1] of the live history, so a history that was
    # replaced or rolled back is not mistaken for this one.
    mid = {"anchor": None, "upto": 0, "summary": ""}

    def _active(messages):
        return (
            mid["anchor"] is not None
            and len(messages) > mid["upto"]
            and messages[mid["upto"] - 1] is mid["anchor"]
        )

    def _view(messages):
        # messages[upto] is always an assistant message, so roles keep alternating.
        return [{"role": "user", "content": SUMMARY_PREFIX + mid["summary"]}, *messages[mid["upto"] :]]

    def _reset():
        mid.update(anchor=None, upto=0, summary="")

    @minimal.command("compact", description="summarise the conversation into a new session")
    def compact_command(args, ctx):
        print(compact(ctx, settings))

    if not settings["auto"]:
        return

    @minimal.on("before_request")
    def summarise_when_full(event):
        """In the middle of a turn, replace the history with a summary once the context is full."""
        messages = event["messages"]
        if (
            event["nested"]
            or len(messages) < 4
            or messages[-1]["role"] != "user"
            or isinstance(messages[-1]["content"], str)  # the turn's first request: turn_end covers it
        ):
            return None
        ctx = event["ctx"]
        base = _view(messages) if _active(messages) else messages
        usage = messages[-2].get("usage")
        if usage and usage["input_tokens"] + usage["output_tokens"] >= threshold(ctx, settings):
            k = len(base) - 2
            if k >= 2:
                try:
                    summary = _summarise(ctx, base[:k], settings)
                except ValueError as e:
                    print(f"[compact] skipped: {e}", file=sys.stderr)
                    _say(ctx, settings, f"compact: skipped: {e}", "warning")
                else:
                    mid.update(anchor=messages[len(messages) - 3], upto=len(messages) - 2, summary=summary)
                    base = _view(messages)
                    print("[compact] context summarised for the rest of this turn; the session is compacted when it ends")
                    _say(ctx, settings, "compact: context summarised for the rest of this turn")
        return {"messages": base} if base is not messages else None

    @minimal.on("turn_end")
    def compact_when_full(event):
        """Compact when the turn that just ended left the session's context full."""
        if event["nested"]:
            return  # not the session's own history: a subagent's loop
        ctx = event["ctx"]
        if _active(event["messages"]):
            kept = _view(event["messages"])
            _reset()
            ctx.check_cancelled()
            old = ctx.new_session(kept)
            line = (
                f"[compact] {len(event['messages'])} messages summarised into session {ctx.session_id}; "
                f"the full history stays in session {old}"
            )
            print(line)
            _say(ctx, settings, f"compact: session compacted into {ctx.session_id}")
            return
        _reset()
        usage = event["messages"][-1].get("usage")
        if not usage or usage["input_tokens"] + usage["output_tokens"] < threshold(ctx, settings):
            return
        try:
            line = compact(ctx, settings)
        except ValueError as e:
            print(f"[compact] skipped: {e}", file=sys.stderr)
            _say(ctx, settings, f"compact: skipped: {e}", "warning")
        else:
            print(line)
            _say(ctx, settings, f"compact: session compacted into {ctx.session_id}")

    @minimal.on("session_switch")
    def forget_summary(event):
        _reset()
