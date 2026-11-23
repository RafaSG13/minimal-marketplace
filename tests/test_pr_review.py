"""pr_review: reviewer agents scripted per lens; real git repo; a fake ``gh`` for pull requests."""

import json
import re
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from minimal.providers.base import Reply

from support import ItemTest, have

ITEM = "extensions/pr_review.py"
A_PY = "def f(x):\n    return x\n\n\ndef g():\n    pass\n"
A_PY_NEW = "def f(x):\n    return x.value\n\n\ndef g():\n    pass\n\n\ndef h():\n    return 1\n"


def reply(findings):
    return "Done.\n```json\n" + json.dumps(findings) + "\n```"


FINDING = {"file": "a.py", "line": 2, "severity": "blocker", "title": "Null deref", "detail": "x may be None", "suggestion": "check it"}


class LensProvider:
    """Answers each reviewer with the reply scripted for its lens (found in the system prompt)."""

    name = "fake"

    def __init__(self, by_lens):
        self.by_lens = by_lens
        self.requests = []

    def stream(self, **kw):
        lens = re.search(r"lens: (\w+)\.", kw["system"]).group(1)
        self.requests.append(SimpleNamespace(lens=lens, tools=[t["name"] for t in kw["tools"]], prompt=kw["messages"][0]["content"]))
        return Reply(content=[{"type": "text", "text": self.by_lens[lens]}], stop_reason="end_turn")


