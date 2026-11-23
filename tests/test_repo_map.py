"""tools/repo_map: a temp project (git and plain)."""

import unittest

from support import ItemTest, have

ITEM = "tools/repo_map.py"

PY = '''import os

class Base:
    pass

class Service(Base, object):
    def run(self, a, b=1, *rest, key, **kw):
        pass

    async def stop(self):
        pass

def helper(x, y):
    def inner():
        pass

async def main():
    pass
'''


class RepoMapTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.proj = self.tmp / "proj"
        for rel, text in {
            "app/service.py": PY,
            "app/broken.py": "def (:\n",
            "web/index.ts": "export class Widget {}\nexport default async function render() {}\nexport interface Props {}\nconst x = 1;\n",
            "svc/main.go": "package main\n\nfunc main() {}\n\ntype Server struct{}\n\nfunc (s *Server) Start() {}\n",
            "lib/lib.rs": "pub struct Point;\nimpl Point {}\npub async fn go() {}\nfn private() {}\n",
            "j/App.java": "public class App {}\ninterface Shape {}\n",
            "r/thing.rb": "class Thing\n  def work\n  end\nend\n",
            "README.md": "# hi\n",
            "node_modules/x/index.js": "function hidden() {}\n",
        }.items():
            path = self.proj / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def call(self, registry=None, **input):
        registry = registry or self.load(ITEM)[0]
        return registry.tools["repo_map"].run(input, self.ctx(cwd=self.proj))

    def test_the_tool_is_read_only_and_says_when_to_use_it(self):
        tool = self.load(ITEM)[0].tools["repo_map"]
        self.assertTrue(tool.read_only is True and not tool.confirm)
        self.assertIn("prefer it over many glob and grep calls", tool.description)

    def test_python_symbols_with_parameters_and_nesting(self):
        out = self.call(path="app")
        self.assertIn(
            "app/service.py:\n  L3 class Base\n  L6 class Service(Base, object)\n    L7 def run(a, b, *rest, key, **kw)\n"
            "    L10 async def stop()\n  L13 def helper(x, y)\n  L17 async def main()",
            out,
        )
        self.assertIn("app/broken.py:\n", out)  # a file that does not parse is listed without symbols

    def test_other_languages_by_regex(self):
        out = self.call()
        self.assertIn("web/index.ts:\n  L1 class Widget\n  L2 function render\n  L3 interface Props\n", out)
        self.assertIn("svc/main.go:\n  L3 func main\n  L5 struct Server\n    L7 func Server.Start\n", out)
        self.assertIn("lib/lib.rs:\n  L1 struct Point\n  L2 impl Point\n  L3 fn go\n  L4 fn private\n", out)
        self.assertIn("j/App.java:\n  L1 class App\n  L2 interface Shape\n", out)
        self.assertIn("r/thing.rb:\n  L1 class Thing\n    L2 def work\n", out)

    def test_other_files_are_counted_and_ignored_folders_are_skipped(self):
        out = self.call()
        self.assertNotIn("hidden", out)
        self.assertNotIn("node_modules", out)
        self.assertTrue(out.endswith("(+1 other files without symbols)"), out[-80:])

    def test_focus_lists_matching_files_first(self):
        out = self.call(focus=["web/*", "r"])
        order = [line for line in out.splitlines() if line.endswith(":")]
        self.assertEqual(order[:2], ["r/thing.rb:", "web/index.ts:"])
        self.assertEqual(order[2:], sorted(order[2:]))

    def test_cut_at_max_chars_says_how_to_narrow(self):
        out = self.call(max_chars=500)
        self.assertRegex(out, r"\n\[\d+ more files; pass path= or focus= to narrow the map\]$")
        self.assertLessEqual(len(out.split("\n[")[0]), 500)

    @unittest.skipUnless(have("git"), "needs git")
    def test_in_a_git_repository_ignored_files_are_left_out(self):
        repo = self.git_repo({"keep.py": "def kept(): pass\n", ".gitignore": "gen.py\n"})
        (repo / "gen.py").write_text("def generated(): pass\n")
        (repo / "new.py").write_text("def fresh(): pass\n")
        out = self.load(ITEM)[0].tools["repo_map"].run({}, self.ctx(cwd=repo))
        self.assertEqual(out, "keep.py:\n  L1 def kept()\nnew.py:\n  L1 def fresh()\n(+1 other files without symbols)")

    def test_errors_say_what_to_pass(self):
        with self.assertRaisesRegex(ValueError, r"^\.\./x is outside the working folder"):
            self.call(path="../x")
        with self.assertRaisesRegex(ValueError, "^README.md is not a folder"):
            self.call(path="README.md")
        with self.assertRaisesRegex(ValueError, "^focus must be a list"):
            self.call(focus="web")
        self.assertTrue(self.call(path="web").startswith("web/index.ts:"))
        (self.tmp / "empty").mkdir()
        self.assertTrue(self.load(ITEM)[0].tools["repo_map"].run({}, self.ctx(cwd=self.tmp / "empty")).startswith("(no source files found"))


if __name__ == "__main__":
    unittest.main()
