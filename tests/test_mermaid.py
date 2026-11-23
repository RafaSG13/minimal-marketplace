"""mermaid: the dependency pin, the missing-termaid message, the failure and clipping texts, and a real drawing.

termaid is faked for the texts (so the tests need no third-party package); one test draws with the real termaid when it
is installed (``uv run --with termaid ...``).
"""

import ast
import importlib.util
import re
import sys
import types
import unittest
from unittest import mock

from support import ROOT, ItemTest

ITEM = "extensions/mermaid.py"
HINT = (
    "the mermaid extension needs termaid>=0.12,<1: run `uv pip install 'termaid>=0.12,<1'` in minimal's environment "
    "(or start minimal with `uv run --with 'termaid>=0.12,<1' minimal`)"
)


def fake_termaid(calls):
    """A ``termaid`` that draws each source line as ``[line]``, fails on ``bad`` and records its options."""

    def render(src, **options):
        calls.append((src, options))
        if src.startswith("bad"):
            raise ValueError("no such diagram")
        return "\n".join(f"[{line}]" for line in src.splitlines())

    package = types.ModuleType("termaid")
    package.render = render
    utils = types.ModuleType("termaid.utils")
    utils.fit_to_width = lambda draw, result, width, **options: result
    package.utils = utils
    return {"termaid": package, "termaid.utils": utils}


class MermaidTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.calls = []
        patcher = mock.patch.dict(sys.modules, fake_termaid(self.calls))
        patcher.start()
        self.addCleanup(patcher.stop)

    def renderer(self, **settings):
        self.count = getattr(self, "count", 0) + 1
        app = self.app = self.make_app(ITEM, [], settings=settings or None, session_id=f"s{self.count}")
        return app.registry.renderers["fence:mermaid"].render

    def block(self, source, closed=True, width=80):
        return {"kind": "fence:mermaid", "language": "mermaid", "source": source, "closed": closed, "width": width}

    def test_dependencies_pin_a_version_range_that_the_hint_repeats(self):
        tree = ast.parse((ROOT / ITEM).read_text())
        deps = next(
            ast.literal_eval(n.value)
            for n in tree.body
            if isinstance(n, ast.Assign) and n.targets[0].id == "__dependencies__"
        )
        self.assertEqual(len(deps), 1)
        self.assertRegex(deps[0], r"^termaid>=\d+\.\d+,<\d+$")  # a lower bound it was tried with and an upper one
        self.assertIn(deps[0], HINT)

    def test_without_termaid_loading_fails_with_the_install_command_unless_disabled(self):
        with mock.patch.dict(sys.modules, {"termaid": None, "termaid.utils": None}):
            _, errors = self.load(ITEM)
            self.assertEqual(len(errors), 1, errors)
            self.assertIn(HINT, errors[0])
            registry, errors = self.load(ITEM, enabled=False)
            self.assertEqual(errors, [])
            self.assertNotIn("fence:mermaid", registry.renderers)

    def test_a_termaid_without_the_helper_it_needs_is_also_the_install_hint(self):
        broken = fake_termaid(self.calls)
        broken["termaid.utils"] = types.ModuleType("termaid.utils")  # an old termaid: no fit_to_width
        with mock.patch.dict(sys.modules, broken):
            _, errors = self.load(ITEM)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn(HINT, errors[0])

    def test_a_diagram_that_fails_shows_its_source_and_the_exact_error_once_the_fence_closes(self):
        render = self.renderer()
        rows = render(None, self.block("bad\nx"))
        self.assertEqual(rows[:3], ["bad", "x", ""])
        self.assertEqual(rows[3][0][1], "warning")
        self.assertTrue(rows[3][0][0].endswith(" mermaid: ValueError: no such diagram"))
        self.assertIsNone(render(None, self.block("bad\nx", closed=False)))  # streaming: the plain source meanwhile

    def test_max_lines_cuts_a_tall_drawing_and_says_how_many_rows_are_missing(self):
        rows = self.renderer(max_lines=3)(None, self.block("\n".join("abcdef")))
        self.assertEqual(rows[:3], ["[a]", "[b]", "[c]"])
        self.assertEqual(rows[3], [("… 3 more lines (max_lines 3)", "dim")])

    def test_a_source_over_max_source_chars_is_never_sent_to_termaid(self):
        rows = self.renderer(max_source_chars=200, notice_lines=2)(None, self.block("a\n" * 150))
        self.assertEqual(self.calls, [])
        self.assertEqual(rows[:3], ["a", "a", ""])
        self.assertTrue(rows[3][0][0].endswith("mermaid: 300 characters is over max_source_chars (200); showing the source"))

    def test_ascii_and_termaid_options_reach_termaid(self):
        self.renderer(ascii=True, termaid={"padding_x": 2, "arrow_style": "triangle"})(None, self.block("a"))
        self.assertEqual(self.calls[0][1], {"padding_x": 2, "arrow_style": "triangle", "use_ascii": True})

    def test_a_bad_termaid_option_is_a_load_error_naming_the_option_and_the_choices(self):
        _, errors = self.load(ITEM, termaid={"colour": 1})
        self.assertEqual(len(errors), 1, errors)
        self.assertIn(
            "mermaid: termaid has no option 'colour'; use padding_x, padding_y, gap, rounded_edges, inline_edge_labels, "
            "max_label_width, arrow_style",
            errors[0],
        )

    def test_prompt_hint_is_a_setting(self):
        self.renderer()
        self.assertIn("```mermaid", self.app.context.system_prompt())
        self.renderer(prompt_hint=False)
        self.assertNotIn("```mermaid", self.app.context.system_prompt())


@unittest.skipUnless(importlib.util.find_spec("termaid"), "termaid is not installed here")
class RealTermaidTest(ItemTest):
    """Needs the real package: ``uv run --no-project --with-editable ../minimal --with termaid ...``."""

    def draw(self, source, **settings):
        app = self.make_app(ITEM, [], settings=settings or None)
        block = {"kind": "fence:mermaid", "language": "mermaid", "source": source, "closed": True, "width": 100}
        return app.registry.renderers["fence:mermaid"].render(None, block)

    def test_a_flowchart_is_drawn_and_the_ascii_setting_limits_it_to_ascii(self):
        rows = self.draw("graph LR\n  Alpha --> Beta")
        text = "\n".join(rows)
        self.assertRegex(text, r"Alpha\s*[─-]+.*Beta|Alpha")
        self.assertIn("Beta", text)
        self.assertTrue(any(ord(ch) > 127 for ch in text))  # box drawing
        ascii_rows = self.draw("graph LR\n  Alpha --> Beta", ascii=True)
        self.assertTrue(all(ord(ch) < 128 for ch in "\n".join(ascii_rows)))

    def test_a_malformed_diagram_keeps_its_source_and_names_the_problem(self):
        rows = self.draw("not a diagram at all")
        self.assertEqual(rows[0], "not a diagram at all")
        self.assertRegex(rows[-1][0][0], r"mermaid: \w+")


if __name__ == "__main__":
    unittest.main()
