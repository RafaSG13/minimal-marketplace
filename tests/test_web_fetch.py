"""tools/web_fetch: a local http.server thread."""

import http.server
import importlib.util
import socket
import threading
import unittest
from unittest import mock

from support import ROOT, ItemTest

ITEM = "tools/web_fetch.py"

HTML = """<html><head><title>Doc &amp; Page</title><style>p{}</style><script>alert(1)</script></head>
<body><nav><a href="/x">menu</a></nav>
<h1>Hello</h1><p>Some <b>bold</b> and <em>soft</em> text with <a href="/rel">a link</a> and <code>code()</code>.</p>
<ul><li>one</li><li>two<ul><li>nested</li></ul></li></ul><ol><li>first</li><li>second</li></ol>
<pre>line 1
  line 2</pre>
<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>
<blockquote>quoted</blockquote>
<footer>copyright</footer></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path
        if path == "/page":
            self.send(200, "text/html; charset=utf-8", HTML.encode())
        elif path == "/json":
            self.send(200, "application/json", b'{"b":[1,2],"a":"x"}')
        elif path == "/text":
            self.send(200, "text/plain", b"plain words")
        elif path == "/png":
            self.send(200, "image/png", b"\x89PNG")
        elif path == "/big":
            self.send(200, "text/plain", b"a" * 2_500_000)
        elif path.startswith("/hop/"):
            n = int(path.split("/")[2])
            self.send_response(302)
            self.send_header("Location", f"/hop/{n + 1}" if n < 9 else "/text")
            self.end_headers()
        elif path == "/to-text":
            self.send_response(301)
            self.send_header("Location", "/text")
            self.end_headers()
        elif path == "/to-localhost":
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{self.server.server_port}/text")
            self.end_headers()
        else:
            self.send(404, "text/plain", b"nope here")

    def send(self, code, kind, body):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FetchTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def fetch(self, path="", registry=None, **input):
        registry = registry or self.load(ITEM, allow_private=True)[0]
        return registry.tools["web_fetch"].run({"url": self.base + path, **input}, self.ctx())

    def test_the_tool_is_read_only_and_says_when_to_use_it(self):
        registry, errors = self.load(ITEM)
        self.assertEqual(errors, [])
        self.assertTrue(registry.tools["web_fetch"].read_only is True and not registry.tools["web_fetch"].confirm)
        self.assertIn("prefer it over `bash curl`", registry.tools["web_fetch"].description)

    def test_html_becomes_markdown_without_scripts_styles_nav_and_footer(self):
        out = self.fetch("/page")
        self.assertEqual(
            out,
            "# Doc & Page\n\n# Hello\n\nSome **bold** and *soft* text with [a link](/rel) and `code()`.\n\n"
            "- one\n- two\n  - nested\n\n1. first\n2. second\n\n```\nline 1\n  line 2\n```\n\nA | B\n1 | 2\n\n> quoted",
        )
        for gone in ("alert", "menu", "copyright", "p{}"):
            self.assertNotIn(gone, out)

    def test_text_format_has_no_markup_and_raw_keeps_the_html(self):
        text = self.fetch("/page", format="text")
        self.assertIn("Hello\n\nSome bold and soft text with a link and code().", text)
        self.assertNotIn("**", text)
        self.assertIn("<h1>Hello</h1>", self.fetch("/page", format="raw"))

    def test_json_is_pretty_printed_and_text_is_left_alone(self):
        self.assertEqual(self.fetch("/json"), '{\n  "b": [\n    1,\n    2\n  ],\n  "a": "x"\n}')
        self.assertEqual(self.fetch("/text"), "plain words")

    def test_other_content_types_are_refused(self):
        with self.assertRaisesRegex(ValueError, r"^unsupported content type image/png; web_fetch reads HTML, JSON and text"):
            self.fetch("/png")

    def test_a_redirect_is_followed_and_reported_but_too_many_are_refused(self):
        self.assertEqual(self.fetch("/to-text"), f"{self.base}/text\n\nplain words")
        with self.assertRaisesRegex(RuntimeError, r"^too many redirects \(more than 5\) from the first URL"):
            self.fetch("/hop/0")

    def test_the_body_is_cut_at_two_megabytes_and_the_output_at_max_chars(self):
        registry, _ = self.load(ITEM, allow_private=True, max_chars=1000)
        out = self.fetch("/big", registry)
        self.assertTrue(out.startswith("a" * 1000 + "\n[clipped 1999000 chars; fetch a more specific URL or raise max_chars (at most 1000)]"))
        self.assertTrue(out.endswith("\n[the response was cut at 2 MB]"))
        self.assertEqual(len(self.fetch("/big", registry, max_chars=5000).split("\n[clipped")[0]), 1000)

    def test_errors_say_the_status_and_what_to_check(self):
        with self.assertRaisesRegex(RuntimeError, r"/missing answered HTTP 404 Not Found: nope here$"):
            self.fetch("/missing")
        with self.assertRaisesRegex(ValueError, "is not an http or https URL"):
            self.load(ITEM)[0].tools["web_fetch"].run({"url": "file:///etc/passwd"}, self.ctx())

    def test_private_addresses_are_refused_by_default_and_allowed_by_setting(self):
        registry, _ = self.load(ITEM)
        with self.assertRaisesRegex(ValueError, r"^127\.0\.0\.1 resolves to a private address; set allow_private to fetch it$"):
            registry.tools["web_fetch"].run({"url": self.base + "/text"}, self.ctx())
        self.assertEqual(self.fetch("/text"), "plain words")  # allow_private

    def test_a_redirect_to_a_private_address_is_refused_too(self):
        registry, _ = self.load(ITEM)
        real_getaddrinfo, real_create = socket.getaddrinfo, socket.create_connection

        def getaddrinfo(host, *args, **kw):
            if host == "pub.test":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
            return real_getaddrinfo(host, *args, **kw)

        def create(address, *args, **kw):
            host, port = address
            return real_create(("127.0.0.1", port) if host == "pub.test" else address, *args, **kw)

        url = f"http://pub.test:{self.server.server_port}/to-localhost"
        with mock.patch("socket.getaddrinfo", getaddrinfo), mock.patch("socket.create_connection", create):
            with self.assertRaisesRegex(ValueError, r"^localhost resolves to a private address"):
                registry.tools["web_fetch"].run({"url": url}, self.ctx())

    def test_assert_public_classifies_addresses(self):
        spec = importlib.util.spec_from_file_location("web_fetch_under_test", ROOT / ITEM)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for ip, private in (("10.0.0.5", True), ("192.168.1.1", True), ("169.254.169.254", True), ("::1", True), ("0.0.0.0", True), ("93.184.216.34", False)):
            with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", (ip, 0))]):
                if private:
                    with self.assertRaises(ValueError, msg=ip):
                        mod.assert_public("h.test", False)
                else:
                    mod.assert_public("h.test", False)
                mod.assert_public("h.test", True)

    def test_progress_is_shown_and_cleared(self):
        notes = []
        registry, _ = self.load(ITEM, allow_private=True)
        registry.tools["web_fetch"].run({"url": self.base + "/text"}, self.ctx(progress=lambda text, **k: notes.append(text)))
        self.assertEqual(notes, ["fetching 127.0.0.1", None])


if __name__ == "__main__":
    unittest.main()
