"""tools/fs: real folders in a temp directory."""

import os
import re
import unittest
from pathlib import Path

from support import ItemTest, have

ITEM = "tools/fs.py"
READ = ["fs_tree", "fs_stat", "fs_read_many", "fs_find"]
WRITE = {"fs_mkdir": "path", "fs_move": "src", "fs_copy": "src", "fs_delete": "path"}


class FsTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.work = self.tmp / "work"
        (self.work / "src" / "pkg").mkdir(parents=True)
        (self.work / "node_modules" / "x").mkdir(parents=True)
        (self.work / "a.txt").write_text("alpha\n")
        (self.work / "src" / "m.py").write_text("print(1)\n")
        (self.work / "src" / "pkg" / "deep.py").write_text("x = 1\n")
        (self.work / "node_modules" / "x" / "i.js").write_text("1")

    def call(self, tool, registry=None, **input):
        registry = registry or self.load(ITEM)[0]
        return registry.tools[tool].run(input, self.ctx(cwd=self.work))

    def test_flags_and_subject_keys(self):
        registry, errors = self.load(ITEM)
        self.assertEqual(errors, [])
        for name in READ:
            self.assertTrue(registry.tools[name].read_only and not registry.tools[name].confirm, name)
            self.assertIn("Prefer it over `bash`", registry.tools[name].description)
        for name, key in WRITE.items():
            tool = registry.tools[name]
            self.assertTrue(tool.confirm and not tool.read_only and tool.subject_key == key, name)

    def test_tree_walk_skips_ignored_folders_and_honours_depth(self):
        out = self.call("fs_tree")
        self.assertEqual(out, "./\n  src/\n    pkg/\n      deep.py\n    m.py\n  a.txt")
        self.assertEqual(self.call("fs_tree", depth=1), "./\n  src/\n  a.txt")
        self.assertEqual(self.call("fs_tree", dirs_only=True), "./\n  src/\n    pkg/")
        self.assertIn("  node_modules/", self.call("fs_tree", self.load(ITEM, ignore=[])[0]))

    def test_tree_truncates_with_a_note(self):
        out = self.call("fs_tree", max_entries=2)
        self.assertEqual(out.splitlines()[-1], "[3 more entries; narrow path or depth]")

    @unittest.skipUnless(have("git"), "needs git")
    def test_tree_in_a_repository_lists_tracked_and_untracked_but_not_ignored_files(self):
        repo = self.git_repo({"keep.py": "k", ".gitignore": "secret.txt\nbuild/\n", "pkg/mod.py": "m"})
        (repo / "secret.txt").write_text("s")
        (repo / "build").mkdir()
        (repo / "build" / "o.bin").write_text("o")
        (repo / "new.txt").write_text("n")
        out = self.load(ITEM)[0].tools["fs_tree"].run({}, self.ctx(cwd=repo))
        self.assertEqual(out, "./\n  pkg/\n    mod.py\n  .gitignore\n  keep.py\n  new.txt")
        sub = self.load(ITEM)[0].tools["fs_tree"].run({"path": "pkg"}, self.ctx(cwd=repo))
        self.assertEqual(sub, "pkg/\n  mod.py")

    def test_stat_reports_files_symlinks_and_missing(self):
        os.symlink("a.txt", self.work / "link")
        lines = self.call("fs_stat", paths=["a.txt", "src", "link", "nope"]).splitlines()
        self.assertRegex(lines[0], r"^a\.txt  file  6 bytes  \d{4}-\d\d-\d\dT[\d:]{8}  644$")
        self.assertRegex(lines[1], r"^src  dir  ")
        self.assertTrue(lines[2].startswith("link  symlink  ") and lines[2].endswith("  -> a.txt"))
        self.assertEqual(lines[3], "nope  missing")

    def test_read_many_headers_binary_clipping_and_limits(self):
        (self.work / "bin.dat").write_bytes(b"\0\1\2" * 10)
        (self.work / "long.txt").write_text("z" * 500)
        registry, _ = self.load(ITEM, max_chars_each=100, max_files=3)
        out = self.call("fs_read_many", registry, paths=["a.txt", "bin.dat", "long.txt", ][:3])
        self.assertIn("==> a.txt <==\nalpha\n", out)
        self.assertIn("==> bin.dat <==\n[binary, 30 bytes]", out)
        self.assertIn("z" * 100 + "\n[clipped; 500 bytes in the file;", out)
        with self.assertRaisesRegex(ValueError, "^4 paths is too many; read at most 3 files per call$"):
            self.call("fs_read_many", registry, paths=["a.txt"] * 4)
        self.assertIn("[missing]", self.call("fs_read_many", paths=["nope"]))

    def test_find_by_name_type_and_limit(self):
        self.assertEqual(self.call("fs_find", name="*.py"), "src/m.py\nsrc/pkg/deep.py")
        self.assertEqual(self.call("fs_find", type="d"), "src/\nsrc/pkg/")
        self.assertEqual(self.call("fs_find", name="*.py", max_size=3), "(no matches)")
        out = self.call("fs_find", name="*.py", limit=1)
        self.assertEqual(out, "src/m.py\n[more matches; narrow path or name, or raise limit above 1]")
        self.assertEqual(self.call("fs_find", path="src/pkg"), "src/pkg/deep.py")

    def test_paths_outside_the_working_folder_are_refused(self):
        root = os.path.realpath(self.work)
        message = (
            f"^{re.escape('../outside')} is outside the working folder; use a path inside {re.escape(root)} "
            r"\(symlinks that lead out count\) or set the allow_outside setting$"
        )
        with self.assertRaisesRegex(ValueError, message):
            self.call("fs_stat", paths=["../outside"])
        (self.tmp / "secret").write_text("s")
        os.symlink(self.tmp / "secret", self.work / "escape")
        with self.assertRaisesRegex(ValueError, "escape is outside the working folder"):
            self.call("fs_read_many", paths=["escape"])
        with self.assertRaisesRegex(ValueError, "is outside the working folder"):
            self.call("fs_move", src="a.txt", dest="../moved.txt")
        registry, _ = self.load(ITEM, allow_outside=True)
        self.assertIn("s", self.call("fs_read_many", registry, paths=["escape"]))

    def test_mkdir(self):
        self.assertEqual(self.call("fs_mkdir", path="new/deep"), "created new/deep")
        self.assertTrue((self.work / "new" / "deep").is_dir())
        with self.assertRaisesRegex(ValueError, "^a.txt exists and is a file$"):
            self.call("fs_mkdir", path="a.txt")
        with self.assertRaisesRegex(ValueError, "inside the .git folder"):
            self.call("fs_mkdir", path=".git/x")

    def test_move_refuses_an_existing_destination_unless_overwrite(self):
        (self.work / "b.txt").write_text("beta\n")
        with self.assertRaisesRegex(ValueError, r"^b\.txt already exists; pass overwrite=true to replace it$"):
            self.call("fs_move", src="a.txt", dest="b.txt")
        self.assertTrue((self.work / "a.txt").exists())
        self.assertEqual(self.call("fs_move", src="a.txt", dest="b.txt", overwrite=True), "moved a.txt -> b.txt")
        self.assertEqual((self.work / "b.txt").read_text(), "alpha\n")
        self.assertFalse((self.work / "a.txt").exists())
        self.call("fs_move", src="b.txt", dest="made/for/it/c.txt")  # parents are created
        self.assertTrue((self.work / "made" / "for" / "it" / "c.txt").exists())
        with self.assertRaisesRegex(ValueError, "^nothing.txt does not exist"):
            self.call("fs_move", src="nothing.txt", dest="x")

    def test_copy_files_and_folders(self):
        self.call("fs_copy", src="src", dest="copy")
        self.assertEqual((self.work / "copy" / "pkg" / "deep.py").read_text(), "x = 1\n")
        self.assertTrue((self.work / "src" / "m.py").exists())
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.call("fs_copy", src="a.txt", dest="copy")

    def test_delete_goes_to_the_trash_and_can_be_restored_with_move(self):
        registry, _ = self.load(ITEM)
        out = registry.tools["fs_delete"].run({"path": "src/m.py"}, self.ctx(cwd=self.work))
        self.assertFalse((self.work / "src" / "m.py").exists())
        match = re.fullmatch(r"moved src/m\.py to the trash: (.+) \(restore it with fs_move\)", out)
        self.assertIsNotNone(match, out)
        trashed = Path(match.group(1))
        self.assertTrue(trashed.read_text() == "print(1)\n")
        self.assertRegex(str(trashed), r"/data/projects/[^/]+/tools/fs/trash/\d{8}-\d{6}/src/m\.py$")
        registry.tools["fs_move"].run({"src": "a.txt", "dest": "src/m.py"}, self.ctx(cwd=self.work))  # (restore flow uses move)

    def test_delete_refusals_and_permanent_modes(self):
        with self.assertRaisesRegex(ValueError, "^refusing to change the working folder itself"):
            self.call("fs_delete", path=".")
        (self.work / ".git").mkdir()
        with self.assertRaisesRegex(ValueError, "^refusing to change the .git folder"):
            self.call("fs_delete", path=".git")
        self.assertEqual(self.call("fs_delete", path="a.txt", permanent=True), "deleted a.txt for good")
        registry, _ = self.load(ITEM, trash=False)
        self.assertEqual(self.call("fs_delete", registry, path="src"), "deleted src for good")
        self.assertFalse((self.work / "src").exists())
        with self.assertRaisesRegex(ValueError, "^gone does not exist"):
            self.call("fs_delete", path="gone")


if __name__ == "__main__":
    unittest.main()
