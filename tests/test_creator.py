"""creator: the tools' confirm/read_only flags, the name rule, where files may be written, the lint vocabulary and the
environment ``ext_check`` hands to the process that loads an item.

The skeletons, ``ext_list``, ``ext_catalogue_row`` and the lint's api/schema rules are covered by minimal's
``tests/test_bundled_creator.py``.
"""

import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from minimal.extensions import loader

from support import ROOT, ItemTest

ITEM = "extensions/creator.py"
KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BRAVE_API_KEY")
BAD_NAME = "invalid name {!r}: use lowercase letters, digits and _, not starting with _"


class CreatorTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.home = self.tmp / "userhome"
        self.project = self.tmp / "project"
        self.home.mkdir()
        self.project.mkdir()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = self.make_app(ITEM, [], cwd=self.project)
        self.module = sys.modules[loader.module_name(ROOT / ITEM)]
        self.global_root = self.home / ".minimal" / "extensions"
        self.project_root = self.project / ".minimal" / "extensions"

    def call(self, tool, **input):
        return self.app.registry.tools[tool].run(input, self.app.context)

    def files(self):
        return sorted(p for p in self.tmp.rglob("*") if p.is_file() and p.suffix == ".py" and "extensions" in p.parts)

    def test_flags_mutating_tools_confirm_and_name_their_target_and_pure_reads_are_read_only(self):
        tools = self.app.registry.tools
        for name, subject in (("ext_new", "name"), ("ext_bump", "path"), ("ext_remove", "path")):
            self.assertIs(tools[name].confirm, True, name)
            self.assertFalse(tools[name].read_only, name)
            self.assertEqual(tools[name].subject_key, subject, name)
        for name in ("ext_template", "ext_check", "ext_api", "ext_list", "ext_catalogue_row"):
            self.assertIs(tools[name].read_only, True, name)
            self.assertFalse(tools[name].confirm, name)

    def test_ext_new_only_writes_a_name_that_fits_the_rule_and_only_below_the_extensions_folder(self):
        for name in ("../evil", "evil/../../x", "a/b", "Evil", "_hidden", ".hidden", "my-tool", "two words", "", None, 5, "x\n"):
            with self.subTest(name=name), self.assertRaises(ValueError) as caught:
                self.call("ext_new", name=name, kind="tool")
            self.assertEqual(str(caught.exception), BAD_NAME.format(name))
        self.assertEqual(self.files(), [])
        self.assertIn("Created", self.call("ext_new", name="a1_b2", kind="tool"))
        self.assertEqual(self.files(), [self.global_root / "tools" / "a1_b2.py"])

    def test_ext_new_scope_and_kind_errors_name_the_choices(self):
        with self.assertRaisesRegex(ValueError, "^scope must be 'global' or 'project'$"):
            self.call("ext_new", name="demo", kind="tool", scope="everywhere")
        for kind in ("plugin", None, ["tool"]):  # an unhashable kind is an error message, not a TypeError
            with self.subTest(kind=kind), self.assertRaises(ValueError) as caught:
                self.call("ext_new", name="demo", kind=kind)
            self.assertEqual(str(caught.exception), f"unknown kind {kind!r}; use one of: extension, tool, widget, theme")
        self.assertEqual(self.files(), [])

    def test_ext_new_scope_defaults_to_the_setting_and_the_project_scope_writes_inside_the_project(self):
        self.call("ext_new", name="local_one", kind="extension", scope="project")
        self.assertEqual(self.files(), [self.project_root / "local_one.py"])
        app = self.make_app(ITEM, [], cwd=self.project, settings={"default_scope": "project"}, session_id="s2")
        app.registry.tools["ext_new"].run({"name": "local_two", "kind": "theme"}, app.context)
        self.assertEqual(self.files(), [self.project_root / "local_one.py", self.project_root / "themes" / "local_two.py"])

    def test_ext_new_never_overwrites_and_says_so(self):
        self.call("ext_new", name="demo", kind="tool")
        target = self.global_root / "tools" / "demo.py"
        target.write_text('"""mine"""\n')
        with self.assertRaisesRegex(ValueError, f"^{target} exists; edit it instead$"):
            self.call("ext_new", name="demo", kind="tool")
        self.assertEqual(target.read_text(), '"""mine"""\n')

    def test_ext_remove_refuses_everything_outside_the_two_extension_folders_with_the_reason(self):
        self.call("ext_new", name="demo", kind="tool", scope="project")
        keep = [self.tmp / "outside.py", self.home / "notes.py", self.project / "app.py"]
        for path in keep:
            path.write_text('"""keep"""\n')
        for refused in (*map(str, keep), "../outside.py", str(self.global_root), str(self.project_root / "tools"), "."):
            with self.subTest(path=refused), self.assertRaises(ValueError) as caught:
                self.call("ext_remove", path=refused)
            self.assertRegex(
                str(caught.exception),
                r"^only extensions under ~/\.minimal/extensions or \./\.minimal/extensions can be removed; .+ is not one$",
            )
        self.assertTrue(all(path.exists() for path in keep))
        self.assertIn("Removed", self.call("ext_remove", path=".minimal/extensions/tools/demo.py"))
        self.assertEqual(self.files(), [])

    def test_ext_bump_changes_only_the_version_line(self):
        target = self.project / "item.py"
        target.write_text('"""Item."""\n\n__version__ = "1.9"\n__api__ = "2.3"\n')
        self.assertEqual(self.call("ext_bump", path="item.py"), "1.9 -> 1.10")
        self.assertEqual(self.call("ext_bump", path="item.py", part="major"), "1.10 -> 2.0")
        self.assertEqual(target.read_text(), '"""Item."""\n\n__version__ = "2.0"\n__api__ = "2.3"\n')
        with self.assertRaisesRegex(ValueError, "^part must be 'minor' or 'major'$"):
            self.call("ext_bump", path="item.py", part="patch")

    def test_ext_check_hands_the_checker_no_api_keys_and_keeps_the_rest_of_the_environment(self):
        item = self.project / "item.py"
        item.write_text('"""Item."""\n')
        secrets = {key: f"secret-{key}" for key in KEYS}
        done = subprocess.CompletedProcess([], 0, stdout="ok item", stderr="")
        with (
            mock.patch.dict(os.environ, {**secrets, "KEEP_ME": "yes"}),
            mock.patch("subprocess.run", return_value=done) as run,
        ):
            self.call("ext_check", path="item.py")
        argv, env = run.call_args.args[0], run.call_args.kwargs["env"]
        self.assertEqual(argv, [sys.executable, "-m", "minimal", "ext", "check", str(item)])
        self.assertEqual([key for key in KEYS if key in env], [])
        self.assertEqual(env["KEEP_ME"], "yes")
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_ext_check_errors_say_what_failed_and_what_to_change(self):
        with self.assertRaisesRegex(ValueError, f"^{self.project / 'nope.py'} does not exist$"):
            self.call("ext_check", path="nope.py")
        bad = self.project / "bad.py"
        bad.write_text("def register(minimal:\n")
        with self.assertRaises(RuntimeError) as caught:
            self.call("ext_check", path="bad.py")
        self.assertIn("bad", str(caught.exception))
        slow = subprocess.TimeoutExpired("x", 1)
        with mock.patch("subprocess.run", side_effect=slow), self.assertRaisesRegex(
            RuntimeError, "^ext check timed out after 120s; raise the check_timeout setting if the item is slow to load$"
        ):
            self.call("ext_check", path="bad.py")

    def test_the_lint_accepts_every_tag_the_marketplace_gate_accepts(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(sys.path.remove, str(ROOT / "scripts"))
        import check_items

        self.assertEqual(set(self.module.TAGS), set(check_items.TAGS))
        for tag in check_items.TAGS:
            source = f'"""x"""\n__version__ = "1.0"\n__api__ = "2.3"\n__tags__ = [{tag!r}]\n'
            self.assertEqual(self.module.lint(source)[0], [], tag)
        problems, _ = self.module.lint('"""x"""\n__tags__ = ["nonsense"]\n')
        self.assertEqual(len(problems), 1)
        self.assertIn("github", problems[0])  # the message lists the vocabulary to pick from

    def test_a_check_of_a_file_with_a_new_tag_passes_end_to_end(self):
        item = self.project / "gh_item.py"
        item.write_text(
            '"""Reads PRs."""\n__version__ = "1.0"\n__api__ = "2.3"\n__tags__ = ["github"]\n\n\ndef register(minimal):\n    pass\n'
        )
        report = self.call("ext_check", path="gh_item.py")
        self.assertNotIn("LINT", report)


if __name__ == "__main__":
    unittest.main()
