"""scope_fence: the guard blocks edits outside the fence and over the budget, and blocks (not allows) when it cannot tell."""

import contextlib
import importlib.util
import io
import os
import shutil
import unittest
from unittest import mock

from minimal import config

from support import ROOT, ItemTest, have, text_reply, tool_reply

ITEM = "extensions/scope_fence.py"


def module():
    spec = importlib.util.spec_from_file_location("scope_fence_under_test", ROOT / ITEM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(have("git"), "git is not installed")
class FenceTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.repo = self.git_repo({"src/a.py": "one\ntwo\n", "docs/readme.md": "doc\n"})

    def state_file(self, cwd=None):
        return config.project_data_dir(str(cwd or self.repo)) / "scope_fence" / "state.json"

    def app(self, replies=(), cwd=None, **settings):
        return self.make_app(ITEM, list(replies), cwd=cwd or self.repo, settings=settings or None)

    def command(self, app, line):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            app.run_command(line)
        return out.getvalue()

    def call(self, app, name, args):
        """The tool result the model got for one call of ``name`` (the item's guard runs before the tool)."""
        app.provider.replies[:] = [tool_reply(name, args), text_reply("done")]
        self.run_turn(app, "go")
        return app.messages[-2]["content"][0]

    def test_a_write_outside_the_fence_is_blocked_with_how_to_widen_it_and_inside_runs(self):
        app = self.app()
        self.assertIn("Fence: src/**", self.command(app, "/fence src"))
        blocked = self.call(app, "write", {"path": "docs/new.md", "content": "x"})
        self.assertTrue(blocked["is_error"])
        self.assertIn(
            "docs/new.md is outside the fence (src/**). Do not work around it: tell the user why you need this file "
            "so they can widen the fence with /fence.",
            blocked["content"],
        )
        self.assertFalse((self.repo / "docs" / "new.md").exists())
        ok = self.call(app, "write", {"path": "src/b.py", "content": "x"})
        self.assertFalse(ok.get("is_error"))
        self.assertEqual((self.repo / "src" / "b.py").read_text(), "x")

    def test_a_symlink_inside_the_fence_cannot_reach_outside_it(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (self.repo / "src" / "link").symlink_to(outside)
        app = self.app()
        self.command(app, "/fence src")
        result = self.call(app, "write", {"path": "src/link/evil.txt", "content": "x"})
        self.assertTrue(result["is_error"])
        self.assertIn("is outside the fence", result["content"])
        self.assertFalse((outside / "evil.txt").exists())

    def test_the_outside_message_is_a_setting(self):
        app = self.app(outside_message="NO {path} ({globs})")
        self.command(app, "/fence src")
        self.assertEqual(self.call(app, "write", {"path": "docs/x.md", "content": "x"})["content"], "Error: NO docs/x.md (src/**)")

    def test_a_used_up_diff_budget_blocks_edits_with_the_counts(self):
        app = self.app()
        self.command(app, "/fence src --lines 2")
        (self.repo / "src" / "a.py").write_text("one\nTWO\nthree\n")  # 1 removed + 2 added = 3 changed lines
        blocked = self.call(app, "edit", {"path": "src/a.py", "old_text": "one", "new_text": "uno"})
        self.assertTrue(blocked["is_error"])
        self.assertIn(
            "diff budget used up (3/2 changed lines). Stop editing, summarise what is done and what remains.",
            blocked["content"],
        )
        self.assertEqual((self.repo / "src" / "a.py").read_text(), "one\nTWO\nthree\n")

    def test_a_budget_that_cannot_be_measured_blocks_instead_of_allowing(self):
        plain = self.tmp / "plain"  # not a git repository: `git diff HEAD` fails
        (plain / "src").mkdir(parents=True)
        app = self.app(cwd=plain)
        self.command(app, "/fence src --lines 5")
        blocked = self.call(app, "write", {"path": "src/a.py", "content": "x"})
        self.assertTrue(blocked["is_error"])
        self.assertIn("the diff budget (5 lines) cannot be measured: `git diff HEAD` failed in", blocked["content"])
        self.assertIn("Tell the user to make a first commit or to run /fence again without --lines.", blocked["content"])
        self.assertFalse((plain / "src" / "a.py").exists())
        # without a budget the same folder needs no git at all
        self.command(app, "/fence src")
        self.assertFalse(self.call(app, "write", {"path": "src/a.py", "content": "x"}).get("is_error"))

    def test_an_unreadable_state_file_blocks_edits_until_the_fence_is_removed(self):
        app = self.app()
        self.command(app, "/fence src")
        self.state_file().write_text("{not json")
        blocked = self.call(app, "write", {"path": "src/b.py", "content": "x"})
        self.assertTrue(blocked["is_error"])
        self.assertIn(f"the scope fence state {self.state_file()} is unreadable", blocked["content"])
        self.assertIn("tell the user to run /fence off, or /fence <paths> to set a new fence.", blocked["content"])
        self.assertFalse((self.repo / "src" / "b.py").exists())
        self.assertIn("unreadable", app.registry.panels["fence"].render(self.ctx(cwd=self.repo)))
        self.assertIn("Fence removed.", self.command(app, "/fence off"))
        self.assertFalse(self.call(app, "write", {"path": "docs/free.md", "content": "x"}).get("is_error"))

    def test_a_state_file_that_is_not_a_fence_blocks_too(self):
        app = self.app()
        self.command(app, "/fence src")
        self.state_file().write_text('{"globs": "src/**"}')
        self.assertIn("is unreadable (not a fence)", self.call(app, "write", {"path": "src/b.py", "content": "x"})["content"])

    def test_a_bash_call_that_changes_files_outside_the_fence_is_noted(self):
        app = self.app()
        self.command(app, "/fence src")
        out = self.call(app, "bash", {"command": "touch stray.txt"})
        self.assertIn("[fence] this command changed files outside the fence: stray.txt. Revert them", out["content"])
        self.assertIn("stray.txt", app.registry.panels["fence"].render(self.ctx(cwd=self.repo)))

    def test_disabled_registers_nothing_and_the_state_lives_outside_the_repository(self):
        self.assertNotIn("fence", self.app(enabled=False).registry.commands)
        app = self.app(enabled=True)
        self.command(app, "/fence src")
        self.assertTrue(self.state_file().is_file())
        self.assertTrue(self.state_file().is_relative_to(self.tmp / "home"))
        self.assertEqual(sorted(p.name for p in self.repo.iterdir() if p.name != ".git"), ["docs", "src"])


@unittest.skipUnless(have("git"), "git is not installed")
class GitChildTest(ItemTest):
    def test_git_runs_without_the_keys_prompts_or_the_repositorys_fsmonitor(self):
        log = self.tmp / "git.log"
        self.fake_bin("git", f'#!/bin/sh\n{{ echo "$@"; env; }} > "{log}"\nexit 0\n')
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k1", "BRAVE_API_KEY": "k2", "OPENAI_API_KEY": "k3"}):
            self.assertEqual(module()._git(self.tmp, "status", "--porcelain"), "")
        lines = log.read_text().splitlines()
        self.assertEqual(lines[0], "-c core.fsmonitor=false status --porcelain")
        env = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in lines[1:] if "=" in line}
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BRAVE_API_KEY"):
            self.assertNotIn(name, env)
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(env["GIT_PAGER"], "cat")

    def test_a_missing_git_means_none_not_a_crash(self):
        with mock.patch.dict(os.environ, {"PATH": ""}):
            self.assertIsNone(module()._git(self.tmp, "status"))


if __name__ == "__main__":
    unittest.main()
