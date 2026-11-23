"""help_overlay: /keys lists live bindings and commands without side effects; bad settings warn instead of failing the load."""

import contextlib
import io
import unittest

from support import ItemTest

ITEM = "extensions/help_overlay.py"

HELPER = '''
__version__ = "1.0"
__api__ = "2.3"


def register(minimal):
    minimal.register_command("evil", lambda args, ctx: None, description="bad\\x1b]0;t\\x07\\nline2")
    minimal.register_command("quiet", lambda args, ctx: None, description="stays out")
    minimal.register_keybinding("ctrl+shift+h", lambda ctx: None, "helper action", name="act")
'''


class HelpOverlayTest(ItemTest):
    def app(self, **settings):
        helper = self.tmp / "helper.py"
        helper.write_text(HELPER)
        return self.make_app(ITEM, [], extra=[helper], settings=settings or None)

    def keys(self, app, line="/keys"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            app.run_command(line)
        return out.getvalue()

    def test_lists_the_live_keybindings_with_their_owner_and_the_commands(self):
        app = self.app()
        text = self.keys(app)
        self.assertIn("Keys\n", text)
        self.assertRegex(text, r"Ctrl\+Shift\+H +helper action \[helper\]")
        self.assertIn("Ctrl+Q", text)  # an extra key the UI handles itself
        self.assertIn("/keys", text)
        self.assertRegex(text, r"/quiet +stays out")  # other extensions' commands come from the live registry
        self.assertEqual(text, self.keys(app, "/shortcuts"))  # the alias is the same command

    def test_reading_the_listing_changes_nothing(self):
        app = self.app()
        before = (sorted(app.registry.commands), list(app.registry.keybindings), self.keys(app))
        self.keys(app)
        self.assertEqual((sorted(app.registry.commands), list(app.registry.keybindings), self.keys(app)), before)

    def test_text_from_other_extensions_cannot_inject_escape_sequences(self):
        text = self.keys(self.app())
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\x07", text)
        self.assertRegex(text, r"/evil +bad \]0;t line2")

    def test_text_filters_by_key_name_or_description_and_reports_no_match(self):
        app = self.app()
        text = self.keys(app, "/keys helper")
        self.assertIn("helper action", text)
        self.assertNotIn("/quiet", text)
        self.assertEqual(
            self.keys(app, "/keys zzzz").strip(),
            "Nothing matches 'zzzz'. Run the command without text to list everything.",
        )

    def test_hide_commands_and_width_settings(self):
        text = self.keys(self.app(hide_commands=["/quiet", "evil"], width=20))
        self.assertNotIn("/quiet", text)
        self.assertNotIn("/evil", text)
        self.assertTrue(all(len(line) < 60 for line in text.splitlines() if line.startswith("  /")))

    def test_bad_extra_keys_warn_and_the_default_keys_are_listed(self):
        app = self.make_app(ITEM, [], settings={"extra_keys": [["only one"]]})
        (problem,) = app.extension_problems
        self.assertEqual(
            problem,
            "help_overlay: extensions.settings.help_overlay.extra_keys: extra_keys entries must be [key, text] pairs, "
            "not ['only one']; the default keys are listed until you fix it",
        )
        self.assertIn("Ctrl+Q", self.keys(app))

    def test_an_empty_command_name_warns_and_falls_back_to_keys(self):
        app = self.make_app(ITEM, [], settings={"command": "  /  "})
        (problem,) = app.extension_problems
        self.assertIn("extensions.settings.help_overlay.command must not be empty; /keys is used until you fix it", problem)
        self.assertIn("keys", app.registry.commands)

    def test_disabled_registers_nothing(self):
        self.assertNotIn("keys", self.make_app(ITEM, [], settings={"enabled": False}).registry.commands)


if __name__ == "__main__":
    unittest.main()
