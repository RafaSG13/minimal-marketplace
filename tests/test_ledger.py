"""ledger: the context panel (heaviest results, stale reads) and /prune.

The item registers no tool, so the standard's tool flags do not apply. What it does start is one lazily-created thread
that stats the files the history read; that thread and what it remembers must go away with ``/reload`` and at exit.
"""

import contextlib
import copy
import io
import os
import threading
import time
import unittest
from types import SimpleNamespace

from support import ItemTest

ITEM = "extensions/ledger.py"


def tool_use(id, name, **input):
    return {"role": "assistant", "content": [{"type": "tool_use", "id": id, "name": name, "input": input}]}


def tool_result(id, text, is_error=False):
    return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": id, "content": text, "is_error": is_error}]}


def history():
    return [
        {"role": "user", "content": "please run the tests and read a.py"},
        tool_use("r1", "read", path="a.py"),
        tool_result("r1", "r" * 4000),
        tool_use("b1", "bash", command="pytest -q\necho second line"),
        tool_result("b1", "b" * 8000),
        {"role": "assistant", "content": [{"type": "text", "text": "done"}], "usage": {"input_tokens": 1, "output_tokens": 1}},
    ]


def flat(lines):
    """Each panel line as plain text."""
    return ["".join(piece if isinstance(piece, str) else piece[0] for piece in line) for line in lines]


def ledger_threads():
    return [t for t in threading.enumerate() if t.name == "ledger-stat"]


class LedgerTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.invalidated = threading.Event()

    def load_ledger(self, **settings):
        registry, errors = self.load(ITEM, **settings)
        self.assertEqual((errors, registry.problems), ([], []))
        self.addCleanup(registry.dispose)
        return registry

    def panel_ctx(self, messages, tokens=None):
        return self.ctx(
            cwd=self.work, messages=messages, context_tokens=tokens, invalidate=self.invalidated.set
        )

    def render(self, registry, messages, tokens=None):
        return flat(registry.panels["ledger"].render(self.panel_ctx(messages, tokens)))

    # --- the panel -----------------------------------------------------------------------------------------

    def test_lists_the_heaviest_results_first_with_their_label_and_the_share_of_each_kind(self):
        registry = self.load_ledger()
        lines = self.render(registry, history(), tokens=10_000)
        self.assertEqual(lines[0], "10.0k tokens")
        self.assertRegex(lines[1], r"^results 99% · prose 0% · inputs 0%$")
        # the model's own count (10000 tokens) is spread over the characters of the history: 8000 + 4000 of results
        self.assertRegex(lines[2], r"^ 6\.\dk bash pytest -q$")
        self.assertRegex(lines[3], r"^ 3\.\dk read a\.py$")
        self.assertEqual(len(lines), 4)
        guessed = self.render(registry, history())  # no usage reported: 4 characters a token
        self.assertEqual(guessed[2:], [" 2.0k bash pytest -q", " 1.0k read a.py"])
        self.assertRegex(guessed[0], r"^~3\.\dk tokens$")

    def test_an_empty_history_says_empty(self):
        self.assertEqual(self.render(self.load_ledger(), []), ["empty"])

    def test_rows_and_label_width_are_settings(self):
        registry = self.load_ledger(rows=1, label_width=10)
        lines = self.render(registry, history(), tokens=12_000)
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[2].endswith("bash pytq…") or lines[2].endswith("…"), lines[2])
        self.assertLessEqual(len(lines[2].split(" ", 2)[-1]), 10)
        self.assertEqual(len(self.render(self.load_ledger(rows=0), history(), tokens=12_000)), 2)

    def test_a_read_followed_by_a_write_of_the_same_file_is_marked_stale(self):
        registry = self.load_ledger(stale_mark="STALE")
        messages = [*history(), tool_use("w1", "write", path="a.py", content="x"), tool_result("w1", "ok")]
        lines = self.render(registry, messages, tokens=10_000)
        self.assertTrue(any(line.endswith("read a.py STALE") for line in lines), lines)
        self.assertFalse(any("bash" in line and "STALE" in line for line in lines))
        failed = [*history(), tool_use("w1", "write", path="a.py", content="x"), tool_result("w1", "no", is_error=True)]
        self.assertFalse(any("STALE" in line for line in self.render(registry, failed, tokens=10_000)))

    def test_a_file_that_changed_on_disk_after_it_was_read_is_marked_stale_by_the_worker_thread(self):
        path = self.work / "a.py"
        path.write_text("v1")
        registry = self.load_ledger()
        ctx = self.panel_ctx(history(), tokens=10_000)
        registry.emit("tool_result", {"name": "read", "input": {"path": "a.py"}, "is_error": False, "ctx": ctx})
        self.assertEqual(ledger_threads(), [])  # nothing runs until the panel is drawn
        first = flat(registry.panels["ledger"].render(ctx))
        self.assertFalse(any("⚠" in line for line in first))
        self.assertTrue(self.invalidated.wait(5), "the worker never reported the file it saw")
        self.invalidated.clear()
        later = time.time() + 100
        os.utime(path, (later, later))
        # a draw asks the worker to stat the file again; it reports the change with a redraw request
        longer = [*history(), {"role": "user", "content": "more"}]
        registry.panels["ledger"].render(self.panel_ctx(longer, tokens=10_000))
        self.assertTrue(self.invalidated.wait(5), "the worker never asked for a redraw")
        again = flat(registry.panels["ledger"].render(self.panel_ctx(longer, tokens=10_000)))
        self.assertTrue(any(line.endswith("read a.py ⚠") for line in again), again)

    def test_the_worker_thread_stops_on_dispose_and_a_reload_starts_with_nothing_remembered(self):
        registry = self.load_ledger()
        self.render(registry, history(), tokens=10_000)
        self.assertEqual(len(ledger_threads()), 1)
        registry.dispose()
        self.assertEqual(ledger_threads(), [])
        registry, errors = self.load(ITEM)
        self.assertEqual(errors, [])
        self.addCleanup(registry.dispose)
        self.assertEqual(ledger_threads(), [])

    # --- /prune --------------------------------------------------------------------------------------------

    def prune(self, registry, messages, ticked):
        asked = []
        switched = []

        def choose(title, options):
            asked.append((title, options))
            return ticked(options) if callable(ticked) else ticked

        def new_session(new):
            switched.append(new)
            return "old"

        ctx = self.ctx(
            cwd=self.work,
            messages=messages,
            context_tokens=None,
            session_id="new",
            ui=SimpleNamespace(choose_many=choose),
            new_session=new_session,
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            registry.commands["prune"].run("", ctx)
        return asked, switched, out.getvalue()

    def test_prune_offers_the_heaviest_first_and_replaces_only_the_chosen_results(self):
        (self.work / "a.py").write_text("x")  # a read of a file that vanished would be offered as stale
        registry = self.load_ledger()
        messages = history()
        original = copy.deepcopy(messages)
        asked, switched, out = self.prune(registry, messages, lambda options: [options[0][0]])
        (title, options) = asked[0]
        self.assertEqual(title, "Prune from context (heaviest first)")
        self.assertEqual([o[1] for o in options], ["2.0k  bash pytest -q", "1.0k  read a.py"])
        self.assertEqual([o[2] for o in options], [False, False])
        self.assertEqual(messages, original)  # the live history is untouched; the new session gets a copy
        (new,) = switched
        self.assertEqual(
            new[4]["content"][0]["content"],
            "[pruned by the user to save context: bash pytest -q, 8000 characters. Run the tool again if you need it.]",
        )
        self.assertEqual(new[2]["content"][0]["content"], "r" * 4000)
        self.assertNotIn("usage", new[5])
        self.assertRegex(out, r"^\[prune\] 1 results pruned \(~[\d.]+k tokens\); now in session new; the full history stays in session old\n$")

    def test_a_stale_read_is_offered_already_ticked(self):
        registry = self.load_ledger()
        messages = [*history(), tool_use("w1", "write", path="a.py", content="x"), tool_result("w1", "ok")]
        asked, _, _ = self.prune(registry, messages, None)
        by_label = {o[1].split("  ", 1)[1]: o for o in asked[0][1]}
        self.assertTrue(by_label["read a.py  (stale)"][2])
        self.assertFalse(by_label["bash pytest -q"][2])

    def test_cancelling_or_ticking_nothing_changes_nothing(self):
        registry = self.load_ledger()
        _, switched, out = self.prune(registry, history(), None)
        self.assertEqual((switched, out), ([], "Cancelled.\n"))
        _, switched, out = self.prune(registry, history(), [])
        self.assertEqual((switched, out), ([], "Nothing pruned.\n"))

    def test_results_that_are_small_or_already_pruned_are_not_offered(self):
        registry = self.load_ledger()
        _, switched, _ = self.prune(registry, history(), lambda options: [o[0] for o in options])
        pruned = switched[0]
        with self.assertRaisesRegex(ValueError, "^nothing to prune$"):
            self.prune(registry, pruned, [])
        # min_prune_chars is a setting: raising it hides the 4000-character read
        registry = self.load_ledger(min_prune_chars=5000)
        asked, _, _ = self.prune(registry, history(), None)
        self.assertEqual(len(asked[0][1]), 1)
        # and prune_candidates caps the list
        registry = self.load_ledger(prune_candidates=1)
        asked, _, _ = self.prune(registry, history(), None)
        self.assertEqual(len(asked[0][1]), 1)

    def test_stub_prefix_is_a_setting_that_marks_pruned_results(self):
        registry = self.load_ledger(stub_prefix="<<cut")
        _, switched, _ = self.prune(registry, history(), lambda options: [options[0][0]])
        self.assertTrue(switched[0][4]["content"][0]["content"].startswith("<<cut to save context: bash pytest -q, 8000 characters."))

    def test_an_empty_stub_prefix_is_a_warning_and_the_default_is_used(self):
        registry, errors = self.load(ITEM, stub_prefix="  ")
        self.assertEqual(errors, [])
        self.addCleanup(registry.dispose)
        self.assertEqual(
            registry.problems,
            ["ledger: extensions.settings.ledger.stub_prefix must not be empty; the default is used until you fix it"],
        )
        _, switched, _ = self.prune(registry, history(), lambda options: [options[0][0]])  # an empty prefix would offer nothing
        self.assertTrue(switched[0][4]["content"][0]["content"].startswith("[pruned by the user to save context"))

    # --- settings and registration ---------------------------------------------------------------------------

    def test_disabled_registers_nothing(self):
        registry, errors = self.load(ITEM, enabled=False)
        self.assertEqual(errors, [])
        self.assertNotIn("prune", registry.commands)
        self.assertNotIn("ledger", registry.panels)

    def test_area_title_and_order_reach_the_panel(self):
        registry = self.load_ledger(area="footer", title="CTX", order=3)
        panel = registry.panels["ledger"]
        self.assertEqual((panel.area, panel.title, panel.order, panel.collapsible), ("footer", "CTX", 3, True))
        panel = self.load_ledger(title="").panels["ledger"]
        self.assertIsNone(panel.title)

    def test_a_value_outside_the_schema_fails_the_load_naming_the_key(self):
        for settings, key in (({"rows": 51}, "rows"), ({"label_width": 2}, "label_width"), ({"area": "nowhere"}, "area")):
            with self.subTest(settings=settings):
                _, errors = self.load(ITEM, **settings)
                self.assertTrue(any(key in e for e in errors), errors)

    def test_registering_starts_no_thread_and_writes_nothing(self):
        before = sorted(p.name for p in self.tmp.iterdir())
        self.load_ledger()
        self.assertEqual(ledger_threads(), [])
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
