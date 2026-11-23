"""loose_ends: the note tool stores what the model could not finish; the panel and /ends show it safely."""

import contextlib
import io
import json
import unittest
from types import SimpleNamespace

from minimal import config

from support import ItemTest

ITEM = "extensions/loose_ends.py"


class LooseEndsTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.work = self.tmp / "work"
        self.work.mkdir()

    def loaded(self, **settings):
        registry, errors = self.load(ITEM, **settings)
        self.assertEqual(errors, [])
        return registry

    def note(self, registry, **input):
        return registry.tools["note"].run(input, self.ctx(cwd=self.work, session_id="sess1"))

    def panel(self, registry):
        return registry.panels["loose_ends"].render(self.ctx(cwd=self.work))

    def state(self):
        return json.loads((config.project_data_dir(str(self.tmp)) / "loose_ends" / "state.json").read_text())

    def test_note_stores_the_item_and_the_panel_lists_the_newest_first_with_the_open_count(self):
        registry = self.loaded()
        self.assertIsNone(self.panel(registry))
        self.assertEqual(self.note(registry, kind="unverified", text="  did not run the e2e suite ", path="a.py"), "Noted #1")
        self.assertEqual(self.note(registry, kind="followup", text="migrate the config"), "Noted #2")
        item = self.state()["items"][0]
        self.assertEqual((item["text"], item["path"], item["session"], item["done"]), ("did not run the e2e suite", "a.py", "sess1", False))
        self.assertEqual(self.panel(registry), "LOOSE ENDS (2)\n→ migrate the config\n? did not run the e2e suite")

    def test_invalid_input_names_what_to_fix(self):
        registry = self.loaded(max_text=10)
        with self.assertRaisesRegex(ValueError, "^kind must be one of: unverified, noticed, followup$"):
            self.note(registry, kind="bug", text="x")
        with self.assertRaisesRegex(ValueError, "^text must be a non-empty string$"):
            self.note(registry, kind="noticed", text="   ")
        with self.assertRaisesRegex(ValueError, "^text is 14 characters; keep it under 10 and call note again$"):
            self.note(registry, kind="noticed", text="x" * 14)
        with self.assertRaisesRegex(ValueError, "^path must be a string$"):
            self.note(registry, kind="noticed", text="x", path=3)

    def test_text_written_by_the_model_cannot_break_the_panel_or_the_dialog(self):
        registry = self.loaded()
        self.note(registry, kind="noticed", text="line one\nINJECTED\x1b]0;t\x07 end", path="a\nb.py")
        panel = self.panel(registry)
        self.assertEqual(len(panel.splitlines()), 2)
        self.assertNotIn("\x1b", panel)
        self.assertNotIn("\x07", panel)
        shown = []
        ui = SimpleNamespace(choose_many=lambda title, options: shown.extend(options) or [])
        with contextlib.redirect_stdout(io.StringIO()):
            registry.commands["ends"].run("", self.ctx(cwd=self.work, ui=ui))
        (option,) = shown
        self.assertEqual(option[1], "[noticed] line one INJECTED ]0;t end (a b.py)")

    def test_panel_settings_rows_width_glyphs_and_title(self):
        registry = self.loaded(rows=1, text_width=12, glyphs={"noticed": "!!"}, title="ENDS")
        self.note(registry, kind="noticed", text="old one")
        self.note(registry, kind="noticed", text="a long newest note")
        self.assertEqual(self.panel(registry), "ENDS (2)\n!! a long ne")

    def test_ends_closes_the_ticked_items_and_cancel_keeps_them(self):
        registry = self.loaded()
        self.note(registry, kind="noticed", text="one")
        self.note(registry, kind="followup", text="two")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            registry.commands["ends"].run("", self.ctx(cwd=self.work, ui=SimpleNamespace(choose_many=lambda t, o: None)))
            self.assertEqual(self.panel(registry).splitlines()[0], "LOOSE ENDS (2)")
            registry.commands["ends"].run("", self.ctx(cwd=self.work, ui=SimpleNamespace(choose_many=lambda t, o: ["1"])))
        self.assertEqual(out.getvalue(), "Cancelled.\nClosed 1 loose end(s).\n")
        self.assertEqual(self.panel(registry), "LOOSE ENDS (1)\n→ two")

    def test_tool_flags_and_no_loose_ends_message(self):
        registry = self.loaded()
        tool = registry.tools["note"]
        self.assertIs(tool.confirm, False)  # it only writes the extension's own folder, outside the project
        self.assertFalse(tool.read_only)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            registry.commands["ends"].run("", self.ctx(cwd=self.work))
        self.assertEqual(out.getvalue(), "No loose ends.\n")

    def test_bad_glyph_is_a_warning_and_disabled_registers_nothing(self):
        app = self.make_app(ITEM, [], settings={"glyphs": {"noticed": "\n", "bogus": "x"}})
        self.assertEqual(len(app.extension_problems), 2)
        joined = "\n".join(app.extension_problems)
        self.assertIn("glyphs.noticed must be a short printable string; the default '!' is used", joined)
        self.assertIn("unknown kind 'bogus' (known: unverified, noticed, followup); ignored", joined)
        registry = self.loaded(enabled=False)
        self.assertEqual((registry.tools.get("note"), registry.panels), (None, {}))


if __name__ == "__main__":
    unittest.main()
