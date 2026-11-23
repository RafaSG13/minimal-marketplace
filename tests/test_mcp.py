"""mcp: a fake stdio MCP server written as a Python script."""

import base64
import importlib.util
import json
import os
import sys
import threading
import time
import unittest

from support import ROOT, ItemTest

ITEM = "extensions/mcp.py"

SERVER = r'''
import json, os, sys, time
marker = sys.argv[1]
with open(marker, "a") as f:
    f.write(str(os.getpid()) + "\n")
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
PAGE1 = [
    {"name": "echo", "description": "Echo the text back.", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}, "annotations": {"readOnlyHint": True}},
    {"name": "fail", "description": "Always fails.", "inputSchema": {"type": "object"}},
    {"name": "pic", "description": "A picture.", "inputSchema": {"type": "object"}},
]
PAGE2 = [
    {"name": "doc", "description": "An embedded resource.", "inputSchema": {"type": "object"}},
    {"name": "crash", "description": "Exits.", "inputSchema": {"type": "object"}},
    {"name": "slow", "description": "Sleeps.", "inputSchema": {"type": "object"}},
]
def send(m):
    sys.stdout.write(json.dumps(m) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    msg = json.loads(line)
    method, ident = msg.get("method"), msg.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": ident, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "1"}}})
    elif method == "tools/list":
        if not (msg.get("params") or {}).get("cursor"):
            send({"jsonrpc": "2.0", "id": ident, "result": {"tools": PAGE1, "nextCursor": "p2"}})
        else:
            send({"jsonrpc": "2.0", "id": ident, "result": {"tools": PAGE2}})
    elif method == "tools/call":
        name, args = msg["params"]["name"], msg["params"].get("arguments") or {}
        if name == "echo":
            send({"jsonrpc": "2.0", "id": ident, "result": {"content": [{"type": "text", "text": "echo: " + args.get("text", "")}]}})
        elif name == "fail":
            send({"jsonrpc": "2.0", "id": ident, "result": {"isError": True, "content": [{"type": "text", "text": "it broke"}]}})
        elif name == "pic":
            send({"jsonrpc": "2.0", "id": ident, "result": {"content": [{"type": "text", "text": "see"}, {"type": "image", "data": PNG, "mimeType": "image/png"}]}})
        elif name == "doc":
            send({"jsonrpc": "2.0", "id": ident, "result": {"content": [{"type": "resource", "resource": {"uri": "file:///a", "text": "file text"}}]}})
        elif name == "crash":
            sys.stderr.write("boom\n"); sys.stderr.flush()
            os._exit(1)
        elif name == "slow":
            time.sleep(10)
'''


