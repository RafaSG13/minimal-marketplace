"""lsp: a fake language server written as a Python script."""

import importlib.util
import os
import sys
import time
import unittest

from support import ROOT, ItemTest

ITEM = "extensions/lsp.py"

SERVER = r'''
import json, os, sys, time
marker, log = sys.argv[1], sys.argv[2]
with open(marker, "a") as f:
    f.write(f"{os.getpid()} {os.getcwd()}\n")
def send(m):
    body = json.dumps(m).encode()
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(body) + body); sys.stdout.buffer.flush()
def read():
    length = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        k, _, v = line.partition(b":")
        if k.lower() == b"content-length":
            length = int(v)
    return json.loads(sys.stdin.buffer.read(length))
def note(text):
    with open(log, "a") as f:
        f.write(text + "\n")
def publish(doc):
    text = doc["text"]
    if "SLOWSERVER" in text:
        time.sleep(3)
    diags = []
    for i, line in enumerate(text.splitlines()):
        if "ERROR" in line:
            diags.append({"range": {"start": {"line": i, "character": 0}, "end": {"line": i, "character": 5}}, "severity": 1, "message": "bad: " + line.strip()})
        if "WARN" in line:
            diags.append({"range": {"start": {"line": i, "character": 2}, "end": {"line": i, "character": 5}}, "severity": 2, "message": "careful"})
    send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": doc["uri"], "diagnostics": diags}})
while True:
    msg = read()
    if msg is None:
        break
    method, ident = msg.get("method"), msg.get("id")
    note(method or "response")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": ident, "result": {"capabilities": {}}})
    elif method == "textDocument/didOpen":
        publish(msg["params"]["textDocument"])
    elif method == "textDocument/didChange":
        d = msg["params"]["textDocument"]
        publish({"uri": d["uri"], "text": msg["params"]["contentChanges"][0]["text"]})
    elif method == "textDocument/definition":
        send({"jsonrpc": "2.0", "id": ident, "result": [{"uri": msg["params"]["textDocument"]["uri"], "range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 5}}}]})
    elif method == "textDocument/references":
        uri = msg["params"]["textDocument"]["uri"]
        send({"jsonrpc": "2.0", "id": ident, "result": [{"uri": uri, "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}}}, {"uri": uri, "range": {"start": {"line": 1, "character": 2}, "end": {"line": 1, "character": 3}}}]})
    elif method == "textDocument/hover":
        send({"jsonrpc": "2.0", "id": ident, "result": {"contents": {"kind": "markdown", "value": "def f() -> int"}}})
    elif method == "textDocument/documentSymbol":
        r = {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 0}}
        send({"jsonrpc": "2.0", "id": ident, "result": [{"name": "f", "kind": 12, "range": r, "selectionRange": r, "children": [{"name": "inner", "kind": 13, "range": r, "selectionRange": {"start": {"line": 1, "character": 4}, "end": {"line": 1, "character": 9}}}]}]})
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": ident, "result": None})
    elif method == "exit":
        break
'''


