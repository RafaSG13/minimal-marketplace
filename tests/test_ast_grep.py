"""tools/ast_grep: a fake ``ast-grep`` on PATH."""

import json
import os
import unittest
from unittest import mock

from support import ItemTest, have

ITEM = "tools/ast_grep.py"


def match(file, line, column, text):
    return json.dumps({"text": text, "file": file, "lines": text, "range": {"start": {"line": line, "column": column}, "end": {"line": line, "column": column + 3}}, "language": "Python"})


@unittest.skipUnless(have("sh") and have("python3"), "needs sh and python3")
class AstGrepTest(ItemTest):
    def tool(self, name, outputs=None, input=None, **fake):
        self.cli = self.fake_cli("ast-grep", outputs, **fake)
        self.registry, errors = self.load(ITEM, **getattr(self, "settings", {}))
        self.assertEqual(errors, [])
        return self.registry.tools[name].run(input or {}, self.ctx())

    def test_flags_search_read_only_rewrite_decided_per_call(self):
        registry, _ = self.load(ITEM)
        search, rewrite = registry.tools["ast_grep_search"], registry.tools["ast_grep_rewrite"]
        self.assertTrue(search.read_only is True and not search.confirm)
        ctx = self.ctx()
        self.assertEqual((rewrite.read_only({}, ctx), rewrite.confirm({}, ctx)), (True, False))
        self.assertEqual((rewrite.read_only({"apply": False}, ctx), rewrite.confirm({"apply": False}, ctx)), (True, False))
        self.assertEqual((rewrite.read_only({"apply": True}, ctx), rewrite.confirm({"apply": True}, ctx)), (False, True))
        self.assertIn("Prefer it over grep", search.description)

    def test_search_lists_matches_with_one_based_positions(self):
        stream = "\n".join([match("a.py", 0, 4, "print(1)\nmore"), match("b/c.py", 9, 0, "print(2)")])
        out = self.tool("ast_grep_search", {"run": stream}, {"pattern": "print($A)", "lang": "python", "paths": ["a.py", "b"]})
        self.assertEqual(out, "a.py:1:5  print(1)\nb/c.py:10:1  print(2)")
        self.assertEqual(self.cli.calls(), [["run", "--pattern=print($A)", "--lang=python", "--json=stream", "--", "a.py", "b"]])

    def test_a_pattern_that_looks_like_an_option_stays_attached(self):
        self.tool("ast_grep_search", {"run": ""}, {"pattern": "--help"})
        self.assertEqual(self.cli.calls(), [["run", "--pattern=--help", "--json=stream"]])

    def test_limit_and_no_matches(self):
        stream = "\n".join(match("a.py", i, 0, f"x{i}") for i in range(5))
        out = self.tool("ast_grep_search", {"run": stream}, {"pattern": "x", "limit": 2})
        self.assertEqual(out.splitlines()[-1], "[3 more matches; narrow paths or the pattern, or raise limit]")
        self.assertEqual(self.tool("ast_grep_search", {"run": ""}, {"pattern": "x"}), "(no matches)")

    def test_rewrite_previews_by_default_and_applies_on_request(self):
        diff = "a.py\n1  | -print(1)\n   | +log(1)\n"
        out = self.tool("ast_grep_rewrite", {"run": diff}, {"pattern": "print($A)", "rewrite": "log($A)"})
        self.assertEqual(out, diff + "\n[preview only: pass apply=true to write these changes]")
        self.assertEqual(self.cli.calls(), [["run", "--pattern=print($A)", "--rewrite=log($A)"]])
        refreshed = []
        registry, _ = self.load(ITEM)
        ctx = self.ctx(git_refresh=lambda: refreshed.append(1))
        out = registry.tools["ast_grep_rewrite"].run({"pattern": "print($A)", "rewrite": "log($A)", "apply": True}, ctx)
        self.assertEqual(self.cli.calls()[-1], ["run", "--pattern=print($A)", "--rewrite=log($A)", "--update-all"])
        self.assertEqual((out, refreshed), (diff.strip(), [1]))  # what ast-grep printed

    def test_validation_and_failures(self):
        self.tool("ast_grep_search", {"run": ""}, {"pattern": "x"})
        tool = self.registry.tools["ast_grep_search"]
        for input, text in (
            ({}, "pattern is required"),
            ({"pattern": "x", "lang": "py thon"}, "lang must be a language name"),
            ({"pattern": "x", "paths": ["../out"]}, r"\.\./out is outside the working folder"),
            ({"pattern": "x", "paths": "a"}, "paths must be a list"),
        ):
            with self.assertRaisesRegex(ValueError, text):
                tool.run(input, self.ctx())
        with self.assertRaisesRegex(ValueError, "^rewrite is required"):
            self.registry.tools["ast_grep_rewrite"].run({"pattern": "x"}, self.ctx())
        with self.assertRaisesRegex(RuntimeError, r"^ast-grep failed \(exit 2\): Error: Cannot parse pattern$"):
            self.tool("ast_grep_search", stderr="Error: Cannot parse pattern\n", exit=2, input={"pattern": "("})

    def test_missing_binary_gives_the_install_hint(self):
        registry, _ = self.load(ITEM)
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "empty")}):
            with self.assertRaises(ValueError) as caught:
                registry.tools["ast_grep_search"].run({"pattern": "x"}, self.ctx())
        self.assertEqual(str(caught.exception), "ast-grep is not installed or not on PATH; install it with brew install ast-grep")


if __name__ == "__main__":
    unittest.main()
