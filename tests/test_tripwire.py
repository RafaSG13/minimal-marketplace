"""tripwire: invariants re-run after changes; nothing runs or is written at register; children are scrubbed and killed."""

import contextlib
import importlib.util
import io
import os
import time
import unittest
from unittest import mock

from minimal import config

from support import ROOT, ItemTest, have, text_reply, tool_reply

ITEM = "extensions/tripwire.py"

LOG_GIT = '#!/bin/sh\necho "$@" >> "$FAKE_LOG"\nexit 1\n'


def module():
    spec = importlib.util.spec_from_file_location("tripwire_under_test", ROOT / ITEM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(have("git"), "git is not installed")
class TripwireTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.repo = self.git_repo({"a.txt": "good\n"})

    def state_file(self):
        return config.project_data_dir(str(self.repo)) / "tripwire" / "state.json"

    def app(self, replies=(), **settings):
        return self.make_app(ITEM, list(replies), cwd=self.repo, settings=settings or None)

    def command(self, app, line):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            app.run_command(line)
        return out.getvalue()

    def edit_turn(self, app, text="bad\n", name="write"):
        """One turn in which the model writes ``a.txt``; returns the tool result text it got."""
        args = {"path": "a.txt", "content": text}
        app.provider.replies[:] = [tool_reply(name, args), text_reply("ok")]
        self.run_turn(app, "go")
        return str(app.messages[-2]["content"][0]["content"])

    def test_register_starts_no_process_runs_no_invariant_and_writes_no_file(self):
        marker = self.tmp / "ran"
        log = self.tmp / "git.log"
        self.fake_bin("git", LOG_GIT)
        with mock.patch.dict(os.environ, {"FAKE_LOG": str(log)}):
            registry, errors = self.load(ITEM, commands=[f"touch {marker}"])
        self.assertEqual(errors, [])
        self.assertFalse(log.exists(), "register must not run git")
        self.assertFalse(marker.exists())
        self.assertFalse(self.state_file().exists())
        # the panel still shows the configured invariant, without writing it
        self.assertIn("0/1 wires", registry.panels["tripwire"].render(self.ctx(cwd=self.repo)))
        self.assertFalse(self.state_file().exists())

    def test_a_change_that_breaks_an_invariant_is_named_in_the_tool_result(self):
        app = self.app()
        self.assertIn("passing now", self.command(app, "/tripwire add grep -q good a.txt"))
        seen = self.edit_turn(app)
        self.assertIn(
            '[tripwire] "grep -q good a.txt" was passing before this call and fails now:\n(no output)', seen
        )
        self.assertIn("1. failing  grep -q good a.txt", self.command(app, "/tripwire"))
        self.assertIn('[tripwire] "grep -q good a.txt" passes again', self.edit_turn(app, "good\n"))

    def test_configured_commands_run_after_the_first_change_and_are_saved_then(self):
        marker = self.tmp / "ran"
        app = self.app(commands=[f"touch {marker}"])
        self.assertFalse(self.state_file().exists())
        self.edit_turn(app, "changed\n")
        self.assertTrue(marker.exists())
        self.assertTrue(self.state_file().is_file())

    def test_an_unreadable_state_file_is_reported_not_treated_as_no_invariants(self):
        app = self.app()
        self.command(app, "/tripwire add true")
        self.state_file().write_text("{broken")
        seen = self.edit_turn(app)
        self.assertIn(f"[tripwire] the invariants did not run: the tripwire state file {self.state_file()} is unreadable", seen)
        self.assertIn("delete it to start over", seen)
        with self.assertRaisesRegex(ValueError, "is unreadable; delete it to start over"):
            app.registry.commands["tripwire"].run("", self.ctx(cwd=self.repo))
        panel = app.registry.panels["tripwire"].render(self.ctx(cwd=self.repo))
        self.assertIn("tripwire state unreadable", panel)

    def test_an_invariant_that_cannot_start_fails_instead_of_crashing_the_call(self):
        ok, tail = module()._run_wire("true", self.tmp / "missing-folder", dict(module().DEFAULTS))
        self.assertFalse(ok)
        self.assertTrue(tail.startswith("could not run it: "), tail)

    def test_an_invariant_runs_without_the_model_keys_and_without_stdin(self):
        settings = dict(module().DEFAULTS)
        script = 'test -z "$ANTHROPIC_API_KEY$OPENAI_API_KEY$GEMINI_API_KEY$GOOGLE_API_KEY$BRAVE_API_KEY" && ! read -r x'
        with mock.patch.dict(
            os.environ,
            {k: "secret" for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BRAVE_API_KEY")},
        ):
            self.assertEqual(module()._run_wire(script, self.repo, settings), (True, "(no output)"))

    def test_a_timeout_kills_the_whole_process_group_and_returns_promptly(self):
        pidfile = self.tmp / "pid"
        settings = {**module().DEFAULTS, "timeout": 1}
        start = time.monotonic()
        ok, tail = module()._run_wire(f"sleep 30 & echo $! > {pidfile}; wait", self.repo, settings)
        self.assertEqual((ok, tail), (False, "timed out after 1s"))
        self.assertLess(time.monotonic() - start, 10)
        pid = int(pidfile.read_text())
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            os.kill(pid, 9)
            self.fail("the sleep started by the invariant survived its timeout")

    def test_timeout_setting_and_tail_limits_apply(self):
        settings = dict(module().DEFAULTS)
        self.assertEqual(module()._run_wire("seq 1 5; false", self.repo, {**settings, "tail_lines": 2}), (False, "4\n5"))

    def test_git_children_get_no_keys_prompts_or_fsmonitor(self):
        log = self.tmp / "git.log"
        env_log = self.tmp / "env.log"
        self.fake_bin("git", f'#!/bin/sh\necho "$@" > "{log}"\nenv > "{env_log}"\nexit 0\n')
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
            module()._git(self.repo, "status", "--porcelain")
        self.assertEqual(log.read_text().strip(), "-c core.fsmonitor=false status --porcelain")
        env = env_log.read_text()
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertIn("GIT_TERMINAL_PROMPT=0", env)


if __name__ == "__main__":
    unittest.main()
