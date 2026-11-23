"""tools/web_search: the Brave API is replaced by a patched ``urllib.request.urlopen``; no network."""

import io
import json
import os
import socket
import unittest
import urllib.error
from contextlib import nullcontext
from unittest import mock

from support import ItemTest

ITEM = "tools/web_search.py"
KEYS_URL = "https://api-dashboard.search.brave.com/app/keys"


def payload(n=1, description="word " * 10):
    return {"web": {"results": [{"title": f"T{i}", "url": f"https://a{i}.test", "description": description} for i in range(1, n + 1)]}}


class WebSearchTest(ItemTest):
    def use(self, **settings):
        self.registry, errors = self.load(ITEM, **settings)
        self.assertEqual(errors, [])
        return self.registry.tools["web_search"]

    def search(self, answer=None, env=None, **input):
        """Run a search with the key set; ``answer`` is a payload dict or an exception raised by ``urlopen``."""
        sent = []

        def urlopen(request, timeout):
            sent.append((request, timeout))
            if isinstance(answer, Exception):
                raise answer
            body = answer if isinstance(answer, bytes) else json.dumps(answer if answer is not None else payload()).encode()
            return nullcontext(io.BytesIO(body))

        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "k", **(env or {})}), mock.patch("urllib.request.urlopen", urlopen):
            self.sent = sent
            return self.registry.tools["web_search"].run(input, self.ctx())

    def http_error(self, code, body=b"{}"):
        return urllib.error.HTTPError("https://api.search.brave.com", code, "x", {}, io.BytesIO(body))

    def test_it_is_read_only_and_says_when_to_prefer_it_to_bash_curl(self):
        tool = self.use()
        self.assertTrue(tool.read_only)
        self.assertFalse(tool.confirm)
        self.assertIn("Prefer it to `bash` with curl for finding pages", tool.description)

    def test_results_are_numbered_with_cleaned_snippets(self):
        self.use()
        out = self.search({"web": {"results": [{"title": "<strong>A</strong> &amp; B", "url": "https://a.test", "description": "x <b>y</b>"}]}}, query=" q ")
        self.assertEqual(out, "1. A & B\nhttps://a.test\nx y")
        self.assertIn("q=q", self.sent[0][0].full_url)

    def test_missing_key_says_where_to_create_it_and_how_to_export_it(self):
        self.use()
        with mock.patch.dict(os.environ):
            os.environ.pop("BRAVE_API_KEY", None)
            with self.assertRaises(ValueError) as caught:
                self.registry.tools["web_search"].run({"query": "x"}, self.ctx())
        self.assertEqual(
            str(caught.exception),
            f"BRAVE_API_KEY is not set; create a key at {KEYS_URL} and export it before starting minimal "
            "(export BRAVE_API_KEY=<key>), or name another variable in the key_env setting",
        )

    def test_the_missing_key_message_names_the_configured_variable(self):
        self.use(key_env="MY_SEARCH_KEY")
        with mock.patch.dict(os.environ):
            os.environ.pop("MY_SEARCH_KEY", None)
            with self.assertRaisesRegex(ValueError, r"^MY_SEARCH_KEY is not set; .*\(export MY_SEARCH_KEY=<key>\)"):
                self.registry.tools["web_search"].run({"query": "x"}, self.ctx())

    def test_a_rejected_key_says_which_variable_to_fix(self):
        self.use()
        for code in (401, 403):
            with self.subTest(code), self.assertRaises(RuntimeError) as caught:
                self.search(self.http_error(code), query="x")
            self.assertEqual(
                str(caught.exception),
                f"Brave Search rejected the API key in BRAVE_API_KEY (HTTP {code}); check or create a key at {KEYS_URL}, "
                "export it again before starting minimal, or name another variable in the key_env setting",
            )

    def test_the_rate_limit_says_to_wait(self):
        self.use()
        with self.assertRaises(RuntimeError) as caught:
            self.search(self.http_error(429), query="x")
        self.assertEqual(
            str(caught.exception),
            f"Brave Search refused the search: rate limit or quota reached (HTTP 429); wait a moment and retry, or check your plan at {KEYS_URL}",
        )

    def test_another_http_error_carries_the_start_of_the_body(self):
        self.use()
        with self.assertRaisesRegex(RuntimeError, r"^Brave Search returned HTTP 500: " + "e" * 200 + "$"):
            self.search(self.http_error(500, b"e" * 500), query="x")

    def test_a_custom_endpoint_is_named_in_errors_by_its_host(self):
        self.use(endpoint="https://search.test/api")
        with self.assertRaisesRegex(RuntimeError, r"^search\.test returned HTTP 502: bad gateway$"):
            self.search(self.http_error(502, b"bad gateway"), query="x")

    def test_an_unreachable_host_says_to_check_the_network(self):
        self.use()
        with self.assertRaisesRegex(
            RuntimeError, r"^could not reach Brave Search: .*nodename.*; check the network connection or the endpoint setting$"
        ):
            self.search(urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided")), query="x")

    def test_a_timeout_says_which_setting_to_raise(self):
        self.use(timeout=7)
        expected = r"^Brave Search did not answer within 7 s; retry, or raise the timeout setting$"
        for error in (TimeoutError("timed out"), urllib.error.URLError(TimeoutError("timed out"))):
            with self.subTest(error), self.assertRaisesRegex(RuntimeError, expected):
                self.search(error, query="x")
        self.assertEqual(self.sent[0][1], 7)

    def test_an_answer_that_is_not_json_is_an_error(self):
        self.use()
        with self.assertRaisesRegex(RuntimeError, r"^Brave Search did not answer with JSON \(.*\); check the endpoint setting$"):
            self.search(b"<html>proxy login</html>", query="x")

    def test_progress_is_cleared_after_a_failure(self):
        self.use()
        notes = []
        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "k"}), mock.patch("urllib.request.urlopen", side_effect=self.http_error(500)):
            with self.assertRaises(RuntimeError):
                self.registry.tools["web_search"].run({"query": "x"}, self.ctx(progress=notes.append))
        self.assertEqual(notes, ["searching: x", None])

    def test_bad_input_is_a_clear_error_and_sends_no_request(self):
        self.use()
        for input, text in (
            ({}, "query is empty; pass the words to search for as a non-empty string"),
            ({"query": "  "}, "query is empty; pass the words to search for as a non-empty string"),
            ({"query": 5}, "query is empty; pass the words to search for as a non-empty string"),
            ({"query": "x", "count": "many"}, "count must be a whole number from 1 to 20"),
        ):
            with self.subTest(input), self.assertRaises(ValueError) as caught:
                self.search(**input)
            self.assertEqual(str(caught.exception), text)
            self.assertEqual(self.sent, [])

    def test_a_long_answer_is_cut_at_max_chars_and_the_marker_says_how_to_narrow(self):
        self.use(max_chars=1000, count=20)
        full = "\n\n".join(f"{i}. T{i}\nhttps://a{i}.test\n{'word ' * 10}" for i in range(1, 21))
        self.assertGreater(len(full), 1000)
        out = self.search(payload(20), query="x")
        self.assertEqual(
            out, full[:1000] + f"\n[clipped {len(full) - 1000} chars; ask for fewer results with count or set the clip setting]"
        )

    def test_an_answer_within_max_chars_is_not_marked(self):
        self.use(max_chars=1000)
        self.assertNotIn("[clipped", self.search(payload(3), query="x"))

    def test_max_chars_below_its_minimum_is_a_load_error_naming_the_setting(self):
        _, errors = self.load(ITEM, max_chars=10)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("web_search.max_chars", errors[0])

    def test_clip_shortens_each_snippet_with_an_ellipsis(self):
        self.use(clip=12)
        lines = self.search(payload(1, "abcdefghij " * 5), query="x").splitlines()
        self.assertEqual(lines[2], "abcdefghij…")

    def test_count_is_limited_by_max_count_and_a_count_above_it_is_reported(self):
        self.use(count=9, max_count=3)
        self.search(query="x", count=50)
        self.assertTrue(self.sent[0][0].full_url.endswith("count=3"))
        (problem,) = self.registry.problems
        self.assertIn("setting count (9) is above max_count (3); using 3", problem)

    def test_no_results(self):
        self.use()
        self.assertEqual(self.search({"web": {"results": []}}, query="x"), "No results")
        self.assertEqual(self.search([], query="x"), "No results")  # an endpoint answering a list


if __name__ == "__main__":
    unittest.main()
