"""tools/git: real git in temp repositories; a fake ``git`` on PATH for timeout, cancel and environment."""

import os
import subprocess
import time
import unittest
from unittest import mock

from support import ItemTest, have

ITEM = "tools/git.py"
READ = ["git_status", "git_diff", "git_log", "git_show", "git_blame", "git_branch"]
WRITE = ["git_add", "git_commit", "git_switch"]


def sh(repo, *argv):
    return subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True, text=True).stdout


@unittest.skipUnless(have("git"), "needs git")
class GitToolsTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.repo = self.git_repo({"a.txt": "one\ntwo\nthree\n", "src/b.py": "print(1)\n"})

    def call(self, name, registry=None, **input):
        registry = registry or self.load(ITEM)[0]
        return registry.tools[name].run(input, self.ctx(cwd=self.repo))

    def test_flags_read_tools_are_read_only_and_mutating_ones_confirm(self):
        registry, errors = self.load(ITEM)
        self.assertEqual(errors, [])
        for name in READ:
            self.assertTrue(registry.tools[name].read_only and not registry.tools[name].confirm, name)
        for name in WRITE:
            self.assertTrue(registry.tools[name].confirm and not registry.tools[name].read_only, name)
        self.assertEqual(registry.tools["git_switch"].subject_key, "branch")
        for tool in registry.tools.values():
            if tool.read_only:
                self.assertIn("Prefer it over `bash git", tool.description)

    def test_mutations_false_leaves_only_the_read_tools(self):
        registry, _ = self.load(ITEM, mutations=False)
        self.assertEqual(sorted(n for n in registry.tools if n.startswith("git_")), sorted(READ))

    def test_status_diff_log_show_blame_branch(self):
        (self.repo / "a.txt").write_text("one\nTWO\nthree\n")
        self.assertEqual(self.call("git_status"), "## main\n M a.txt\n")
        diff = self.call("git_diff")
        self.assertIn("-two\n+TWO", diff)
        self.assertIn("a.txt | 2 +-", self.call("git_diff", stat=True))
        self.assertEqual(self.call("git_diff", paths=["src/b.py"]), "(no differences)")
        self.assertRegex(self.call("git_log"), r"^[0-9a-f]+ \d{4}-\d\d-\d\d Test initial\n$")
        self.assertIn("src/b.py", self.call("git_show", rev="HEAD", stat=True))
        blame = self.call("git_blame", path="a.txt", start=2, end=2)
        self.assertEqual(len(blame.splitlines()), 1)
        self.assertIn("TWO", blame)
        self.assertIn("* main", self.call("git_branch"))

    def test_options_cannot_be_smuggled_in_as_refs(self):
        pwn = self.tmp / "pwn"
        for name, field, input in (
            ("git_diff", "ref", {"ref": f"--output={pwn}"}),
            ("git_show", "rev", {"rev": f"--output={pwn}"}),
            ("git_log", "ref", {"ref": "--all"}),
            ("git_log", "author", {"author": "-x"}),
            ("git_switch", "branch", {"branch": "-f"}),
        ):
            with self.assertRaisesRegex(ValueError, f"^{field} must not start with '-'$"):
                self.call(name, **input)
        self.assertEqual(self.call("git_diff", paths=[f"--output={pwn}"]), "(no differences)")  # after `--`: a pathspec
        self.assertFalse(pwn.exists())

    def test_outside_a_repository_it_says_how_to_fix_it(self):
        registry, _ = self.load(ITEM)
        with self.assertRaises(ValueError) as caught:
            registry.tools["git_status"].run({}, self.ctx(cwd=self.tmp))
        self.assertEqual(
            str(caught.exception), f"not a git repository: {self.tmp}; run git from the project folder or git init"
        )

    def test_a_failing_command_reports_its_exit_and_stderr(self):
        with self.assertRaisesRegex(RuntimeError, r"^git show failed \(exit 128\): fatal: ambiguous argument 'nope'"):
            self.call("git_show", rev="nope")

    def test_long_output_is_clipped_with_how_to_narrow_the_call(self):
        (self.repo / "big.txt").write_text("x" * 50 + "\n" * 1 + "y\n" * 3000)
        sh(self.repo, "add", "big.txt")
        registry, _ = self.load(ITEM, max_chars=1000)
        out = self.call("git_diff", registry, staged=True)
        self.assertRegex(out, r"\n\[clipped \d+ chars; pass paths, stat=true or a narrower ref\]$")
        self.assertEqual(len(out.split("\n[clipped")[0]), 1000)

    def test_log_is_limited_by_log_max_and_filters(self):
        for i in range(3):
            (self.repo / "a.txt").write_text(f"v{i}\n")
            sh(self.repo, "commit", "-qam", f"change {i}")
        registry, _ = self.load(ITEM, log_max=2)
        self.assertEqual(len(self.call("git_log", registry, n=50).splitlines()), 2)
        self.assertEqual(len(self.call("git_log", registry, grep="change 1").splitlines()), 1)

    def test_add_and_commit_make_a_commit_with_the_message_and_refresh_git(self):
        refreshed = []
        registry, _ = self.load(ITEM, commit_trailer="Co-authored-by: Bot <bot@example.com>")
        ctx = self.ctx(cwd=self.repo, git_refresh=lambda: refreshed.append(1))
        (self.repo / "a.txt").write_text("changed\n")
        (self.repo / "new.txt").write_text("new\n")
        staged = registry.tools["git_add"].run({"paths": ["a.txt"]}, ctx)
        self.assertIn("M  a.txt", staged)
        self.assertIn("?? new.txt", staged)
        out = registry.tools["git_commit"].run({"message": "x", "paths": ["new.txt"]}, ctx)
        self.assertIn("a.txt", out)
        self.assertIn("new.txt", out)
        self.assertEqual(sh(self.repo, "log", "-1", "--format=%s").strip(), "x")
        self.assertIn("Co-authored-by: Bot", sh(self.repo, "log", "-1", "--format=%b"))
        self.assertTrue(refreshed)

    def test_commit_refusals(self):
        with self.assertRaisesRegex(ValueError, "^message is required"):
            self.call("git_commit", message="  ")
        with self.assertRaisesRegex(RuntimeError, r"(?s)^git commit failed \(exit 1\): .*nothing to commit"):
            self.call("git_commit", message="empty")
        with self.assertRaisesRegex(ValueError, "^paths is required"):
            self.call("git_add", paths=[])

    def test_commit_all_stages_tracked_changes_and_hooks_still_run(self):
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho blocked by hook >&2\nexit 1\n")
        hook.chmod(0o755)
        (self.repo / "a.txt").write_text("changed\n")
        with self.assertRaisesRegex(RuntimeError, "blocked by hook"):
            self.call("git_commit", message="x", all=True)
        hook.unlink()
        self.call("git_commit", message="y", all=True)
        self.assertEqual(sh(self.repo, "log", "-1", "--format=%s").strip(), "y")

    def test_switch_creates_and_changes_branches(self):
        out = self.call("git_switch", branch="feature", create=True)
        self.assertTrue(out.startswith("## feature"))
        self.assertEqual(self.call("git_switch", branch="main").splitlines()[0], "## main")


