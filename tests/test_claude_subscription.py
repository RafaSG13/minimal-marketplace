"""claude_subscription: the login file, the token endpoint's failure modes and the provider, against fakes.

Nothing here talks to claude.ai or api.anthropic.com or needs a real Claude login: the token endpoint is a patched
``urlopen`` and the browser is a function that calls the local callback. How the real endpoint answers is NOT verified.
"""

import contextlib
import io
import json
import os
import stat
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

from minimal.extensions import loader

from support import ROOT, ItemTest

ITEM = "extensions/claude_subscription.py"
SECRET_ACCESS = "sk-ant-oat-ACCESS-SECRET"
SECRET_REFRESH = "sk-ant-ort-REFRESH-SECRET"


class Reply:
    """What ``urlopen`` returns as a context manager."""

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode()


def http_error(code, body=b'{"error": "invalid_grant"}'):
    return urllib.error.HTTPError("https://api.anthropic.com/v1/oauth/token", code, "x", {}, io.BytesIO(body))


class ClaudeTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.app = self.make_app(ITEM, [])
        self.ext = sys.modules[loader.module_name(ROOT / ITEM)]
        self.legacy = self.tmp / "legacy" / "claude-auth.json"
        patcher = mock.patch.object(self.ext, "LEGACY_AUTH_FILE", self.legacy)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.spec = self.app.registry.providers["claude"]
        self.data = self.tmp / "home" / "data" / "global" / "claude_subscription"

    def stored(self, access=SECRET_ACCESS, refresh=SECRET_REFRESH, expires_in=-10):
        self.ext.save(self.ext.Credentials(access, refresh, int(time.time()) + expires_in, "u@x"))

    def test_register_does_no_network_and_writes_nothing(self):
        self.assertFalse(self.data.exists())  # setUp loaded the item: no data folder, no login file
        with (
            mock.patch("urllib.request.urlopen", side_effect=AssertionError("network at register")) as urlopen,
            mock.patch("webbrowser.open", side_effect=AssertionError("browser at register")),
            mock.patch("socket.socket.connect", side_effect=AssertionError("socket at register")),
        ):
            self.make_app(ITEM, [], session_id="again")
        urlopen.assert_not_called()
        self.assertFalse(self.data.exists())
        self.assertFalse(list(self.tmp.rglob("claude-auth*")))

    def test_the_login_file_is_private_whatever_was_there_and_leaves_no_temporary_file(self):
        self.stored()
        path = self.ext.auth_file()
        path.chmod(0o644)  # a loosened file is replaced by a private one on the next save
        self.stored(access="new-access")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(path.read_text())["access"], "new-access")
        self.assertEqual([p.name for p in path.parent.iterdir()], ["claude-auth.json"])

    def test_a_failed_write_keeps_the_old_login_and_removes_the_temporary_file(self):
        self.stored()
        before = self.ext.auth_file().read_text()
        with mock.patch("os.replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.stored(access="other")
        self.assertEqual(self.ext.auth_file().read_text(), before)
        self.assertEqual([p.name for p in self.ext.auth_file().parent.iterdir()], ["claude-auth.json"])

    def test_login_never_prints_the_tokens_and_a_late_browser_times_out_with_the_fix(self):
        ext = self.ext

        def open_browser(url):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            with urllib.request.urlopen(f"{query['redirect_uri']}?code=abc&state={query['state']}", timeout=5):
                pass
            return True

        tokens = {"access_token": SECRET_ACCESS, "refresh_token": SECRET_REFRESH, "expires_in": 3600}
        out = io.StringIO()
        with (
            mock.patch.object(ext, "_token_request", return_value=tokens),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(out),
        ):
            ext.login(open_browser=open_browser, timeout=5)
        self.assertIn("Logged in to Claude.", out.getvalue())
        self.assertNotIn(SECRET_ACCESS, out.getvalue())
        self.assertNotIn(SECRET_REFRESH, out.getvalue())

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(
                TimeoutError, "Claude login timed out after 0.2s; run `minimal --login claude` again and finish in the browser"
            ):
                ext.login(open_browser=lambda url: None, timeout=0.2)

    def test_login_reports_what_the_browser_returned_as_an_error(self):
        def open_browser(url):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            params = urllib.parse.urlencode({"error": "access_denied", "error_description": "user said no", "state": query["state"]})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f"{query['redirect_uri']}?{params}", timeout=5)
            caught.exception.close()

        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "Claude login failed: user said no"):
            self.ext.login(open_browser=open_browser, timeout=5)

    def test_a_rejected_refresh_token_says_the_login_expired_and_how_to_log_in_again(self):
        self.stored()
        with mock.patch("urllib.request.urlopen", side_effect=http_error(400)):
            with self.assertRaises(RuntimeError) as caught:
                self.ext.TokenProvider()()
        message = str(caught.exception)
        self.assertIn("Claude login expired or was revoked", message)
        self.assertIn("HTTP 400", message)
        self.assertIn("Run `minimal --login claude` (or /login).", message)
        self.assertNotIn(SECRET_REFRESH, message)
        self.assertEqual(self.ext.load().refresh, SECRET_REFRESH)  # the stored login stays for the next attempt

    def test_an_unreachable_service_is_not_reported_as_an_expired_login(self):
        self.stored()
        for failure, needle in (
            (urllib.error.URLError("Temporary failure in name resolution"), "cannot reach https://api.anthropic.com/v1/oauth/token"),
            (TimeoutError("timed out"), "cannot reach"),
            (http_error(503, b"upstream down"), "HTTP 503: upstream down; retry in a few minutes"),
        ):
            with self.subTest(failure=repr(failure)), mock.patch("urllib.request.urlopen", side_effect=failure):
                with self.assertRaises(RuntimeError) as caught:
                    self.ext.TokenProvider()()
                self.assertIn(needle, str(caught.exception))
                self.assertNotIn("expired or was revoked", str(caught.exception))
                self.assertNotIn("Run `minimal --login claude`", str(caught.exception))
        self.assertEqual(self.ext.load().refresh, SECRET_REFRESH)

    def test_a_reply_that_is_not_json_or_has_no_token_is_an_error_naming_the_next_step(self):
        self.stored()
        with mock.patch("urllib.request.urlopen", return_value=Reply(b"<html>maintenance</html>")):
            with self.assertRaisesRegex(RuntimeError, "the reply was not JSON; retry in a few minutes"):
                self.ext.TokenProvider()()
        with mock.patch("urllib.request.urlopen", return_value=Reply({"expires_in": 3600})):
            with self.assertRaisesRegex(RuntimeError, "Claude token reply has no access_token; run `minimal --login claude` again."):
                self.ext.TokenProvider()()

    def test_a_good_refresh_is_stored_with_the_old_refresh_token_when_none_is_returned(self):
        self.stored()
        with mock.patch("urllib.request.urlopen", return_value=Reply({"access_token": "fresh", "expires_in": 3600})) as urlopen:
            token = self.ext.TokenProvider()()
        self.assertEqual(token.token, "fresh")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Anthropic-beta"), self.ext.OAUTH_BETA)
        self.assertEqual(json.loads(request.data)["refresh_token"], SECRET_REFRESH)
        creds = self.ext.load()
        self.assertEqual((creds.access, creds.refresh, creds.email), ("fresh", SECRET_REFRESH, "u@x"))

    def test_not_logged_in_and_unreadable_login_errors_say_how_to_fix_them(self):
        with self.assertRaises(RuntimeError) as caught:
            self.ext.TokenProvider()()
        self.assertEqual(
            str(caught.exception), "Not logged in to Claude: run `minimal --login claude` (or /login claude in the terminal UI)."
        )
        with self.assertRaisesRegex(ValueError, "Not logged in to Claude"):
            self.spec.create()
        path = self.ext.auth_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        with self.assertRaisesRegex(ValueError, f"{path} is unreadable; run `minimal --login claude` again."):
            self.ext.load()
        self.assertIsNone(self.spec.account())  # an unreadable file counts as logged out: a new login replaces it

    def test_the_default_model_is_a_setting(self):
        self.assertEqual(self.spec.default_model, "claude-sonnet-5-5")
        app = self.make_app(ITEM, [], settings={"default_model": "claude-opus-9"}, session_id="s2")
        self.assertEqual(app.registry.providers["claude"].default_model, "claude-opus-9")


if __name__ == "__main__":
    unittest.main()