def module():
    spec = importlib.util.spec_from_file_location("mcp_under_test", ROOT / ITEM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class McpTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.script = self.tmp / "server.py"
        self.script.write_text(SERVER)
        self.marker = self.tmp / "started"
        self.mod = module()
        self.entry = {"command": [sys.executable, str(self.script), str(self.marker)], "env": {}, "cwd": ""}
        self.cache_path = self.tmp / "home" / "data" / "global" / "mcp" / "mcp_cache.json"

    def server_settings(self, **extra):
        return {"servers": {"fake": {"command": self.entry["command"], **extra}}}

    def prime_cache(self, tools=None, entry=None):
        entry = entry or self.entry
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tools = tools if tools is not None else [
            {"name": "echo", "description": "Echo the text back.", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}, "annotations": {"readOnlyHint": True}},
            {"name": "fail", "description": "Always fails.", "inputSchema": {"type": "object"}},
            {"name": "pic", "inputSchema": {"type": "object"}},
            {"name": "doc", "inputSchema": {"type": "object"}},
            {"name": "crash", "inputSchema": {"type": "object"}},
            {"name": "slow", "inputSchema": {"type": "object"}},
        ]
        self.cache_path.write_text(json.dumps({"fake": {"hash": self.mod.config_hash({**entry, "env": entry.get("env", {}), "cwd": entry.get("cwd", "")}), "tools": tools}}))

    def load_mcp(self, server=None, **settings):
        self.prime_cache()
        registry, errors = self.load(ITEM, **{**self.server_settings(**(server or {})), **settings})
        self.assertEqual(errors, [])
        self.addCleanup(registry.dispose)
        return registry

    def call(self, registry, tool, **input):
        return registry.tools[f"mcp__fake__{tool}"].run(input, self.ctx())

    def test_cached_tools_register_without_starting_the_server(self):
        registry = self.load_mcp()
        self.assertEqual(sorted(t for t in registry.tools if t.startswith("mcp__")), [f"mcp__fake__{n}" for n in ("crash", "doc", "echo", "fail", "pic", "slow")])
        self.assertFalse(self.marker.exists())
        self.assertEqual(registry.tools["mcp__fake__echo"].description, "[fake] Echo the text back.")

    def test_a_call_starts_the_server_once_and_round_trips(self):
        registry = self.load_mcp()
        self.assertEqual(self.call(registry, "echo", text="hi"), "echo: hi")
        self.assertEqual(self.call(registry, "echo", text="again"), "echo: again")
        self.assertEqual(len(self.marker.read_text().split()), 1)

    def test_errors_images_and_resources(self):
        registry = self.load_mcp()
        with self.assertRaisesRegex(RuntimeError, "^it broke$"):
            self.call(registry, "fail")
        out = self.call(registry, "pic")
        self.assertEqual(out[0], {"type": "text", "text": "see"})
        self.assertEqual(out[1]["type"], "image")
        self.assertEqual(out[1]["source"]["media_type"], "image/png")
        self.assertEqual(base64.b64decode(out[1]["source"]["data"])[:4], b"\x89PNG")
        self.assertEqual(self.call(registry, "doc"), "file text")

    def test_every_tool_confirms_unless_the_server_is_trusted_for_read_only_hints(self):
        registry = self.load_mcp()
        for name in ("echo", "fail"):
            tool = registry.tools[f"mcp__fake__{name}"]
            self.assertTrue(tool.confirm is True and not tool.read_only, name)
        registry = self.load_mcp(server={"trust_hints": True})
        echo, fail = registry.tools["mcp__fake__echo"], registry.tools["mcp__fake__fail"]
        self.assertTrue(echo.read_only is True and not echo.confirm)
        self.assertTrue(fail.confirm is True and not fail.read_only)

    def test_long_output_is_clipped(self):
        registry = self.load_mcp(max_chars=1000)
        out = self.call(registry, "echo", text="x" * 2000)
        self.assertRegex(out, r"\n\[clipped 1006 chars; ask the server for less")

    def test_tool_names_are_sanitised_and_truncated(self):
        self.assertEqual(self.mod.tool_name("fs", "read file!"), "mcp__fs__read_file_")
        long = self.mod.tool_name("srv", "t" * 80)
        self.assertEqual(len(long), 64)
        self.assertRegex(long, r"^mcp__srv__t+_[0-9a-f]{8}$")
        self.assertNotEqual(long, self.mod.tool_name("srv", "t" * 81))

    def test_the_process_is_gone_after_dispose(self):
        registry = self.load_mcp()
        self.call(registry, "echo", text="x")
        pid = int(self.marker.read_text().split()[0])
        os.kill(pid, 0)  # alive
        registry.dispose()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        self.fail("the server is still running after dispose")

    def test_a_crashed_server_restarts_once_then_errors_with_its_stderr(self):
        registry = self.load_mcp()
        with self.assertRaisesRegex(RuntimeError, "the server exited"):
            self.call(registry, "crash")
        self.assertEqual(self.call(registry, "echo", text="back"), "echo: back")  # restarted
        with self.assertRaisesRegex(RuntimeError, "the server exited"):
            self.call(registry, "crash")
        with self.assertRaises(RuntimeError) as caught:
            self.call(registry, "echo", text="x")
        self.assertIn("mcp server fake exited again after a restart", str(caught.exception))
        self.assertIn("boom", str(caught.exception))
        self.assertEqual(len(self.marker.read_text().split()), 2)  # started once, restarted once

    def test_a_slow_call_times_out(self):
        registry = self.load_mcp(call_timeout=1)
        start = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, r"^mcp server fake: tools/call timed out after 1s$"):
            self.call(registry, "slow")
        self.assertLess(time.monotonic() - start, 6)

    def test_a_missing_program_says_how_to_fix_it(self):
        entry = {"command": ["definitely-not-installed-xyz"], "env": {}, "cwd": ""}
        self.prime_cache(entry=entry)
        registry, _ = self.load(ITEM, servers={"fake": {"command": entry["command"]}})
        with self.assertRaisesRegex(ValueError, r"^mcp server fake: 'definitely-not-installed-xyz' is not installed or not on PATH; install it or fix extensions\.settings\.mcp\.servers\.fake\.command$"):
            self.call(registry, "echo", text="x")

    def test_a_changed_command_makes_the_cache_stale_and_registers_nothing(self):
        self.prime_cache()
        registry, _ = self.load(ITEM, servers={"fake": {"command": [*self.entry["command"], "--other"]}})
        self.assertEqual([t for t in registry.tools if t.startswith("mcp__")], [])

    def test_discovery_on_session_start_lists_every_page_writes_the_cache_and_notifies(self):
        registry, errors = self.load(ITEM, **self.server_settings())
        self.assertEqual((errors, self.marker.exists()), ([], False))  # loading starts nothing
        notes = []
        ctx = self.ctx(notify=lambda text, kind="info": notes.append((text, kind)))
        registry.emit("session_start", {"ctx": ctx, "resumed": False})
        deadline = time.monotonic() + 15
        while not notes and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(notes, [("mcp: fake: 6 tools found; run /reload to use them", "info")])
        cached = json.loads(self.cache_path.read_text())["fake"]
        self.assertEqual([t["name"] for t in cached["tools"]], ["echo", "fail", "pic", "doc", "crash", "slow"])
        self.assertEqual(oct(self.cache_path.stat().st_mode & 0o777), "0o600")
        pid = int(self.marker.read_text().split()[0])
        time.sleep(0.5)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)  # the discovery process does not stay
        registry.dispose()
        registry2, _ = self.load(ITEM, **self.server_settings())
        self.assertIn("mcp__fake__echo", registry2.tools)  # the next load registers the cached tools

    def test_a_server_that_fails_to_start_is_reported_by_the_notice(self):
        registry, _ = self.load(ITEM, servers={"broken": {"command": ["definitely-not-installed-xyz"]}})
        notes = []
        registry.emit("session_start", {"ctx": self.ctx(notify=lambda text, kind="info": notes.append((text, kind))), "resumed": False})
        deadline = time.monotonic() + 10
        while not notes and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(notes[0][1], "warning")
        self.assertIn("mcp: broken: mcp server broken: 'definitely-not-installed-xyz' is not installed", notes[0][0])

    def test_mcp_command_lists_and_refreshes(self):
        registry = self.load_mcp()
        ctx = self.ctx()
        listing = registry.commands["mcp"].run("", ctx)
        self.assertRegex(listing, r"^fake +cached +6 tools +")
        self.call(registry, "echo", text="x")
        self.assertRegex(registry.commands["mcp"].run("", ctx), r"^fake +running +6 tools")
        self.assertEqual(registry.commands["mcp"].run("refresh nope", ctx), "unknown server 'nope'; configured: fake")
        out = registry.commands["mcp"].run("refresh fake", ctx)
        self.assertEqual(out, "fake: 6 tools found\nRun /reload to use the new tool lists.")

    def test_bad_server_entries_are_reported_and_skipped(self):
        servers = {
            "Bad Name": {"command": ["x"]},
            "nocmd": {},
            "badenv": {"command": ["x"], "env": {"A": 1}},
            "extra": {"command": ["x"], "colour": "red"},
            "ok": {"command": ["x"]},
        }
        registry, errors = self.load(ITEM, servers=servers)
        self.assertEqual(errors, [])
        problems = "\n".join(registry.problems)
        for needle in ("'Bad Name' is not a server name", "nocmd: command must be a non-empty list", "badenv: env must be an object of text values", "extra: unknown field 'colour'"):
            self.assertIn(needle, problems)
        self.assertEqual(len(registry.problems), 4)
        self.assertIn("ok  ", registry.commands["mcp"].run("", self.ctx()) + "  ")


if __name__ == "__main__":
    unittest.main()