@unittest.skipUnless(have("sh"), "needs sh")
class ProcessTest(ItemTest):
    def test_a_command_that_outlives_the_timeout_is_killed(self):
        self.fake_bin("git", "#!/bin/sh\nsleep 30\n")
        registry, _ = self.load(ITEM, timeout=1)
        start = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "^git timed out after 1s$"):
            registry.tools["git_status"].run({}, self.ctx())
        self.assertLess(time.monotonic() - start, 10)

    def test_the_users_interrupt_kills_the_command(self):
        self.fake_bin("git", "#!/bin/sh\nsleep 30\n")
        registry, _ = self.load(ITEM)
        with self.assertRaisesRegex(RuntimeError, "^interrupted$"):
            registry.tools["git_status"].run({}, self.ctx(cancelled=True))

    def test_the_child_gets_no_api_keys_and_no_prompts(self):
        self.fake_bin("git", '#!/bin/sh\nenv | grep -E "^(ANTHROPIC_API_KEY|BRAVE_API_KEY|GIT_TERMINAL_PROMPT|NO_COLOR)="\n')
        registry, _ = self.load(ITEM)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "secret", "BRAVE_API_KEY": "secret"}):
            out = registry.tools["git_status"].run({}, self.ctx())
        self.assertEqual(sorted(out.split()), ["GIT_TERMINAL_PROMPT=0", "NO_COLOR=1"])

    def test_missing_git_says_how_to_install_it(self):
        registry, _ = self.load(ITEM)
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "empty")}):
            with self.assertRaisesRegex(ValueError, "^git is not installed or not on PATH; install it with brew install git$"):
                registry.tools["git_status"].run({}, self.ctx())


if __name__ == "__main__":
    unittest.main()
