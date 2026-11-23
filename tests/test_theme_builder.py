"""theme_builder: names, colours, the saved file, export and the readable-contrast guarantee.

The item is a user command with no model tools, so there is nothing to confirm: ``/theme_builder`` is typed by the user.
"""

import contextlib
import io
import json
import sys
import unittest
from unittest import mock

from minimal.extensions import loader, marketplace

from support import ROOT, ItemTest

ITEM = "extensions/theme_builder.py"


class ThemeBuilderTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.folder = self.tmp / "home" / "data" / "global" / "theme_builder"
        self.saved = self.folder / "themes.json"
        self.reloads = 0

    def start(self, **settings):
        registry, errors = self.load(ITEM, **settings)
        self.assertEqual(errors, [])
        self.module = sys.modules[loader.module_name(ROOT / ITEM)]
        self.registry = registry
        return registry

    def run_command(self, args):
        """Run ``/theme_builder args``; returns what it printed."""

        def reload():
            self.reloads += 1
            return "reloaded"

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.registry.commands["theme_builder"].run(args, self.ctx(reload=reload))
        return out.getvalue()

    def test_the_item_adds_a_command_and_no_model_tool(self):
        self.start()
        self.assertEqual(set(self.registry.commands), {"theme_builder"})
        self.assertEqual([name for name in self.registry.tools if "theme" in name], [])  # only built-in tools exist
        self.assertEqual([p for p in self.folder.rglob("*") if p.is_file()], [])  # loading writes no file

    def test_building_saves_the_theme_reloads_once_and_the_next_load_registers_it(self):
        self.start()
        out = self.run_command("ocean #4fc3f7 dark --error #ff6b6b")
        self.assertIn("Theme 'ocean' (dark) saved", out)
        self.assertIn(f"kept across restarts in {self.saved}", out)
        self.assertEqual(self.reloads, 1)
        self.assertEqual(json.loads(self.saved.read_text()), {"ocean": {"accent": "#4fc3f7", "mode": "dark", "error": "#ff6b6b"}})

        registry = self.start()
        theme = registry.themes["ocean"]
        self.assertTrue(theme.dark)
        self.assertEqual(theme.colors["accent"], "#4fc3f7")

    def test_every_text_colour_is_readable_on_the_panel_even_for_an_accent_that_is_not(self):
        self.start()
        for mode, accent in (("dark", "#101010"), ("light", "#f5f5f5"), ("dark", "#4fc3f7"), ("light", "#ff00ff")):
            with self.subTest(mode=mode, accent=accent):
                theme = self.module.build_theme(accent, mode)
                panel = self.module.parse_hex(theme["panel"])
                for name in ("foreground", "accent", "secondary", "success", "warning", "error", "muted", "code", "path"):
                    self.assertGreaterEqual(self.module.contrast(self.module.parse_hex(theme[name]), panel), 4.5, name)
        out = self.run_command("ink #101010 dark")
        self.assertRegex(out, r"saved \(accent adjusted to #[0-9a-f]{6} for readability\)")

    def test_the_contrast_settings_change_every_saved_theme_at_the_next_load(self):
        self.start()
        self.run_command("ocean #4fc3f7 dark")
        default = self.start().themes["ocean"].colors
        raised = self.start(text_ratio=9.0, dim_ratio=6.0).themes["ocean"].colors

        def ratio(colors, name):
            return self.module.contrast(self.module.parse_hex(colors[name]), self.module.parse_hex(colors["panel"]))

        self.assertGreater(ratio(raised, "secondary"), max(8.9, ratio(default, "secondary")))
        self.assertGreaterEqual(ratio(raised, "dim"), 6.0)

    def test_out_of_range_settings_are_load_errors_naming_the_key(self):
        _, errors = self.load(ITEM, text_ratio=1.0)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("theme_builder.text_ratio", errors[0])

    def test_names_that_could_escape_the_folder_or_clash_are_refused_and_nothing_is_written(self):
        self.start()
        for name, needle in (
            ("../evil", "theme name '../evil' must be lowercase letters, digits, - or _ (up to 32); usage: /theme_builder"),
            ("a/b", "must be lowercase letters, digits"),
            ("Ocean", "must be lowercase letters, digits"),
            ("_hidden", "must be lowercase letters, digits"),
            ("x" * 33, "must be lowercase letters, digits"),
            ("minimal", "the built-in theme 'minimal' cannot be replaced; choose another name"),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as caught:
                    self.run_command(f"{name} #4fc3f7 dark")
                self.assertIn(needle, str(caught.exception))
        with self.assertRaisesRegex(ValueError, "'delete' is a /theme_builder subcommand and cannot name a theme"):
            self.module.check_name("delete")  # typed as a command, "delete ..." is the subcommand
        self.assertFalse(self.saved.exists())
        self.assertEqual(self.reloads, 0)

    def test_malformed_arguments_say_how_to_write_them(self):
        self.start()
        for args, needle in (
            ("ocean zzz", "'zzz' is not a hex colour; write it as #rrggbb, e.g. #4fc3f7"),
            ("ocean #4fc3f7 purple", "mode must be dark or light, not 'purple'"),
            ("ocean #4fc3f7 dark --secondary", "--secondary needs a colour, e.g. --secondary #ff9e64"),
            ("ocean #4fc3f7 --bogus #fff", "unknown option '--bogus'; use --secondary, --success, --warning, --error"),
            ("ocean", "usage: /theme_builder <name> <accent #rrggbb>"),
            ("", "usage: /theme_builder <name> <accent #rrggbb>"),
            ("list extra", "usage: /theme_builder"),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError) as caught:
                self.run_command(args)
            self.assertIn(needle, str(caught.exception))
        self.assertFalse(self.saved.exists())

    def test_three_digit_colours_and_equals_options_are_accepted_and_normalised(self):
        self.start()
        self.run_command("tiny #4af light --warning=#f80")
        self.assertEqual(
            json.loads(self.saved.read_text()), {"tiny": {"accent": "#44aaff", "mode": "light", "warning": "#ff8800"}}
        )

    def test_list_delete_and_the_unknown_name_error(self):
        self.start()
        self.assertIn("No saved themes.", self.run_command("list"))
        self.run_command("ocean #4fc3f7 dark")
        self.run_command("sand #d9a066 light --error #cc0000")
        self.assertEqual(
            self.run_command("list").splitlines(), ["ocean: #4fc3f7 dark", "sand: #d9a066 light --error #cc0000"]
        )
        with self.assertRaisesRegex(ValueError, r"no saved theme 'nope' \(ocean, sand\); see /theme_builder list"):
            self.run_command("delete nope")
        reloads = self.reloads
        self.assertIn("Theme 'ocean' deleted.", self.run_command("delete ocean"))
        self.assertEqual(self.reloads, reloads + 1)
        self.assertEqual(list(json.loads(self.saved.read_text())), ["sand"])
        self.assertNotIn("ocean", self.start().themes)

    def test_building_again_with_the_same_name_replaces_the_theme(self):
        self.start()
        self.run_command("ocean #4fc3f7 dark")
        self.run_command("ocean #ff0000 light")
        self.assertEqual(json.loads(self.saved.read_text()), {"ocean": {"accent": "#ff0000", "mode": "light"}})

    def test_export_writes_a_standalone_valid_theme_only_inside_the_data_folder(self):
        self.start()
        self.run_command("deep-sea #4fc3f7 dark")
        out = self.run_command("export deep-sea")
        target = self.folder / "export" / "themes" / "deep_sea.py"
        self.assertIn(f"Theme 'deep-sea' exported to {target}", out)
        lines, ok = marketplace.check([target])
        self.assertTrue(ok, lines)
        self.assertIn('NAME = "deep-sea"', target.read_text())
        written = {p for p in self.tmp.rglob("*") if p.is_file() and p.suffix == ".py" and "export" in p.parts}
        self.assertEqual(written, {target})
        with self.assertRaisesRegex(ValueError, "no saved theme 'ocean'"):
            self.run_command("export ocean")

    def test_a_corrupt_saved_file_does_not_stop_loading_but_every_command_names_it(self):
        self.folder.mkdir(parents=True)
        self.saved.write_text("{broken")
        self.start()  # loading shows the other themes, not an error
        self.assertEqual(self.registry.themes, {})
        for args in ("list", "ocean #4fc3f7 dark", "delete x"):
            with self.subTest(args=args), self.assertRaisesRegex(
                ValueError, rf"{self.saved} is unreadable .*fix it or delete it to forget the saved themes"
            ):
                self.run_command(args)
        self.assertEqual(self.saved.read_text(), "{broken")  # not overwritten

    def test_an_entry_with_a_bad_colour_is_refused_not_silently_fixed(self):
        self.folder.mkdir(parents=True)
        self.saved.write_text(json.dumps({"ocean": {"accent": "blue", "mode": "dark"}}))
        self.start()
        with self.assertRaisesRegex(ValueError, "holds an invalid theme .*not a hex colour"):
            self.run_command("list")

    def test_an_unwritable_folder_is_an_error_that_says_what_to_fix(self):
        self.start()
        with mock.patch("os.replace", side_effect=OSError("read-only file system")):
            with self.assertRaisesRegex(ValueError, rf"cannot save the theme to {self.saved} \(read-only file system\); make that folder writable"):
                self.run_command("ocean #4fc3f7 dark")
        self.assertEqual(self.reloads, 0)


if __name__ == "__main__":
    unittest.main()
