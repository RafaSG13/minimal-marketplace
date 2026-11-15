"""Compacts the history into a summary when the context grows, and adds /compact.

Compacting asks the model for a summary of the conversation and continues in
a new session holding that summary and the last exchange. The old session
stays on disk untouched: ``/resume <id>`` brings the full history back.

It runs by itself when the context reaches ``compact_at`` tokens: in the middle of a
turn, the requests that remain send a summary instead of the earlier history, and
when the turn ends the session is switched to that summary; at the end of a turn,
as ``/compact`` does. Providers that report no usage never trigger it. Run it on
demand with ``/compact``. Set the threshold in settings.json::

    {"extensions": {"settings": {"compact": {"compact_at": 150000}}}}

Install it with ``/ext``.
"""

import sys

__version__ = "2.2"
__api__ = "2"

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


def _text(blocks):
    return "".join(block["text"] for block in blocks if block["type"] == "text")


def _summarise(ctx, messages):
    """The model's summary of ``messages``, which must end with a ``user`` message.

    The summary request goes into a copy of that last message, so two ``user`` messages never
    follow each other.

    Raises:
        ValueError: if the reply has no text or calls a tool.
    """
    last = messages[-1]
    content = last["content"]
    if isinstance(content, str):
        content = content + "\n\n" + SUMMARY_REQUEST
    else:
        content = [*content, {"type": "text", "text": SUMMARY_REQUEST}]
    reply = ctx.complete([*messages[:-1], {**last, "content": content}], tools=True)
    summary = _text(reply.content)
    if not summary or any(block["type"] == "tool_use" for block in reply.content):
        raise ValueError("the model did not return a summary")
    return summary



def compact(ctx):
    """Summarise ``ctx.messages`` and switch to a new session with the summary and the last exchange.

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
    reply = ctx.complete([*messages, {"role": "user", "content": SUMMARY_REQUEST}], tools=True)
    summary = _text(reply.content)
    if not summary or any(block["type"] == "tool_use" for block in reply.content):
        raise ValueError("the model did not return a summary")

    answer = [b for b in messages[-1]["content"] if b["type"] == "text"]
    kept = [
        {"role": "user", "content": SUMMARY_PREFIX + summary},
        {"role": "assistant", "content": [{"type": "text", "text": ACK}]},
    ]
    if answer:  # an assistant message without content would be rejected by the API
        kept += [
            {"role": "user", "content": messages[asked[-1]]["content"]},
            {"role": "assistant", "content": answer},
        ]

    ctx.check_cancelled()  # before anything is saved: the interrupted turn is dropped from history
    old = ctx.new_session(kept)
    return (
        f"[compact] {len(messages)} messages summarised into session {ctx.session_id}; "
        f"the full history stays in session {old}"
    )


def register(minimal):
    settings = minimal.declare_settings({"compact_at": COMPACT_AT})
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

    @minimal.on("before_request")
    def summarise_when_full(event):
        """In the middle of a turn, replace the history with a summary once the context reaches ``compact_at`` tokens."""
        messages = event["messages"]
        if (
            event["nested"]
            or len(messages) < 4
            or messages[-1]["role"] != "user"
            or isinstance(messages[-1]["content"], str)  # the turn's first request: turn_end covers it
        ):
            return None
        base = _view(messages) if _active(messages) else messages
        usage = messages[-2].get("usage")
        if usage and usage["input_tokens"] + usage["output_tokens"] >= settings["compact_at"]:
            k = len(base) - 2
            if k >= 2:
                try:
                    summary = _summarise(event["ctx"], base[:k])
                except ValueError as e:
                    print(f"[compact] skipped: {e}", file=sys.stderr)
                else:
                    mid.update(anchor=messages[len(messages) - 3], upto=len(messages) - 2, summary=summary)
                    base = _view(messages)
                    print("[compact] context summarised for the rest of this turn; the session is compacted when it ends")
        return {"messages": base} if base is not messages else None

    @minimal.on("turn_end")
    def compact_when_full(event):
        """Compact when the turn that just ended left the session's context at ``compact_at`` tokens or more."""
        if event["nested"]:
            return  # not the session's own history: a subagent's loop
        if _active(event["messages"]):
            kept = _view(event["messages"])
            _reset()
            ctx = event["ctx"]
            ctx.check_cancelled()
            old = ctx.new_session(kept)
            print(
                f"[compact] {len(event['messages'])} messages summarised into session {ctx.session_id}; "
                f"the full history stays in session {old}"
            )
            return
        _reset()
        usage = event["messages"][-1].get("usage")
        if not usage or usage["input_tokens"] + usage["output_tokens"] < settings["compact_at"]:
            return
        try:
            print(compact(event["ctx"]))
        except ValueError as e:
            print(f"[compact] skipped: {e}", file=sys.stderr)

    @minimal.on("session_switch")
    def forget_summary(event):
        _reset()

    @minimal.command("compact", description="summarise the conversation into a new session")
    def compact_command(args, ctx):
        print(compact(ctx))
