"""retry: which failures are retried, the backoff, the fallback, the toast, and an interruptible countdown.

The item registers no tool and starts no process; its only wait runs on the turn's thread, so the standard's
tool/subprocess/disposal points do not apply. What matters here is the decision (``verdict``), what the loop does with
it, that a bad template is a warning rather than a failed load, and that Esc interrupts a waiting retry quickly.
"""

import importlib.util
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from minimal.api import TurnInterrupted

from support import ROOT, ItemTest, RecordingProvider, text_reply

ITEM = "extensions/retry.py"


def load_module():
    spec = importlib.util.spec_from_file_location("marketplace_retry_under_test", ROOT / ITEM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HTTPError(Exception):
    def __init__(self, status_code, headers=None):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.response = SimpleNamespace(headers=headers or {})


class FailingProvider(RecordingProvider):
    """Raises the next of ``errors`` on each request while any are left, then replays ``replies``."""

    def __init__(self, errors, replies):
        super().__init__(replies)
        self.errors = list(errors)
        self.attempts = 0

    def stream(self, **kw):
        self.attempts += 1
        if self.errors:
            raise self.errors.pop(0)
        return super().stream(**kw)


class RetryTest(ItemTest):
    def decide(self, registry, error, attempt=1, provider="anthropic", notify=None):
        ctx = self.ctx(notify=notify or (lambda *a, **k: None))
        payload = {"ctx": ctx, "error": error, "attempt": attempt, "provider": provider, "model": "m", "nested": False}
        return registry.emit("provider_error", payload)

    def load_retry(self, **settings):
        registry, errors = self.load(ITEM, **settings)
        self.assertEqual((errors, registry.problems), ([], []))
        return registry

    # --- the decision -------------------------------------------------------------------------------------------

    def test_backoff_doubles_from_base_delay_up_to_max_delay(self):
        registry = self.load_retry()
        delays = [self.decide(registry, HTTPError(429), attempt=n)[0]["retry_after"] for n in range(1, 6)]
        self.assertEqual(delays, [2.0, 4.0, 8.0, 16.0, 32.0])
        registry = self.load_retry(max_delay=10.0)
        self.assertEqual(self.decide(registry, HTTPError(429), attempt=5)[0], {"retry_after": 10.0})

    def test_retry_after_header_wins_until_capped_or_switched_off(self):
        registry = self.load_retry(max_delay=30)
        self.assertEqual(self.decide(registry, HTTPError(429, {"retry-after": "7"}))[0], {"retry_after": 7.0})
        self.assertEqual(self.decide(registry, HTTPError(429, {"retry-after": "500"}))[0], {"retry_after": 30.0})
        self.assertEqual(self.decide(registry, HTTPError(429, {"retry-after": "soon"}))[0], {"retry_after": 2.0})
        registry = self.load_retry(respect_retry_after=False)
        self.assertEqual(self.decide(registry, HTTPError(429, {"retry-after": "7"}))[0], {"retry_after": 2.0})

    def test_only_retryable_errors_are_retried_and_the_lists_are_settings(self):
        registry = self.load_retry()
        self.assertEqual(self.decide(registry, HTTPError(400)), [])
        self.assertEqual(self.decide(registry, ValueError("bad request")), [])
        self.assertTrue(self.decide(registry, HTTPError(529)))
        self.assertTrue(self.decide(registry, ConnectionError("reset")))
        self.assertTrue(self.decide(registry, RuntimeError("Overloaded, try later")))  # `match`, any case
        custom = self.load_retry(statuses=[418], match=["busy"], network_errors=["Flaky"])
        self.assertTrue(self.decide(custom, HTTPError(418)))
        self.assertEqual(self.decide(custom, HTTPError(429)), [])
        self.assertEqual(self.decide(custom, RuntimeError("Overloaded")), [])
        self.assertTrue(self.decide(custom, RuntimeError("server busy")))
        self.assertTrue(self.decide(custom, type("Flaky", (Exception,), {})("x")))

    def test_after_max_attempts_it_switches_once_to_the_fallback(self):
        registry = self.load_retry(max_attempts=2, fallback="openai/gpt-4.1")
        self.assertEqual(self.decide(registry, HTTPError(503), attempt=2)[0], {"retry_after": 4.0})
        self.assertEqual(self.decide(registry, HTTPError(503), attempt=3)[0], {"provider": "openai", "model": "gpt-4.1"})
        self.assertEqual(self.decide(registry, HTTPError(503), attempt=4, provider="openai"), [])  # the fallback failed too
        no_model = self.load_retry(max_attempts=0, fallback="openai")
        self.assertEqual(self.decide(no_model, HTTPError(503), attempt=1)[0], {"provider": "openai"})
        self.assertEqual(self.decide(self.load_retry(max_attempts=0), HTTPError(503), attempt=1), [])

    def test_the_toasts_are_settings(self):
        toasts = []
        registry = self.load_retry()
        self.decide(registry, HTTPError(429), attempt=2, notify=lambda *a: toasts.append(a))
        self.assertEqual(toasts, [("retry: HTTPError (2/5), again in 4s", "warning")])
        toasts.clear()
        registry = self.load_retry(max_attempts=0, fallback="openai/x", fallback_message="going to {fallback}")
        self.decide(registry, HTTPError(429), notify=lambda *a: toasts.append(a))
        self.assertEqual(toasts, [("going to openai/x", "warning")])
        toasts.clear()
        registry = self.load_retry(notify=False)
        self.decide(registry, HTTPError(429), notify=lambda *a: toasts.append(a))
        self.assertEqual(toasts, [])

    # --- settings --------------------------------------------------------------------------------------------

    def test_a_template_that_cannot_be_formatted_is_a_warning_and_the_default_stays(self):
        for key, template in (
            ("retry_message", "{attempt[0]}"),  # TypeError
            ("retry_message", "{error.nope}"),  # AttributeError
            ("retry_message", "{unknown}"),  # KeyError
            ("fallback_message", "{fallback.nope}"),
            ("retry_message", "{delay:d}"),  # ValueError
        ):
            with self.subTest(template=template):
                registry, errors = self.load(ITEM, **{key: template})
                self.assertEqual(errors, [])
                (problem,) = registry.problems
                self.assertIn(f"extensions.settings.retry.{key} is not a valid template", problem)
                self.assertIn("the default is used until you fix it", problem)
                toasts = []
                self.decide(registry, HTTPError(429), notify=lambda *a: toasts.append(a))
                self.assertEqual(toasts, [("retry: HTTPError (1/5), again in 2s", "warning")])

    def test_inconsistent_lists_and_a_bad_fallback_are_warnings_with_the_default_used(self):
        registry, errors = self.load(ITEM, statuses=[700, 429], fallback="openai/")
        self.assertEqual(errors, [])
        self.assertEqual(len(registry.problems), 2)
        self.assertIn("statuses has 700, which is not an HTTP status (100-599)", registry.problems[0])
        self.assertIn("fallback 'openai/' must be \"provider\" or \"provider/model\"", registry.problems[1])
        self.assertTrue(self.decide(registry, HTTPError(502)))  # default statuses back
        self.assertEqual(self.decide(registry, HTTPError(503), attempt=6), [])  # no fallback

    def test_a_value_outside_the_schema_fails_the_load_naming_the_key(self):
        for settings, key in (({"max_attempts": -1}, "max_attempts"), ({"factor": 0.5}, "factor"), ({"base_delay": -2}, "base_delay")):
            with self.subTest(settings=settings):
                _, errors = self.load(ITEM, **settings)
                self.assertTrue(any(key in e for e in errors), errors)

    def test_registering_starts_no_thread(self):
        before = threading.active_count()
        self.load_retry(progress=True)
        self.assertEqual(threading.active_count(), before)

    # --- the loop ----------------------------------------------------------------------------------------------

    def test_a_failed_request_is_sent_again_after_the_wait_and_the_turn_succeeds(self):
        frontend = mock.Mock()
        frontend.theme_name.return_value = None
        app = self.make_app(ITEM, [], settings={"base_delay": 0}, frontend=frontend)
        app.provider = FailingProvider([HTTPError(429), HTTPError(503)], [text_reply("ok")])
        self.run_turn(app, "q")
        self.assertEqual(app.provider.attempts, 3)
        self.assertEqual(app.messages[-1]["content"][0]["text"], "ok")
        self.assertEqual(
            [c.args for c in frontend.notify.call_args_list],
            [("retry: HTTPError (1/5), again in 0s", "warning"), ("retry: HTTPError (2/5), again in 0s", "warning")],
        )

    def test_an_error_that_is_not_retryable_ends_the_turn_after_one_request(self):
        app = self.make_app(ITEM, [], settings={"base_delay": 0})
        app.provider = FailingProvider([HTTPError(400)], [text_reply("never")])
        out = self.run_turn(app, "q")
        self.assertEqual(app.provider.attempts, 1)
        self.assertIn("HTTP 400", out)
        self.assertEqual(app.provider.requests, [])  # the scripted reply was never reached

    # --- the countdown ---------------------------------------------------------------------------------------

    def countdown_ctx(self):
        flag = threading.Event()
        notes = []

        def check():
            if flag.is_set():
                raise TurnInterrupted("interrupted by the user")

        return flag, notes, SimpleNamespace(check_cancelled=check, progress=lambda text: notes.append(text))

    def test_the_countdown_reports_the_seconds_left_and_clears_the_note(self):
        module = load_module()
        flag, notes, ctx = self.countdown_ctx()
        with mock.patch.object(module, "PROGRESS_STEP", 0.02):
            started = time.monotonic()
            module._count_down(ctx, 0.2, "retry: HTTPError (1/5),")
        self.assertGreaterEqual(time.monotonic() - started, 0.19)
        self.assertGreaterEqual(len(notes), 3)
        self.assertTrue(all(n is None or n.startswith("retry: HTTPError (1/5), again in ") for n in notes))
        self.assertIsNone(notes[-1])

    def test_esc_interrupts_a_long_countdown_within_a_fraction_of_a_second(self):
        module = load_module()
        flag, notes, ctx = self.countdown_ctx()
        timer = threading.Timer(0.15, flag.set)
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.monotonic()
        with self.assertRaises(TurnInterrupted):
            module._count_down(ctx, 30, "retry:")  # the default PROGRESS_STEP is a second: the wait must not use it whole
        self.assertLess(time.monotonic() - started, 0.6)
        self.assertIsNone(notes[-1])

    def test_progress_true_counts_down_in_the_real_loop_and_still_retries(self):
        frontend = mock.Mock()
        frontend.theme_name.return_value = None
        app = self.make_app(ITEM, [], settings={"base_delay": 0.15, "progress": True}, frontend=frontend)
        app.provider = FailingProvider([HTTPError(429)], [text_reply("ok")])
        self.run_turn(app, "q")
        notes = [c.args[0] for c in frontend.progress.call_args_list]
        self.assertTrue(notes[0].startswith("retry: HTTPError (1/5), again in "))
        self.assertIsNone(notes[-1])
        self.assertEqual(app.provider.attempts, 2)


if __name__ == "__main__":
    unittest.main()
