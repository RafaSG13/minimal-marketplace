"""tools/delegate: flags, the settings combination check and its consumer-visible effect. The full run/depth/cwd/parallel
behaviour is pinned by minimal's own tests/test_bundled_delegate.py."""

import unittest
from types import SimpleNamespace

from support import ItemTest, text_reply, tool_reply

ITEM = "tools/delegate.py"


class DelegateTest(ItemTest):
    def use(self, **settings):
        self.registry, errors = self.load(ITEM, **settings)
        self.assertEqual(errors, [])
        return self.registry.tools["delegate"]

    def fake_ctx(self, tools=None):
        """A ctx whose ``run_agent_result`` records its keywords and finishes with ``ok``."""
        self.runs = []

        def run_agent_result(prompt, **kw):
            self.runs.append((prompt, kw))
            return SimpleNamespace(status="done", error=None, text="ok")

        return self.ctx(
            tools=tools or self.registry.tools,
            agents=lambda: [],
            run_agent_result=run_agent_result,
        )

    def test_flags_follow_the_parallel_setting_and_it_never_asks_to_confirm(self):
        tool = self.use()
        self.assertFalse(tool.read_only)
        self.assertFalse(tool.confirm)  # what the delegate does is confirmed tool by tool
        tool = self.use(parallel=True)
        self.assertTrue(tool.read_only)
        self.assertIn("limited to read-only tools", tool.description)

    def test_the_description_says_when_to_use_it_and_not_to(self):
        description = self.use().description
        self.assertIn("Do not delegate what you can do in a call or two", description)
        self.assertIn("The delegate sees nothing of this conversation", description)

    def test_a_default_turn_limit_above_the_cap_is_reported_and_clamped(self):
        tool = self.use(default_max_turns=40, max_turns_limit=5)
        (problem,) = self.registry.problems
        self.assertEqual(
            problem,
            "tools/delegate: setting default_max_turns (40) is above max_turns_limit (5); using 5: "
            "lower default_max_turns or raise max_turns_limit",
        )
        self.assertEqual(tool.run({"task": "t"}, self.fake_ctx()), "ok")
        self.assertEqual(self.runs[0][1]["max_turns"], 5)  # not 40: the cap the model is held to binds the default too
        self.assertIn("default 5)", tool.input_schema["properties"]["max_turns"]["description"])

    def test_a_default_turn_limit_within_the_cap_is_used_as_is(self):
        tool = self.use(default_max_turns=4, max_turns_limit=5)
        self.assertEqual(self.registry.problems, [])
        tool.run({"task": "t"}, self.fake_ctx())
        self.assertEqual(self.runs[0][1]["max_turns"], 4)
        tool.run({"task": "t", "max_turns": 2}, self.fake_ctx())
        self.assertEqual(self.runs[0][1]["max_turns"], 2)  # fake_ctx starts a fresh record

    def test_the_model_cannot_ask_for_more_turns_than_the_cap(self):
        tool = self.use(max_turns_limit=5)
        with self.assertRaisesRegex(ValueError, r"^delegate: max_turns must be an integer from 1 to 5 \(setting max_turns_limit\)$"):
            tool.run({"task": "t", "max_turns": 6}, self.fake_ctx())
        self.assertEqual(self.runs, [])

    def test_a_blank_task_is_refused_before_an_agent_starts(self):
        tool = self.use()
        with self.assertRaisesRegex(
            ValueError, r"^delegate: task must be a non-empty string with everything the delegate needs$"
        ):
            tool.run({"task": "  "}, self.fake_ctx())
        self.assertEqual(self.runs, [])

    def test_a_failed_delegate_is_an_error_with_its_status_and_partial_text(self):
        tool = self.use()
        ctx = self.fake_ctx()
        ctx.run_agent_result = lambda prompt, **kw: SimpleNamespace(status="max_turns", error="turn limit of 3 reached", text="half done\n")
        with self.assertRaises(RuntimeError) as caught:
            tool.run({"task": "t"}, ctx)
        self.assertEqual(
            str(caught.exception),
            "The delegate ran out of turns (status: max_turns: turn limit of 3 reached). "
            "Split the task or raise max_turns.\nIts last message:\nhalf done",
        )

    def test_it_starts_no_thread_and_nothing_at_register(self):
        import threading

        before = threading.active_count()
        self.use()
        self.assertEqual(threading.active_count(), before)

    def test_through_an_app_the_delegate_runs_with_an_empty_history_and_returns_its_last_message(self):
        app = self.make_app(ITEM, [tool_reply("delegate", {"task": "look at x", "role": "scout"}), text_reply("found y"), text_reply("main done")])
        self.run_turn(app, "go")
        main, child, final = app.provider.requests
        self.assertEqual(child.messages[0]["content"], "look at x")
        self.assertEqual(len(child.messages), 1)  # nothing of the main conversation
        self.assertIn("with the role: scout", child.system)
        result = final.messages[-1]["content"][0]
        self.assertEqual((result["content"], result.get("is_error", False)), ("found y", False))


if __name__ == "__main__":
    unittest.main()
