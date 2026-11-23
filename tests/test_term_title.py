"""term_title: the title reaches only a terminal, carries no control characters from model or tool text, and is restored."""

import io
import sys
import unittest
from unittest import mock

from support import ItemTest

ITEM = "extensions/term_title.py"
OSC = "\x1b]0;{}\x07"
PUSH = "\x1b[22;0t"
POP = "\x1b[23;0t"


class Stream(io.StringIO):
    """A stand-in for the real terminal."""

    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


class TermTitleTest(ItemTest):
    def terminal(self, tty=True):
        stream = Stream(tty)
        for name in ("__stdout__", "stdout"):
            patcher = mock.patch.object(sys, name, stream)
            patcher.start()
            self.addCleanup(patcher.stop)
        return stream

    def title_ctx(self, cwd="/work/shop", model="m1", mode=None):
        return self.ctx(
            cwd=cwd,
            model=model,
            provider_name="fake",
            mode=mode,
            git=lambda: mock.Mock(branch="main"),
        )

    def loaded(self, **settings):
        registry, errors = self.load(ITEM, **settings)
        self.assertEqual(errors, [])
        return registry

    def test_session_turn_and_end_set_the_title_between_a_push_and_a_pop(self):
        stream = self.terminal()
        registry = self.loaded()
        ctx = self.title_ctx()
        registry.emit("session_start", {"ctx": ctx})
        registry.emit("turn_start", {"ctx": ctx, "text": "hi"})
        registry.emit("turn_end", {"ctx": ctx, "nested": True, "messages": []})  # a nested agent's end: no change
        registry.emit("turn_end", {"ctx": ctx, "nested": False, "messages": []})
        registry.dispose()
        self.assertEqual(
            stream.getvalue(),
            PUSH + OSC.format("minimal: shop [idle]") + OSC.format("minimal: shop [working]")
            + OSC.format("minimal: shop [idle]") + POP,
        )

    def test_nothing_is_written_when_there_is_no_terminal(self):
        stream = self.terminal(tty=False)
        registry = self.loaded()
        ctx = self.title_ctx()
        registry.emit("session_start", {"ctx": ctx})
        registry.emit("turn_start", {"ctx": ctx, "text": "hi"})
        registry.dispose()
        self.assertEqual(stream.getvalue(), "")

    def test_control_characters_in_the_folder_model_and_mode_cannot_inject_a_sequence(self):
        stream = self.terminal()
        registry = self.loaded(template="{project} {model} {mode} {branch}")
        ctx = self.title_ctx(cwd="/work/a\x1b]0;evil\x07b\nc", model="m\x1b[31m", mode="p\x9bq")
        registry.emit("session_start", {"ctx": ctx})
        written = stream.getvalue()
        self.assertEqual(written, PUSH + OSC.format("a ]0;evil b c m [31m p q main"))
        self.assertEqual(written.count("\x1b"), 2)  # the push's and the one that opens our own sequence
        self.assertEqual(written.count("\x07"), 1)
        self.assertNotIn("\x9b", written)

    def test_a_bad_template_is_a_warning_and_the_default_template_is_used(self):
        stream = self.terminal()
        registry, errors = self.load(ITEM, template="{nope} [{state}]")
        self.assertEqual(errors, [])
        registry.emit("session_start", {"ctx": self.title_ctx()})
        self.assertEqual(stream.getvalue(), PUSH + OSC.format("minimal: shop [idle]"))
        app = self.make_app(ITEM, [], settings={"template": "{project"})
        (problem,) = app.extension_problems
        self.assertIn("term_title: extensions.settings.term_title.template: template is not valid", problem)
        self.assertIn("the default template '{prefix}: {project} [{state}]' is used until you fix it", problem)

    def test_settings_choose_the_words_the_limit_and_the_restore_title(self):
        stream = self.terminal()
        registry = self.loaded(prefix="dev", idle="ok", max_length=12, restore="shell", push_pop=False)
        registry.emit("session_start", {"ctx": self.title_ctx(cwd="/work/averylongprojectname")})
        registry.dispose()
        self.assertEqual(stream.getvalue(), OSC.format("dev: a… [ok]") + OSC.format("shell"))

    def test_disabled_registers_nothing(self):
        stream = self.terminal()
        registry = self.loaded(enabled=False)
        self.assertEqual(registry.widgets, {})
        registry.emit("session_start", {"ctx": self.title_ctx()})
        self.assertEqual(stream.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