def module():
    spec = importlib.util.spec_from_file_location("lsp_under_test", ROOT / ITEM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LspTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.script = self.tmp / "ls.py"
        self.script.write_text(SERVER)
        self.marker, self.log = self.tmp / "started", self.tmp / "methods.log"
        self.work = self.tmp / "work"
        (self.work / "pkg").mkdir(parents=True)
        (self.work / "pyproject.toml").write_text("")
        self.a = self.work / "pkg" / "a.py"
        self.a.write_text("def f():\n    ERROR here\n")

    def load_lsp(self, **settings):
        command = [sys.executable, str(self.script), str(self.marker), str(self.log)]
        servers = {"python": {"command": command, "extensions": [".py"], "markers": ["pyproject.toml"]}}
        settings = {"diagnostics_wait": 0.3, "budget": 3.0, **settings}
        registry, errors = self.load(ITEM, servers=servers, **settings)
        self.assertEqual(errors, [])
        self.addCleanup(registry.dispose)
        return registry

    def ask(self, registry, **input):
        return registry.tools["lsp"].run(input, self.ctx(cwd=self.work))

    def after_edit(self, registry, name="edit", path="pkg/a.py", output="edited", is_error=False):
        event = {"name": name, "input": {"path": path}, "output": output, "is_error": is_error, "ctx": self.ctx(cwd=self.work)}
        results = registry.emit("tool_result", event)
        return results[0]["output"] if results else None

    def methods(self):
        return self.log.read_text().split()

    def test_the_tool_is_read_only_and_registering_starts_nothing(self):
        registry = self.load_lsp()
        self.assertTrue(registry.tools["lsp"].read_only is True and not registry.tools["lsp"].confirm)
        self.assertFalse(self.marker.exists())

    def test_diagnostics_definition_references_hover_symbols(self):
        registry = self.load_lsp()
        self.assertEqual(self.ask(registry, action="diagnostics", path="pkg/a.py"), "error: pkg/a.py:2:1 bad: ERROR here")
        self.assertEqual(self.ask(registry, action="definition", path="pkg/a.py", line=1, column=5), "pkg/a.py:1:5  def f():")
        self.assertEqual(
            self.ask(registry, action="references", path="pkg/a.py", line=1, column=5),
            "pkg/a.py:1:1  def f():\npkg/a.py:2:3  ERROR here",
        )
        self.assertEqual(self.ask(registry, action="hover", path="pkg/a.py", line=1, column=5), "def f() -> int")
        self.assertEqual(self.ask(registry, action="symbols", path="pkg/a.py"), "L1 function f\n  L2 variable inner")

    def test_one_server_per_root_started_in_the_project_root(self):
        registry = self.load_lsp()
        self.ask(registry, action="hover", path="pkg/a.py", line=1, column=1)
        self.ask(registry, action="symbols", path="pkg/a.py")
        starts = self.marker.read_text().splitlines()
        self.assertEqual(len(starts), 1)
        self.assertEqual(os.path.realpath(starts[0].split(" ", 1)[1]), os.path.realpath(self.work))

    def test_the_file_is_opened_once_then_changed_with_its_new_text(self):
        registry = self.load_lsp()
        self.ask(registry, action="diagnostics", path="pkg/a.py")
        self.a.write_text("def f():\n    pass\n")
        self.assertEqual(self.ask(registry, action="diagnostics", path="pkg/a.py"), "no diagnostics")
        methods = self.methods()
        self.assertEqual((methods.count("textDocument/didOpen"), methods.count("textDocument/didChange")), (1, 1))

    def test_post_edit_appends_errors_to_an_edit_result(self):
        registry = self.load_lsp()
        out = self.after_edit(registry)
        self.assertEqual(out, "edited\n[lsp] 1 error(s):\n[lsp] pkg/a.py:2:1 bad: ERROR here")
        self.a.write_text("def f():\n    pass\n")
        self.assertIsNone(self.after_edit(registry, name="write"))  # fixed: the result is left alone
        self.assertEqual(self.methods().count("textDocument/didChange"), 1)

    def test_post_edit_leaves_other_results_alone(self):
        registry = self.load_lsp()
        self.assertIsNone(self.after_edit(registry, name="bash"))
        self.assertIsNone(self.after_edit(registry, is_error=True))
        self.assertIsNone(self.after_edit(registry, path="notes.txt"))
        self.assertFalse(self.marker.exists())
        registry = self.load_lsp(post_edit=False)
        self.assertIsNone(self.after_edit(registry))

    def test_severity_warning_adds_warnings_and_max_diagnostics_cuts(self):
        self.a.write_text("WARN one\nERROR two\nERROR three\n")
        registry = self.load_lsp(severity="warning")
        out = self.after_edit(registry)
        self.assertTrue(out.startswith("edited\n[lsp] 3 diagnostic(s):\n"))
        registry = self.load_lsp(max_diagnostics=1)
        out = self.after_edit(registry)
        self.assertTrue(out.endswith("[lsp] pkg/a.py:2:1 bad: ERROR two\n[lsp] ... and 1 more"), out)

    def test_a_server_slower_than_the_budget_adds_nothing_and_does_not_block(self):
        self.a.write_text("SLOWSERVER\nERROR x\n")
        registry = self.load_lsp(budget=0.6)
        start = time.monotonic()
        self.assertIsNone(self.after_edit(registry))
        self.assertLess(time.monotonic() - start, 2.5)

    def test_a_server_that_cannot_start_adds_nothing_and_the_tool_says_why(self):
        broken = self.tmp / "broken.py"
        broken.write_text("import sys; sys.exit(3)\n")
        servers = {"python": {"command": [sys.executable, str(broken)], "extensions": [".py"], "markers": ["pyproject.toml"]}}
        registry, _ = self.load(ITEM, servers=servers, start_timeout=2)
        self.addCleanup(registry.dispose)
        self.assertIsNone(self.after_edit(registry))
        with self.assertRaisesRegex(RuntimeError, "language server python: the language server exited"):
            self.ask(registry, action="hover", path="pkg/a.py", line=1, column=1)

    def test_no_server_for_the_file_type_and_bad_arguments(self):
        registry = self.load_lsp()
        (self.work / "notes.txt").write_text("x")
        with self.assertRaisesRegex(ValueError, r"^no language server for files of type \.txt: install one of "):
            self.ask(registry, action="hover", path="notes.txt", line=1, column=1)
        with self.assertRaisesRegex(ValueError, "^action must be one of: diagnostics, definition, references, hover, symbols$"):
            self.ask(registry, action="rename", path="pkg/a.py")
        with self.assertRaisesRegex(ValueError, "^hover needs line and column"):
            self.ask(registry, action="hover", path="pkg/a.py")
        with self.assertRaisesRegex(ValueError, "^nope.py is not a file"):
            self.ask(registry, action="symbols", path="nope.py")

    def test_the_server_process_is_gone_after_dispose(self):
        registry = self.load_lsp()
        self.ask(registry, action="symbols", path="pkg/a.py")
        pid = int(self.marker.read_text().split()[0])
        os.kill(pid, 0)
        registry.dispose()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        self.fail("the language server is still running after dispose")

    def test_user_servers_merge_over_the_presets(self):
        mod = module()
        merged = mod.merged_servers({"python": {"enabled": False}, "zig": {"command": ["zls"], "extensions": [".zig"]}, "bad": {"command": "x"}})
        self.assertEqual(sorted(merged), ["go", "python", "rust", "typescript", "zig"])
        self.assertEqual(merged["python"]["command"], ["pyright-langserver", "--stdio"])
        self.assertIs(merged["python"]["enabled"], False)
        self.assertEqual(merged["typescript"]["extensions"], [".ts", ".tsx", ".js", ".jsx"])


if __name__ == "__main__":
    unittest.main()
