"""modes: plan mode blocks every tool that changes things, including those that ask per call; reloads keep the mode."""

import threading
import unittest
from unittest import mock

from support import ROOT, ItemTest, text_reply, tool_reply

ITEM = "extensions/modes.py"
TOOLS = {"ast_grep": str(ROOT / "tools/ast_grep.py"), "docker": str(ROOT / "tools/docker.py")}
PLAN = "I read the code.\n\n1. Edit foo.py.\n2. Update the tests.\n"

LOG_ARGV = '#!/bin/sh\necho "$@" >> "$FAKE_LOG"\n'


class ModesTest(ItemTest):
    def app(self, replies=(), settings=None, extra=()):
        frontend = mock.Mock()
        frontend.ask.return_value = True
        self.frontend = frontend
        return self.make_app(ITEM, list(replies), extra=[TOOLS[name] for name in extra], settings=settings, frontend=frontend)

    @staticmethod
    def offered(app, request=-1):
        return set(app.provider.requests[request].tools)


class PlanModeTest(ModesTest):
    def test_plan_hides_the_tools_that_decide_per_call_whether_to_ask_but_keeps_the_read_ones(self):
        app = self.app([text_reply("a"), text_reply("b")], extra=("ast_grep", "docker"))
        app.context.set_mode("plan")
        self.run_turn(app, "look")
        plan = self.offered(app)
        self.assertTrue({"ast_grep_rewrite", "docker_compose", "docker_exec", "docker_container"}.isdisjoint(plan), plan)
        self.assertLessEqual({"ast_grep_search", "docker_ps", "docker_logs"}, plan)
        app.context.set_mode("build")
        self.run_turn(app, "now do it")
        self.assertLessEqual({"ast_grep_rewrite", "docker_compose", "docker_exec"}, self.offered(app))

    def test_a_call_to_such_a_tool_in_plan_mode_is_refused_and_nothing_runs(self):
        log = self.tmp / "ast.log"
        self.fake_bin("ast-grep", LOG_ARGV)
        with mock.patch.dict("os.environ", {"FAKE_LOG": str(log)}):
            app = self.app(
                [tool_reply("ast_grep_rewrite", {"pattern": "a($X)", "rewrite": "b($X)", "apply": True}), text_reply("ok")],
                extra=("ast_grep",),
            )
            app.context.set_mode("plan")
            self.run_turn(app, "rewrite")
        result = app.messages[-2]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("ast_grep_rewrite is blocked", result["content"])
        self.assertIn("only the user can change the mode", result["content"])
        self.assertFalse(log.exists())

    def test_modes_and_the_current_mode_survive_a_reload_without_problems(self):
        app = self.app([text_reply("a")], extra=("ast_grep",))
        app.context.set_mode("plan")
        _, errors = app.reload_extensions()
        self.assertEqual((errors, app.extension_problems), ([], []))
        self.assertEqual(list(app.context.modes()), ["plan", "build"])
        self.assertEqual(app.mode, "plan")
        self.assertIn("ast_grep_rewrite", app.context.mode_info("plan").exclude_tools)
        self.run_turn(app, "look")
        self.assertNotIn("ast_grep_rewrite", self.offered(app))


class GateAndDefaultTest(ModesTest):
    def wait_for_gate(self):
        for thread in threading.enumerate():
            if thread.name == "modes-gate":
                thread.join(5)
                self.assertFalse(thread.is_alive(), "the plan gate is still waiting")

    def test_default_starts_in_that_mode_and_off_leaves_none(self):
        app = self.app(settings={"default": "plan"})
        app.begin()
        self.assertEqual(app.mode, "plan")
        app = self.app(settings={"default": "off"})
        app.begin()
        self.assertIsNone(app.mode)

    def test_approving_sends_the_configured_message_and_min_steps_decides_what_a_plan_is(self):
        app = self.app(settings={"approve_message": "Go ahead.", "min_steps": 3})
        app.messages.append({"role": "assistant", "content": PLAN})  # two steps: not a plan with min_steps 3
        app.context.set_mode("plan")
        app.context.set_mode("build")
        self.wait_for_gate()
        self.frontend.ask.assert_not_called()
        app.context.set_mode("plan")
        app.messages.append({"role": "assistant", "content": PLAN + "3. Ship it.\n"})
        app.context.set_mode("build")
        self.wait_for_gate()
        self.frontend.ask.assert_called_once()
        self.assertEqual(list(app.queued), ["Go ahead."])

    def test_approve_gate_false_switches_without_asking(self):
        app = self.app(settings={"approve_gate": False})
        app.messages.append({"role": "assistant", "content": PLAN})
        app.context.set_mode("plan")
        app.context.set_mode("build")
        self.wait_for_gate()
        self.frontend.ask.assert_not_called()
        self.assertEqual((app.mode, list(app.queued)), ("build", []))

    def test_declining_returns_to_plan_mode(self):
        app = self.app()
        self.frontend.ask.return_value = False
        app.messages.append({"role": "assistant", "content": PLAN})
        app.context.set_mode("plan")
        app.context.set_mode("build")
        self.wait_for_gate()
        self.assertEqual((app.mode, list(app.queued)), ("plan", []))


if __name__ == "__main__":
    unittest.main()
