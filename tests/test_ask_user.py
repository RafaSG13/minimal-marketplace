"""tools/ask_user: what the model is asked, what it gets back, and the settings."""

import unittest
from types import SimpleNamespace

from support import ItemTest

ITEM = "tools/ask_user.py"


class AskUserTest(ItemTest):
    def use(self, **settings):
        registry, errors = self.load(ITEM, **settings)
        self.assertEqual(errors, [])
        self.calls, self.reply = [], None
        ui = SimpleNamespace(
            ask_text=lambda question: self.calls.append(("ask_text", question)) or self.reply,
            choose=lambda title, options: self.calls.append(("choose", title, options)) or self.reply,
        )
        self.tool, self.ctx = registry.tools["ask_user"], SimpleNamespace(ui=ui)

    def test_it_asks_the_user_so_it_is_neither_read_only_nor_a_confirm_tool(self):
        self.use()
        self.assertFalse(self.tool.read_only)  # two questions at once would fight for the one prompt
        self.assertFalse(self.tool.confirm)  # asking is not a mutation; plan mode keeps it
        self.assertIn("Do not ask what files or tools can tell you", self.tool.description)

    def test_an_open_question_returns_the_typed_answer(self):
        self.use()
        self.reply = "use postgres"
        self.assertEqual(self.tool.run({"question": "  Which database? "}, self.ctx), "use postgres")
        self.assertEqual(self.calls, [("ask_text", "Which database?")])

    def test_options_become_a_menu_without_blanks_or_duplicates(self):
        self.use()
        self.reply = "b"
        out = self.tool.run({"question": "Pick", "options": [" a ", "b", "", "b", "  ", 7, "a"]}, self.ctx)
        self.assertEqual(out, "b")
        self.assertEqual(self.calls, [("choose", "Pick", [("a", "a"), ("b", "b")])])

    def test_a_string_for_options_is_an_error_not_a_menu_of_letters(self):
        self.use()
        with self.assertRaisesRegex(
            ValueError,
            r'^ask_user: options must be an array of strings such as \["yes", "no"\]; omit it for an open question$',
        ):
            self.tool.run({"question": "Proceed?", "options": "yes"}, self.ctx)
        self.assertEqual(self.calls, [])

    def test_an_empty_question_is_an_error_and_nothing_is_asked(self):
        self.use()
        with self.assertRaisesRegex(ValueError, "^ask_user needs a non-empty question$"):
            self.tool.run({"question": "   "}, self.ctx)
        self.assertEqual(self.calls, [])

    def test_no_answer_tells_the_model_to_continue_with_an_assumption(self):
        self.use()
        with self.assertRaisesRegex(
            ValueError,
            r"^The user gave no answer \(cancelled, empty reply, or there is no terminal to ask in\)\. "
            r"Continue with your best assumption and say which one, or finish and explain what you need\.$",
        ):
            self.tool.run({"question": "q"}, self.ctx)

    def test_settings_cap_the_menu_and_replace_the_no_answer_text(self):
        self.use(max_options=2, no_answer="Stop and list what you need.")
        self.assertIn("at most 2", self.tool.input_schema["properties"]["options"]["description"])
        self.reply = "x"
        self.tool.run({"question": "q", "options": list("xyz")}, self.ctx)
        self.assertEqual([value for value, _ in self.calls[0][2]], ["x", "y"])
        self.reply = None
        with self.assertRaisesRegex(ValueError, "^Stop and list what you need\\.$"):
            self.tool.run({"question": "q"}, self.ctx)

    def test_an_emptied_no_answer_setting_falls_back_to_the_default_text(self):
        self.use(no_answer="")
        with self.assertRaisesRegex(ValueError, "^The user gave no answer"):
            self.tool.run({"question": "q"}, self.ctx)


if __name__ == "__main__":
    unittest.main()
