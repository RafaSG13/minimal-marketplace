"""lenses: compression of long bash output, and the full text kept on disk where the note says it is.

The item registers no tool and starts no process or thread; it writes only to its documented folder inside the project
(``.minimal/outputs``), privately. The standard's tool/subprocess points do not apply.
"""

import contextlib
import io
import os
import stat
import sys
import unittest

from support import ROOT, ItemTest

ITEM = "extensions/lenses.py"
SAVED = "[full output: .minimal/outputs/{n:04d}.txt, {lines} lines; read it with offset and limit]"


class LensesTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.work = self.tmp / "work"
        self.work.mkdir()

    def load_lenses(self, **settings):
        registry, errors = self.load(ITEM, **settings)
        self.assertEqual((errors, registry.problems), ([], []))
        return registry

    def bash_result(self, registry, command, output):
        """What the model gets for ``output`` of ``command``: the handlers' rewrite of the tool_result, or the output."""
        event = {
            "name": "bash",
            "input": {"command": command},
            "output": output,
            "is_error": False,
            "ctx": self.ctx(cwd=self.work),
        }
        results = registry.emit("tool_result", event)
        return results[0]["output"] if results else output

    def command(self, registry, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            registry.commands["lenses"].run(args, self.ctx(cwd=self.work))
        return out.getvalue()

    def saved(self):
        return sorted((self.work / ".minimal" / "outputs").glob("*.txt"))

    # --- compression and the full text ----------------------------------------------------------------------

    def test_a_long_output_is_cut_in_the_middle_and_the_full_text_is_saved(self):
        registry = self.load_lenses(head=100, tail=100)
        raw = "".join(f"line {n:04d} of the build output\n" for n in range(400))
        out = self.bash_result(registry, "make all", raw)
        omitted = len(raw) - 200
        self.assertEqual(
            out,
            raw[:100] + "\n" + f"... [lens: {omitted} characters omitted here]" + "\n" + raw[-100:] + "\n"
            + SAVED.format(n=1, lines=400),
        )
        (path,) = self.saved()
        self.assertEqual(path.read_text(), raw)

    def test_tail_zero_keeps_no_tail_instead_of_the_whole_output_again(self):
        registry = self.load_lenses(head=50, tail=0)
        raw = "".join(f"line {n:04d} of the build output\n" for n in range(400))
        out = self.bash_result(registry, "make all", raw)
        self.assertEqual(
            out,
            raw[:50] + "\n" + f"... [lens: {len(raw) - 50} characters omitted here]" + "\n" + "\n" + SAVED.format(n=1, lines=400),
        )
        self.assertLess(len(out), 300)
        self.assertEqual(self.saved()[0].read_text(), raw)

    def test_short_output_is_left_alone_and_nothing_is_saved(self):
        registry = self.load_lenses()
        self.assertEqual(self.bash_result(registry, "ls", "a\nb\n"), "a\nb\n")
        self.assertEqual(self.saved(), [])
        other = {"name": "read", "input": {"path": "x"}, "output": "x" * 5000, "is_error": False, "ctx": self.ctx(cwd=self.work)}
        self.assertEqual(registry.emit("tool_result", other), [])  # only bash output is rewritten

    def test_min_chars_is_a_setting(self):
        registry = self.load_lenses(min_chars=10, head=5, tail=5)
        out = self.bash_result(registry, "echo", "0123456789abcdef\n")
        self.assertTrue(out.startswith("01234\n... [lens: "))
        self.assertTrue(out.endswith(SAVED.format(n=1, lines=1)))

    def test_repeated_lines_collapse_and_the_rest_stays(self):
        registry = self.load_lenses(min_chars=100)
        raw = "start\n" + "same line here\n" * 50 + "end\n"
        out = self.bash_result(registry, "tail -f log", raw)
        self.assertEqual(out, "start\nsame line here\n[previous line repeated 49 more times]\nend\n\n" + SAVED.format(n=1, lines=52))
        self.assertEqual(self.saved()[0].read_text(), raw)

    def test_python_test_lens_hides_passing_lines_and_keeps_failures_and_the_exit_line(self):
        registry = self.load_lenses(min_chars=100)
        ok = "".join(f"test_{n} (m.T.test_{n}) ... ok\n" for n in range(60))
        raw = ok + "FAIL: test_bad (m.T.test_bad)\nAssertionError: 1 != 2\n[exit 1]"
        out = self.bash_result(registry, "python -m unittest -v", raw)
        self.assertEqual(
            out,
            "FAIL: test_bad (m.T.test_bad)\nAssertionError: 1 != 2\n[lens python-tests: 60 passing lines hidden]\n[exit 1]\n"
            + SAVED.format(n=1, lines=63),
        )
        off = self.load_lenses(min_chars=100, python_tests=False)
        self.assertEqual(self.bash_result(off, "python -m unittest -v", raw), raw)

    def test_your_own_rule_drops_lines_and_keeps_head_and_tail_of_the_rest(self):
        rule = {"name": "make", "command": r"\bmake\b", "drop": [r"\[ *\d+%\].*"], "tail": 2}
        registry = self.load_lenses(min_chars=50, rules=[rule])
        raw = "".join(f"[ {n}%] compiling\n" for n in range(1, 10)) + "warning: a\nwarning: b\nwarning: c\n[exit 2]"
        out = self.bash_result(registry, "make -j4", raw)
        self.assertEqual(
            out,
            "[lens make: 1 lines omitted]\nwarning: b\nwarning: c\n[lens make: 9 lines hidden]\n[exit 2]\n"
            + SAVED.format(n=1, lines=13),
        )

    def test_files_are_numbered_in_sequence_and_clear_removes_them(self):
        registry = self.load_lenses(min_chars=10, head=5, tail=5)
        for _ in range(3):
            self.bash_result(registry, "echo", "0123456789abcdef\n")
        self.assertEqual([p.name for p in self.saved()], ["0001.txt", "0002.txt", "0003.txt"])
        listing = self.command(registry, "")
        self.assertIn("python-tests  \\b(pytest|unittest)\\b  (built-in)", listing)
        self.assertIn("3 saved output(s) in .minimal/outputs", listing)
        self.assertEqual(self.command(registry, "clear"), "Removed 3 saved output(s).\n")
        self.assertEqual(self.saved(), [])

    def test_output_dir_is_a_setting(self):
        registry = self.load_lenses(min_chars=10, head=5, tail=5, output_dir="build/logs")
        out = self.bash_result(registry, "echo", "0123456789abcdef\n")
        self.assertIn("[full output: build/logs/0001.txt, 1 lines;", out)
        self.assertEqual((self.work / "build" / "logs" / "0001.txt").read_text(), "0123456789abcdef\n")

    # --- where and how it writes -------------------------------------------------------------------------------

    @unittest.skipIf(sys.platform == "win32", "POSIX modes")
    def test_saved_outputs_are_private_to_the_owner(self):
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        registry = self.load_lenses(min_chars=10, head=5, tail=5)
        self.bash_result(registry, "echo $SECRET", "0123456789abcdef\n")
        folder = self.work / ".minimal" / "outputs"
        self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.saved()[0].stat().st_mode), 0o600)

    def test_when_the_full_text_cannot_be_saved_the_output_is_left_whole(self):
        registry = self.load_lenses(min_chars=10, head=5, tail=5)
        (self.work / ".minimal").mkdir()
        (self.work / ".minimal" / "outputs").write_text("a file where the folder should be")
        raw = "0123456789abcdef\n"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.bash_result(registry, "echo", raw), raw)
        self.assertIn("[lenses] could not save the full output (", err.getvalue())
        self.assertIn("it is left whole", err.getvalue())

    # --- switches --------------------------------------------------------------------------------------------

    def test_off_and_on_by_command_and_the_prompt_note_follows(self):
        registry = self.load_lenses(min_chars=10, head=5, tail=5)
        (section,) = [e for e in registry.prompt_edits if e.name == "lenses"]
        self.assertEqual(
            section.text(self.ctx()),
            "Output lenses: bash output over 10 characters is compressed and the full text is saved under .minimal/outputs/ "
            "(read it with offset and limit when you need hidden lines).",
        )
        self.assertEqual(self.command(registry, "off"), "Output lenses are off.\n")
        self.assertIsNone(section.text(self.ctx()))
        raw = "0123456789abcdef\n"
        self.assertEqual(self.bash_result(registry, "echo", raw), raw)
        self.assertIn("Output lenses are off: /lenses on turns them back on.", self.command(registry, ""))
        self.assertEqual(self.command(registry, "toggle"), "Output lenses are on.\n")
        self.assertNotEqual(self.bash_result(registry, "echo", raw), raw)

    def test_enabled_false_starts_off(self):
        registry = self.load_lenses(enabled=False, min_chars=10)
        raw = "0123456789abcdef\n"
        self.assertEqual(self.bash_result(registry, "echo", raw), raw)

    def test_a_bad_usage_says_the_usage(self):
        registry = self.load_lenses()
        with self.assertRaisesRegex(ValueError, r"^usage: /lenses \[on\|off\|toggle\|clear\]$"):
            self.command(registry, "bogus")

    def test_a_key_the_ui_needs_is_a_warning_and_the_lenses_still_load(self):
        registry, errors = self.load(ITEM, key="enter")
        self.assertEqual(errors, [])
        (problem,) = registry.problems
        self.assertIn("extensions.settings.lenses.key:", problem)
        self.assertIn('set it to "" for no key (the lenses work without it)', problem)
        self.assertIn("lenses", registry.commands)

    # --- settings problems ---------------------------------------------------------------------------------------

    def test_a_message_template_that_cannot_be_formatted_is_a_warning_and_the_default_is_used(self):
        for template in ("{hidden.x}", "{hidden[0]}", "{nope}", "{hidden!z}"):
            with self.subTest(template=template):
                registry, errors = self.load(ITEM, messages={"hidden": template})
                self.assertEqual(errors, [])
                (problem,) = registry.problems
                self.assertIn("messages.hidden is not a valid template (", problem)
                self.assertIn("it may use {hidden}", problem)
                self.assertIn("(ignored: the default applies)", problem)
                raw = "".join(f"test_{n} (m.T.test_{n}) ... ok\n" for n in range(100))
                out = self.bash_result(registry, "python -m unittest -v", raw)
                self.assertIn("[lens python-tests: 100 passing lines hidden]", out)

    def test_bad_rules_regexes_output_dir_and_repeat_min_are_warnings(self):
        registry, errors = self.load(
            ITEM,
            rules=[{"name": "x", "command": "(", "tail": 5}, {"name": "y", "command": "ok"}],
            passing=["(", r".* ok"],
            output_dir="../escape",
            repeat_min=1,
        )
        self.assertEqual(errors, [])
        text = "\n".join(registry.problems)
        self.assertIn("rules[0].command '(' is not a valid regular expression", text)
        self.assertIn("rules[1] (y) does nothing; give it drop, head or tail", text)
        self.assertIn("passing[0] '(' is not a valid regular expression", text)
        self.assertIn("output_dir must be a folder inside the project, like .minimal/outputs (relative, no '..')", text)
        self.assertIn("repeat_min must be 0 (never) or 2 or more", text)

    def test_a_value_outside_the_schema_fails_the_load_naming_the_key(self):
        for settings, key in (({"min_chars": 0}, "min_chars"), ({"head": -1}, "head"), ({"repeat_min": 2000}, "repeat_min")):
            with self.subTest(settings=settings):
                _, errors = self.load(ITEM, **settings)
                self.assertTrue(any(key in e for e in errors), errors)

    def test_registering_writes_nothing(self):
        before = sorted(p.name for p in self.tmp.iterdir())
        self.load_lenses()
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), before)

    def test_metadata(self):
        source = (ROOT / ITEM).read_text()
        self.assertIn('__api__ = "2.4"', source)
        self.assertIn('__tags__ = ["context"]', source)


if __name__ == "__main__":
    unittest.main()