@unittest.skipUnless(have("git"), "needs git")
class ReviewTest(ItemTest):
    BY_LENS = {
        "correctness": reply([FINDING, {**FINDING, "line": 99, "title": "Off in the void", "severity": "major"}]),
        "security": reply([{**FINDING, "title": "NULL DEREF", "severity": "major"}, {"file": "a.py", "line": 50, "severity": "minor", "title": "Naming", "detail": "d", "suggestion": ""}]),
        "tests": "Looks fine to me, no block.",
        "maintainability": reply([]),
    }

    def setUp(self):
        super().setUp()
        self.repo = self.git_repo({"a.py": A_PY})
        subprocess.run(["git", "switch", "-qc", "feature"], cwd=self.repo, check=True)
        (self.repo / "a.py").write_text(A_PY_NEW)
        subprocess.run(["git", "commit", "-qam", "change"], cwd=self.repo, check=True)
        self.frontend = mock.Mock()
        self.frontend.ask.return_value = True

    def app(self, by_lens=None, **settings):
        app = self.make_app(ITEM, [], cwd=self.repo, settings=settings or None, frontend=self.frontend)
        app.provider = self.provider = LensProvider(by_lens or self.BY_LENS)
        return app

    def review(self, app, **input):
        return app.registry.tools["review_changes"].run(input, app.context)

    def test_report_is_sorted_deduplicated_and_separates_unanchored_and_unparsed(self):
        report = self.review(self.app(max_parallel=1))
        self.assertTrue(report.startswith("# Review: main...HEAD\n\nFindings: 1 blocker, 1 major, 1 minor, 0 nit\n"), report[:120])
        body = report.split("## Unanchored")[0]
        self.assertEqual(body.count("Null deref"), 1)  # the security lens' "NULL DEREF" is the same finding
        self.assertIn("**blocker** a.py:2 Null deref\nx may be None\nSuggestion: check it", body)
        unanchored = report.split("## Unanchored")[1].split("## Not parsed")[0]
        self.assertLess(unanchored.index("a.py:99"), unanchored.index("a.py:50"))  # major before minor
        self.assertIn("(the file or line is not part of the diff)", unanchored)
        not_parsed = report.split("## Not parsed")[1]
        self.assertIn("- tests: no ```json block in the reply\nLooks fine to me, no block.", not_parsed)
        self.assertNotIn("Partially reviewed", report)

    def test_the_report_is_saved_in_the_project_data_folder(self):
        report = self.review(self.app())
        path = re.search(r"Saved to (.+\.md)", report).group(1)
        self.assertRegex(path, r"/reviews/\d{8}-\d{6}\.md$")
        self.assertIn("**blocker** a.py:2 Null deref", Path(path).read_text())

    def test_reviewers_only_get_read_only_tools_and_the_chunk_as_prompt(self):
        app = self.app()
        self.review(app)
        offered = {t for r in self.provider.requests for t in r.tools}
        self.assertTrue({"read", "grep", "glob"} <= offered)
        self.assertFalse(offered & {"bash", "write", "edit", "review_changes", "reload_extensions"}, offered)
        self.assertEqual(sorted(r.lens for r in self.provider.requests), sorted(self.BY_LENS))
        self.assertIn("diff --git a/a.py b/a.py", self.provider.requests[0].prompt)

    def test_lenses_input_overrides_the_setting_and_large_files_are_partial(self):
        app = self.app(chunk_chars=2000)
        (self.repo / "big.py").write_text("x = 1\n" * 1000)
        subprocess.run(["git", "add", "big.py"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "big"], cwd=self.repo, check=True)
        report = self.review(app, lenses=["correctness"])
        self.assertEqual([r.lens for r in self.provider.requests], ["correctness", "correctness"])
        self.assertIn("## Partially reviewed\n(too large for one reviewer; cut to chunk_chars)\n\n- big.py", report)

    def test_no_changes_and_staged_and_range_targets(self):
        app = self.app()
        subprocess.run(["git", "switch", "-q", "main"], cwd=self.repo, check=True)
        self.assertEqual(self.review(app), "no changes to review")
        self.assertEqual(self.provider.requests, [])
        (self.repo / "a.py").write_text(A_PY_NEW)
        subprocess.run(["git", "add", "a.py"], cwd=self.repo, check=True)
        report = self.review(app, target="--staged", lenses=["correctness"])
        self.assertTrue(report.startswith("# Review: staged changes"))
        report = self.review(app, target="main..feature", lenses=["maintainability"])
        self.assertTrue(report.startswith("# Review: main...feature"))
        with self.assertRaisesRegex(ValueError, "^target must look like <base>..<head>"):
            self.review(app, target="--output=x..y")

    def test_the_flags_of_the_tool(self):
        registry, errors = self.load(ITEM)
        self.assertEqual(errors, [])
        tool = registry.tools["review_changes"]
        self.assertFalse(tool.read_only)
        self.assertFalse(tool.confirm)
        self.assertIn("SPENDS MODEL TOKENS", tool.description)
        self.assertIn("review", registry.commands)

    @unittest.skipUnless(have("sh") and have("python3"), "needs sh and python3")
    def test_a_pull_request_review_posts_only_anchored_findings_after_asking(self):
        diff = subprocess.run(["git", "diff", "main...HEAD"], cwd=self.repo, capture_output=True, text=True).stdout
        cli = self.fake_cli("gh", {"pr-diff": diff, "repo-view": json.dumps({"nameWithOwner": "o/r"})})
        report = self.review(self.app(), target="7")
        self.assertTrue(report.startswith("# Review: pull request #7"))
        self.frontend.ask.assert_called_once_with("Post 1 findings as a review on PR #7?")
        calls = cli.calls()
        self.assertEqual(calls[0], ["pr", "diff", "7", "--color=never"])
        self.assertEqual(calls[1], ["repo", "view", "--json", "nameWithOwner"])
        self.assertEqual(calls[2], ["api", "repos/o/r/pulls/7/reviews", "-X", "POST", "--input", "-"])
        body = json.loads(cli.stdin_text())
        self.assertEqual(body["event"], "COMMENT")
        self.assertEqual([(c["path"], c["line"], c["side"]) for c in body["comments"]], [("a.py", 2, "RIGHT")])
        self.assertTrue(report.rstrip().endswith("Posted 1 findings to PR #7."))

    @unittest.skipUnless(have("sh") and have("python3"), "needs sh and python3")
    def test_declining_or_post_never_posts_nothing(self):
        diff = subprocess.run(["git", "diff", "main...HEAD"], cwd=self.repo, capture_output=True, text=True).stdout
        cli = self.fake_cli("gh", {"pr-diff": diff})
        self.frontend.ask.return_value = False
        self.assertTrue(self.review(self.app(), target="7").rstrip().endswith("Not posted (declined)."))
        self.assertEqual([c[0] for c in cli.calls()], ["pr"])
        self.frontend.ask.reset_mock()
        self.review(self.app(post="never"), target="7")
        self.frontend.ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
