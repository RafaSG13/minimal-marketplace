"""tools/gh: a fake ``gh`` on PATH answers with canned ``--json`` payloads."""

import json
import os
import unittest
from unittest import mock

from support import ItemTest, have

ITEM = "tools/gh.py"
READ = ["gh_pr_view", "gh_pr_diff", "gh_pr_list", "gh_pr_checks", "gh_issue_view", "gh_issue_list", "gh_run_view"]
WRITE = ["gh_pr_comment", "gh_issue_comment", "gh_pr_review", "gh_pr_create"]

PR = {
    "number": 7,
    "title": "Add things",
    "state": "OPEN",
    "isDraft": False,
    "author": {"login": "ana"},
    "baseRefName": "main",
    "headRefName": "feature",
    "reviewDecision": "CHANGES_REQUESTED",
    "url": "https://github.com/o/r/pull/7",
    "statusCheckRollup": [
        {"conclusion": "SUCCESS", "status": "COMPLETED"},
        {"conclusion": "SKIPPED", "status": "COMPLETED"},
        {"conclusion": "FAILURE", "status": "COMPLETED"},
        {"conclusion": "", "status": "IN_PROGRESS"},
        {"state": "SUCCESS"},
    ],
    "files": [{"path": "a.py", "additions": 3, "deletions": 1}, {"path": "b.py", "additions": 0, "deletions": 9}],
    "body": "Does stuff.",
}
DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\ndiff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +0,0 @@\n-z\n"


