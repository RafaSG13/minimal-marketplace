"""compact: /compact and the automatic summary, through a real App with a scripted provider.

The item registers no tool, starts no process or thread and writes no file of its own (the new session is minimal's),
so the item standard's tool, subprocess and disposal points do not apply; what matters is when it compacts, what it
keeps, and how a bad setting or a failing summary request is reported.
"""

import contextlib
import io
import threading
import unittest
from unittest import mock

from minimal.providers.base import Reply, Usage

from support import ROOT, ItemTest, RecordingProvider, text_reply

ITEM = "extensions/compact.py"
SUMMARY_PREFIX = "Summary of the earlier conversation (compacted):\n\n"
ACK = "Understood. I will continue from this summary."


def exchange(question, answer):
    return [
        {"role": "user", "content": question},
        {"role": "assistant", "content": [{"type": "text", "text": answer}]},
    ]


def texts(messages):
    return [m["content"] if isinstance(m["content"], str) else m["content"][0]["text"] for m in messages]


def full(text, tokens):
    """A final reply that reports ``tokens`` of context."""
    return text_reply(text, usage=Usage(input_tokens=tokens, output_tokens=1))


class CompactTest(ItemTest):
    def app(self, replies=(), settings=None):
        frontend = mock.Mock()
        frontend.theme_name.return_value = None
        self.frontend = frontend
        return self.make_app(ITEM, replies, settings=settings, session_id="old", frontend=frontend)

    def run_command(self, app, line):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            app.run_command(line)
        return out.getvalue()

    def compacted(self, app):
        return app.session.id != "old"

    # --- the command ------------------------------------------------------------------------------------------

    def test_the_command_summarises_into_a_new_session_and_keeps_the_last_exchange(self):
        app = self.app()
        app.messages[:] = [*exchange("q1", "a1"), *exchange("q2", "a2")]
        app.provider.replies = [text_reply("SUMMARY")]
        out = self.run_command(app, "/compact")
        self.assertRegex(out, r"\[compact\] 4 messages summarised into session [\w-]+; the full history stays in session old")
        self.assertEqual(texts(app.messages), [SUMMARY_PREFIX + "SUMMARY", ACK, "q2", "a2"])
        self.assertEqual([m["role"] for m in app.messages], ["user", "assistant"] * 2)
        # the request that made the summary carried the history and then the default instruction
        asked = app.provider.requests[0].messages
        self.assertEqual(texts(asked[:4]), ["q1", "a1", "q2", "a2"])
        self.assertIn("Write a summary of this whole conversation", asked[-1]["content"])
        self.assertTrue(self.compacted(app))

    def test_nothing_to_compact_says_so_and_changes_nothing(self):
        app = self.app()
        out = self.run_command(app, "/compact")
        self.assertIn("nothing to compact", out)
        self.assertEqual(app.provider.requests, [])
        self.assertFalse(self.compacted(app))

    def test_summary_prompt_replaces_the_instruction_and_keep_last_zero_keeps_only_the_summary(self):
        app = self.app(settings={"summary_prompt": "Summarise in one line.", "keep_last": 0})
        app.messages[:] = exchange("q", "a")
        app.provider.replies = [text_reply("S1")]
        self.run_command(app, "/compact")
        self.assertEqual(app.provider.requests[0].messages[-1], {"role": "user", "content": "Summarise in one line."})
        self.assertEqual(texts(app.messages), [SUMMARY_PREFIX + "S1", ACK])

    def test_keep_last_keeps_that_many_exchanges_and_never_repeats_an_old_summary(self):
        app = self.app(settings={"keep_last": 5})
        app.messages[:] = [*exchange(SUMMARY_PREFIX + "S0", ACK), *exchange("q", "a")]
        app.provider.replies = [text_reply("S1")]
        self.run_command(app, "/compact")
        self.assertEqual(texts(app.messages), [SUMMARY_PREFIX + "S1", ACK, "q", "a"])

    def test_a_reply_without_text_changes_nothing(self):
        app = self.app()
        app.messages[:] = exchange("q", "a")
        before = list(app.messages)
        app.provider.replies = [Reply(content=[], stop_reason="end_turn")]
        out = self.run_command(app, "/compact")
        self.assertIn("the model did not return a summary", out)
        self.assertEqual(app.messages, before)
        self.assertFalse(self.compacted(app))

    # --- automatic compaction --------------------------------------------------------------------------------

    def test_compacts_when_the_turn_ends_at_the_threshold_and_not_below_it(self):
        app = self.app([full("answer", 99_998), ], settings={"compact_at": 100_000})
        self.run_turn(app, "q")
        self.assertFalse(self.compacted(app))
        self.assertEqual(len(app.provider.requests), 1)
        app.provider.replies = [full("answer2", 99_999), text_reply("SUMMARY")]
        self.run_turn(app, "q2")
        self.assertTrue(self.compacted(app))
        self.assertEqual(texts(app.messages), [SUMMARY_PREFIX + "SUMMARY", ACK, "q2", "answer2"])

    def test_auto_false_leaves_compacting_to_the_command(self):
        app = self.app([full("answer", 10_000_000)], settings={"auto": False})
        self.run_turn(app, "q")
        self.assertFalse(self.compacted(app))
        self.assertEqual(len(app.provider.requests), 1)
        app.provider.replies = [text_reply("SUMMARY")]
        self.assertIn("[compact] 2 messages summarised", self.run_command(app, "/compact"))
        self.assertTrue(self.compacted(app))

    def test_window_ratio_uses_the_models_window_and_falls_back_to_compact_at(self):
        # the window is unknown to the fake provider: 0.5 of nothing -> compact_at decides
        app = self.app([full("answer", 1_998)], settings={"window_ratio": 0.5, "compact_at": 2_000})
        self.assertIsNone(app.context.context_window)
        self.run_turn(app, "q")
        self.assertFalse(self.compacted(app))
        app.provider.replies = [full("answer", 1_999), text_reply("S")]
        self.run_turn(app, "q")
        self.assertTrue(self.compacted(app))

    def test_the_middle_of_a_turn_sends_a_summary_instead_of_the_history(self):
        (self.tmp / "f.txt").write_text("x")
        app = self.app(settings={"compact_at": 50, "summary_prompt": "ONE LINE"})
        app.messages[:] = exchange("q0", "a0")
        read = {"type": "tool_use", "id": "r1", "name": "read", "input": {"path": "f.txt"}}
        app.provider.replies = [
            Reply(content=[read], stop_reason="tool_use", usage=Usage(input_tokens=50, output_tokens=1)),
            text_reply("SUMMARY"),
            text_reply("done"),
        ]
        self.run_turn(app, "q")
        summary_request, after = app.provider.requests[1], app.provider.requests[2]
        self.assertTrue(summary_request.messages[-1]["content"].endswith("ONE LINE"))
        self.assertEqual(after.messages[0]["content"], SUMMARY_PREFIX + "SUMMARY")
        # the history sent after the summary does not repeat what the summary replaced
        self.assertNotIn("q0", texts([m for m in after.messages if isinstance(m["content"], str)]))

    def test_the_session_switched_to_at_the_end_of_a_mid_turn_summary_continues_from_it(self):
        (self.tmp / "f.txt").write_text("x")
        app = self.app(settings={"compact_at": 50})
        app.messages[:] = exchange("q0", "a0")
        read = {"type": "tool_use", "id": "r1", "name": "read", "input": {"path": "f.txt"}}
        app.provider.replies = [
            Reply(content=[read], stop_reason="tool_use", usage=Usage(input_tokens=50, output_tokens=1)),
            text_reply("SUMMARY"),
            text_reply("done"),
        ]
        self.run_turn(app, "q")
        self.assertTrue(self.compacted(app))
        app.provider.replies = [text_reply("next")]
        self.run_turn(app, "again")
        sent = [m["content"] for m in app.provider.requests[-1].messages if isinstance(m["content"], str)]
        self.assertEqual(sent, [SUMMARY_PREFIX + "SUMMARY", "again"])  # neither q0 nor the turn's own prompt come back

    # --- the summary request ------------------------------------------------------------------------------------

    def test_model_and_reasoning_effort_go_to_the_summary_request_only(self):
        calls = []

        class Options(RecordingProvider):
            def stream(self, **kw):
                calls.append((kw["model"], kw.get("options")))
                return super().stream(**kw)

        app = self.app(settings={"model": "small-model", "reasoning_effort": "low"})
        app.provider = Options([full("answer", 100_000), text_reply("S")])
        self.run_turn(app, "q")
        self.assertEqual(calls[0][0], "m")
        self.assertNotEqual((calls[0][1] or {}).get("reasoning_effort"), "low")
        self.assertEqual((calls[1][0], calls[1][1]["reasoning_effort"]), ("small-model", "low"))
        self.assertEqual(app.provider.requests[1].tools, [])  # another model has its own cache: no tools offered
        self.assertEqual(app.model, "m")

    def test_a_failing_summary_model_is_reported_with_the_fix_and_the_session_is_kept(self):
        app = self.app(settings={"model": "nope"})
        app.provider = RecordingProvider([full("answer", 100_000)])
        stream = app.provider.stream

        def fail_on_summary(**kw):
            if kw["model"] == "nope":
                raise RuntimeError("unknown model")
            return stream(**kw)

        app.provider.stream = fail_on_summary
        out = self.run_turn(app, "q")
        self.assertIn(
            "[compact] skipped: the summary request to model 'nope' failed (unknown model); set "
            'extensions.settings.compact.model to a model of the current provider, or to "" for the current model',
            out,
        )
        self.assertFalse(self.compacted(app))

    def test_notify_toasts_and_a_progress_note_only_when_asked(self):
        app = self.app([full("answer", 100_000), text_reply("S")])
        self.run_turn(app, "q")
        self.frontend.notify.assert_not_called()
        self.frontend.progress.assert_not_called()

        app = self.app([full("answer", 100_000), text_reply("S")], settings={"notify": True})
        self.run_turn(app, "q")
        (toast,) = self.frontend.notify.call_args_list
        self.assertRegex(toast.args[0], r"^compact: session compacted into [\w-]+")
        self.assertEqual([c.args[0] for c in self.frontend.progress.call_args_list], ["compact: summarising the conversation", None])

    # --- settings -------------------------------------------------------------------------------------------------

    def test_an_empty_summary_prompt_is_a_warning_and_the_default_prompt_is_used(self):
        self.write_settings(**{"compact": {"summary_prompt": "  "}})
        registry, errors = self.load(ITEM)
        self.assertEqual(errors, [])
        (problem,) = registry.problems
        self.assertIn("extensions.settings.compact.summary_prompt must not be empty; the default prompt is used until you fix it", problem)
        self.assertIn("compact", registry.commands)

    def test_a_value_outside_the_schema_fails_the_load_with_the_key_named(self):
        for settings, key in (({"keep_last": -1}, "keep_last"), ({"window_ratio": 1.5}, "window_ratio"), ({"compact_at": 0}, "compact_at")):
            with self.subTest(settings=settings):
                _, errors = self.load(ITEM, **settings)
                self.assertTrue(any(key in e for e in errors), errors)

    def test_registering_starts_nothing_and_writes_nothing(self):
        before, threads = sorted(p.name for p in self.tmp.iterdir()), threading.active_count()
        registry, errors = self.load(ITEM)
        self.assertEqual(errors, [])
        self.assertIn("compact", registry.commands)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), before)
        self.assertEqual(threading.active_count(), threads)

    def test_metadata(self):
        source = (ROOT / ITEM).read_text()
        self.assertIn('__api__ = "2.4"', source)
        self.assertIn('__tags__ = ["context", "workflow"]', source)


if __name__ == "__main__":
    unittest.main()
