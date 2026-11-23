"""tui_tools: the new presets, /edit, and the note that tells the model what a tool changed.

The pre-existing behaviour (launching, chooser, git notes, key bindings) is covered by minimal's own
``tests/test_bundled_tui_tools.py``; fake executables stand in for the real programs here.
"""

import importlib.util
import json
import os
import subprocess
import unittest
from unittest import mock

from support import ROOT, ItemTest, have

ITEM = "extensions/tui_tools.py"

LOG_ARGV = """#!/bin/sh
python3 - "$@" >> "$FAKE_LOG" <<'PY'
import json, os, sys
print(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}))
PY
"""


def module():
    spec = importlib.util.spec_from_file_location("tui_tools_under_test", ROOT / ITEM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PresetTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.log = self.tmp / "argv.log"
        patcher = mock.patch.dict(os.environ, {"FAKE_LOG": str(self.log)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_tool(self, name, args="", **settings):
        registry, errors = self.load(ITEM, **settings)
        self.assertEqual(errors, [])
        self.reports = []
        ctx = self.ctx(show=lambda text, kind="output": self.reports.append((text, kind)))
        registry.commands[name].run(args, ctx)
        return registry, ctx

    def runs(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_each_new_preset_runs_its_program_with_the_arguments_after_the_command(self):
        cases = {
            "lazysql": ("lazysql", []),
            "harlequin": ("harlequin", []),
            "rainfrog": ("rainfrog", []),
            "posting": ("posting", []),
            "atac": ("atac", []),
            "oxker": ("oxker", []),
            "trippy": ("trip", ["example.com"]),
            "bottom": ("btm", []),
            "atuin": ("atuin", ["search", "-i"]),
            "glow": ("glow", ["-p", "README.md"]),
        }
        for name, (program, argv) in cases.items():
            with self.subTest(name):
                self.log.unlink(missing_ok=True)
                self.fake_bin(program, LOG_ARGV)
                self.run_tool(name, "example.com" if name == "trippy" else "README.md" if name == "glow" else "")
                self.assertEqual([r["argv"] for r in self.runs()], [argv])

    def test_a_preset_whose_program_is_missing_is_not_a_command_and_tui_names_the_install(self):
        registry, _ = self.load(ITEM, tools={"fzf": {"env": {"PATH": str(self.tmp / "empty")}}})
        self.assertNotIn("fzf", registry.commands)
        mod = module()
        entry = mod.BUILTIN_TOOLS["fzf"]
        self.assertEqual(
            mod.missing_text("fzf", entry),
            "fzf is not installed ('fzf' is not on PATH): brew install fzf; then /reload.",
        )

    @unittest.skipUnless(have("git") and have("sh"), "needs git and sh")
    def test_fzf_picks_files_of_the_repository_into_the_message_box(self):
        repo = self.git_repo({"a.txt": "a", "sub/b.txt": "b"})
        # the fake fzf behaves as `fzf --multi` answering with the first candidate
        self.fake_bin("fzf", "#!/bin/sh\nhead -1\n")
        registry, _ = self.load(ITEM)
        ctx = self.ctx(cwd=repo, show=lambda *a, **k: None)
        registry.commands["fzf"].run("", ctx)
        self.assertEqual(ctx.ui.draft.strip(), "@a.txt")


class EditTest(ItemTest):
    def edit(self, editor_script, draft="hello", var="EDITOR", **settings):
        registry, errors = self.load(ITEM, **settings)
        self.assertEqual(errors, [])
        path = self.fake_bin("fake-editor", editor_script)
        shown = []
        ctx = self.ctx(show=lambda text, kind="output": shown.append((text, kind)))
        ctx.ui.draft = draft
        sets = []
        original = ctx.ui.set_draft
        ctx.ui.set_draft = lambda text, **kw: (sets.append(text), original(text, **kw))[1]
        with mock.patch.dict(os.environ, {var: str(path)}):
            os.environ.pop("VISUAL" if var == "EDITOR" else "EDITOR", None)
            registry.commands["edit"].run("", ctx)
        return registry, ctx, shown, sets

    def test_edit_is_a_terminal_command_and_puts_the_edited_text_back(self):
        registry, ctx, _, _ = self.edit("#!/bin/sh\nprintf 'more\\n' >> \"$1\"\n", draft="hello\n")
        self.assertTrue(registry.commands["edit"].terminal)
        self.assertEqual(ctx.ui.draft, "hello\nmore")

    def test_visual_wins_over_editor(self):
        _, ctx, _, _ = self.edit("#!/bin/sh\nprintf 'v' > \"$1\"\n", var="VISUAL")
        self.assertEqual(ctx.ui.draft, "v")

    def test_unchanged_text_leaves_the_draft_alone(self):
        _, ctx, shown, sets = self.edit("#!/bin/sh\nexit 0\n", draft="hello\n")
        self.assertEqual((sets, ctx.ui.draft, shown), ([], "hello\n", []))

    def test_an_editor_that_fails_keeps_the_message_and_says_so(self):
        _, ctx, shown, sets = self.edit("#!/bin/sh\nprintf 'lost' > \"$1\"\nexit 3\n")
        self.assertEqual((sets, ctx.ui.draft), ([], "hello"))
        self.assertIn("exited with status 3; your message is unchanged", shown[0][0])

    def test_a_missing_editor_says_how_to_fix_it(self):
        registry, _ = self.load(ITEM)
        shown = []
        ctx = self.ctx(show=lambda text, kind="output": shown.append((text, kind)))
        with mock.patch.dict(os.environ, {"EDITOR": "no-such-editor-xyz"}):
            os.environ.pop("VISUAL", None)
            registry.commands["edit"].run("", ctx)
        self.assertEqual(
            shown, [("/edit: editor 'no-such-editor-xyz' is not on PATH; set $VISUAL or $EDITOR, then retry.", "error")]
        )

    def test_editor_key_binds_a_terminal_key_and_a_reserved_key_is_reported(self):
        registry, _ = self.load(ITEM, editor_key="alt+e")
        self.assertTrue(registry.keybindings["alt+e"].terminal)
        registry, _ = self.load(ITEM, editor_key="ctrl+c")
        self.assertEqual(registry.keybindings, {})
        self.assertTrue(any("editor_key: ctrl+c is reserved" in p for p in registry.problems), registry.problems)


@unittest.skipUnless(have("git"), "needs git")
class TellModelTest(ItemTest):
    FAKE_LAZYGIT = "#!/bin/sh\ncd \"$2\" && {body}\n"

    def run_tool(self, repo, name, script, **settings):
        self.fake_bin(name, script)
        registry, errors = self.load(ITEM, **settings)
        self.assertEqual(errors, [])
        ctx = self.ctx(cwd=repo, show=lambda *a, **k: None)
        registry.commands[name].run("", ctx)
        return registry

    def request(self, registry, **extra):
        out = registry.emit("before_request", {"system": "SYS", "tools": [], "messages": [], "nested": False, **extra})
        return [r["system"] for r in out]

    def test_a_commit_is_told_once_to_the_next_request_only(self):
        repo = self.git_repo({"a.txt": "a"})
        registry = self.run_tool(
            repo, "lazygit", self.FAKE_LAZYGIT.format(body="git commit --allow-empty -q -m 'from lazygit'"), tell_model=True
        )
        first = self.request(registry)
        self.assertEqual(len(first), 1)
        self.assertTrue(first[0].startswith("SYS\n\nThe user ran lazygit and committed or moved HEAD on main: "), first)
        self.assertIn("(from lazygit)", first[0])
        self.assertEqual(self.request(registry), [])

    def test_a_branch_switch_is_told(self):
        repo = self.git_repo({"a.txt": "a"})
        registry = self.run_tool(
            repo, "lazygit", self.FAKE_LAZYGIT.format(body="git switch -q -c feature"), tell_model=True
        )
        self.assertIn("The user ran lazygit and switched from branch main to feature.", self.request(registry)[0])

    def test_nothing_is_told_when_the_setting_is_off_or_nothing_moved(self):
        repo = self.git_repo({"a.txt": "a"})
        registry = self.run_tool(repo, "lazygit", self.FAKE_LAZYGIT.format(body="git switch -q -c feature"))
        self.assertEqual(self.request(registry), [])
        registry = self.run_tool(repo, "lazygit", self.FAKE_LAZYGIT.format(body="true"), tell_model=True)
        self.assertEqual(self.request(registry), [])

    def test_a_subagent_request_does_not_consume_the_note(self):
        repo = self.git_repo({"a.txt": "a"})
        registry = self.run_tool(
            repo, "lazygit", self.FAKE_LAZYGIT.format(body="git switch -q -c feature"), tell_model=True
        )
        self.assertEqual(self.request(registry, nested=True), [])
        self.assertEqual(len(self.request(registry)), 1)

    def test_yazi_picks_are_told(self):
        repo = self.git_repo({"a.txt": "a"})
        script = "#!/bin/sh\nprintf '%s\\n' \"$PWD/a.txt\" > \"${1#--chooser-file=}\"\n"
        registry = self.run_tool(repo, "yazi", script, tell_model=True)
        self.assertEqual(self.request(registry), ["SYS\n\nThe user picked: @a.txt"])

    def test_model_note_wording(self):
        mod = module()
        self.assertIsNone(mod.model_note("x", ("a1", "main", "s"), ("a1", "main", "s"), None))
        self.assertIsNone(mod.model_note("x", None, ("a1", "main", "s"), None))
        self.assertEqual(
            mod.model_note("x", ("a1", "main", "s"), ("b2", "main", "fix"), "x changed the working tree: 1 -> 0 changed files."),
            "The user ran x and committed or moved HEAD on main: a1 -> b2 (fix). x changed the working tree: 1 -> 0 changed files.",
        )


if __name__ == "__main__":
    unittest.main()