@unittest.skipUnless(have("sh") and have("python3"), "needs sh and python3")
class GhTest(ItemTest):
    def tool(self, name, outputs=None, input=None, **fake):
        self.cli = self.fake_cli("gh", outputs, **fake)
        self.registry, errors = self.load(ITEM, **getattr(self, "settings", {}))
        self.assertEqual(errors, [])
        return self.registry.tools[name].run(input or {}, self.ctx())

    def test_flags(self):
        registry, _ = self.load(ITEM)
        for name in READ:
            self.assertTrue(registry.tools[name].read_only is True and not registry.tools[name].confirm, name)
            self.assertIn("Prefer it over `bash gh", registry.tools[name].description)
        for name in WRITE:
            self.assertTrue(registry.tools[name].confirm is True and not registry.tools[name].read_only, name)

    def test_pr_view_renders_the_summary(self):
        out = self.tool("gh_pr_view", {"pr-view": json.dumps(PR)}, {"number": 7})
        self.assertEqual(
            out,
            "#7 Add things [OPEN] by ana\n"
            "main <- feature  review: CHANGES_REQUESTED\n"
            "https://github.com/o/r/pull/7\n"
            "checks: 3 passing, 1 failing, 1 pending\n"
            "files (2):\n  a.py +3 -1\n  b.py +0 -9\n\nDoes stuff.",
        )
        call = self.cli.calls()[0]
        self.assertEqual(call[:3], ["pr", "view", "7"])
        self.assertEqual(call[3], "--json")

    def test_pr_view_without_number_uses_the_current_branch_and_repo_adds_r(self):
        self.tool("gh_pr_view", {"pr-view": json.dumps(PR)}, {"repo": "o/r"})
        self.assertEqual(self.cli.calls()[0][:2], ["pr", "view"])
        self.assertEqual(self.cli.calls()[0][-2:], ["-R", "o/r"])
        self.assertEqual(self.cli.calls()[0][2], "--json")
        for bad in ("o", "--help/x", "a/b/c", "a b/c"):
            with self.assertRaisesRegex(ValueError, "^repo must look like owner/name$"):
                self.registry.tools["gh_pr_view"].run({"repo": bad}, self.ctx())

    def test_pr_diff_keeps_one_files_section(self):
        out = self.tool("gh_pr_diff", {"pr-diff": DIFF}, {"number": 7, "path": "b.py"})
        self.assertEqual(out, DIFF[DIFF.index("diff --git a/b.py") :])
        self.assertEqual(self.cli.calls(), [["pr", "diff", "7", "--color=never"]])
        with self.assertRaisesRegex(ValueError, r"^no section for c.py in the diff; files in it: a.py, b.py$"):
            self.registry.tools["gh_pr_diff"].run({"path": "c.py"}, self.ctx())
        self.assertEqual(self.tool("gh_pr_diff", {"pr-diff": ""}, {}), "(empty diff)")

    def test_pr_diff_is_clipped_with_the_hint(self):
        out = self.tool("gh_pr_diff", {"pr-diff": "+x\n" * 2000}, {"max_chars": 1000})
        self.assertRegex(out, r"\n\[clipped 5000 chars; pass path to read one file's diff\]$")

    def test_pr_list_and_issue_list_lines_and_validation(self):
        prs = [{"number": 1, "title": "T", "author": {"login": "bo"}, "state": "OPEN", "headRefName": "h", "isDraft": True}]
        self.assertEqual(self.tool("gh_pr_list", {"pr-list": json.dumps(prs)}, {"author": "bo", "limit": 500}), "#1 [open, draft] T (bo, h)")
        call = self.cli.calls()[0]
        self.assertEqual(call[:7], ["pr", "list", "--state", "open", "--limit", "100", "--author=bo"])
        with self.assertRaisesRegex(ValueError, "^author must not start with '-'$"):
            self.registry.tools["gh_pr_list"].run({"author": "-x"}, self.ctx())
        with self.assertRaisesRegex(ValueError, "^state must be open, closed, merged or all$"):
            self.registry.tools["gh_pr_list"].run({"state": "x"}, self.ctx())
        issues = [{"number": 3, "title": "Bug", "state": "OPEN", "author": {"login": "cy"}, "labels": [{"name": "bug"}]}]
        self.assertEqual(self.tool("gh_issue_list", {"issue-list": json.dumps(issues)}), "#3 [open] Bug (cy) {bug}")

    def test_checks_accept_the_pending_and_failing_exit_codes(self):
        checks = [{"name": "unit", "state": "FAILURE", "link": "http://x", "workflow": "ci"}]
        out = self.tool("gh_pr_checks", {"pr-checks": json.dumps(checks)}, {"number": 7}, exit=8)
        self.assertEqual(out, "FAILURE    ci / unit  http://x")
        self.assertEqual(self.cli.calls()[0], ["pr", "checks", "7", "--json", "name,state,link,workflow"])

    def test_issue_view_with_comments(self):
        issue = {
            "number": 3,
            "title": "Bug",
            "state": "OPEN",
            "author": {"login": "cy"},
            "labels": [],
            "url": "u",
            "body": "It breaks.",
            "comments": [{"author": {"login": "di"}, "body": "me too"}],
        }
        out = self.tool("gh_issue_view", {"issue-view": json.dumps(issue)}, {"number": 3, "comments": True})
        self.assertTrue(out.endswith("It breaks.\n\n--- di:\nme too"), out)
        self.assertIn("comments", self.cli.calls()[0][-1])

    def test_run_view_picks_the_latest_run_of_the_branch_and_cuts_the_log_from_the_start(self):
        repo = self.git_repo({"a": "a"})
        self.cli = self.fake_cli("gh", {"run-list": json.dumps([{"databaseId": 99}]), "run-view": "start\n" + "e" * 2000 + "\nthe error\n"})
        registry, _ = self.load(ITEM, max_chars=1000)
        out = registry.tools["gh_run_view"].run({"failed_only": True}, self.ctx(cwd=repo))
        self.assertEqual(self.cli.calls()[0][:6], ["run", "list", "--limit", "1", "--json", "databaseId,status,conclusion,name"])
        self.assertEqual(self.cli.calls()[0][-2:], ["--branch", "main"])
        self.assertEqual(self.cli.calls()[1], ["run", "view", "99", "--log-failed"])
        self.assertTrue(out.startswith("e") and "the error\n\n[clipped" in out and out.endswith("pass failed_only=true]"), out[-200:])

    def test_not_signed_in_says_how_to_fix_it(self):
        with self.assertRaises(RuntimeError) as caught:
            self.tool("gh_pr_list", stderr="To get started with GitHub CLI, please run:  gh auth login\n", exit=4)
        self.assertEqual(str(caught.exception), "gh is not authenticated; run `gh auth login`")
        with self.assertRaisesRegex(RuntimeError, r"^gh pr view failed \(exit 1\): no pull requests found$"):
            self.tool("gh_pr_view", stderr="no pull requests found\n", exit=1)

    def test_missing_gh_gives_the_install_hint(self):
        registry, _ = self.load(ITEM)
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "empty")}):
            with self.assertRaises(ValueError) as caught:
                registry.tools["gh_pr_list"].run({}, self.ctx())
        self.assertEqual(
            str(caught.exception),
            "gh is not installed or not on PATH; install it with brew install gh, then run `gh auth login`",
        )

    def test_comment_bodies_go_on_stdin_never_in_argv(self):
        body = "line 1 $(rm -rf /) \"quoted\"\nline 2"
        self.tool("gh_pr_comment", {}, {"number": 7, "body": body})
        self.assertEqual(self.cli.calls(), [["pr", "comment", "7", "-F", "-"]])
        self.assertEqual(self.cli.stdin_text(), body)
        self.tool("gh_issue_comment", {}, {"number": 3, "body": "hi"})
        self.assertEqual(self.cli.calls()[-1], ["issue", "comment", "3", "-F", "-"])
        self.tool("gh_pr_review", {}, {"action": "request_changes", "body": "fix it"})
        self.assertEqual(self.cli.calls()[-1], ["pr", "review", "--request-changes", "-F", "-"])
        self.assertEqual(self.cli.stdin_text(), "fix it")
        with self.assertRaisesRegex(ValueError, "^body is required"):
            self.registry.tools["gh_pr_comment"].run({"body": "  "}, self.ctx())
        with self.assertRaisesRegex(ValueError, "^action must be approve, request_changes or comment$"):
            self.registry.tools["gh_pr_review"].run({"action": "merge", "body": "x"}, self.ctx())

    def test_pr_create_keeps_a_dash_title_attached_and_sends_the_body_on_stdin(self):
        out = self.tool("gh_pr_create", {"pr-create": "https://github.com/o/r/pull/9\n"}, {"title": "--web", "body": "B", "base": "main", "draft": True})
        self.assertEqual(out, "https://github.com/o/r/pull/9")
        self.assertEqual(self.cli.calls(), [["pr", "create", "--title=--web", "--body-file", "-", "--base=main", "--draft"]])
        self.assertEqual(self.cli.stdin_text(), "B")


if __name__ == "__main__":
    unittest.main()
