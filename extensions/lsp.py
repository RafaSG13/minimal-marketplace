"""Language-server tool and post-edit diagnostics: `lsp(action, path, ...)` and a type-error report after every edit. Install it with `/ext`.

The tool answers ``diagnostics``, ``definition``, ``references``, ``hover`` and ``symbols`` (1-based ``line`` and
``column``) from a language server, so the model does not have to guess from text search. After each successful ``edit``
or ``write`` of a file a server handles, the new errors are appended to the result as ``[lsp]`` lines, within a time
budget: a slow or failing server adds nothing and never blocks or fails the edit. Servers start on first use, one per
language and project root (the nearest folder above the file that holds a marker such as ``pyproject.toml``), and stop
with minimal. Presets: Python (``pyright-langserver``), TypeScript/JavaScript (``typescript-language-server``), Go
(``gopls``) and Rust (``rust-analyzer``); one is used only when its program is on PATH.

Settings (``/ext settings lsp``): ``servers`` (merged over the presets, ``{language: {command, extensions, markers,
enabled}}``), ``post_edit``, ``severity`` (``error`` or ``warning`` and above), ``max_diagnostics``, ``start_timeout``,
``request_timeout``, ``diagnostics_wait`` (seconds without a new report before the list counts as complete) and
``budget`` (seconds a post-edit lookup may take in total).
"""

import json
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

__version__ = "1.0"
__api__ = "2.4"
__tags__ = ["diagnostics", "integration"]

PRESETS = {
    "python": {
        "command": ["pyright-langserver", "--stdio"],
        "extensions": [".py"],
        "markers": ["pyproject.toml", "setup.py"],
        "install": "npm install -g pyright",
        "enabled": True,
    },
    "typescript": {
        "command": ["typescript-language-server", "--stdio"],
        "extensions": [".ts", ".tsx", ".js", ".jsx"],
        "markers": ["package.json", "tsconfig.json"],
        "install": "npm install -g typescript-language-server typescript",
        "enabled": True,
    },
    "go": {"command": ["gopls"], "extensions": [".go"], "markers": ["go.mod"], "install": "go install golang.org/x/tools/gopls@latest", "enabled": True},
    "rust": {"command": ["rust-analyzer"], "extensions": [".rs"], "markers": ["Cargo.toml"], "install": "rustup component add rust-analyzer", "enabled": True},
}
"""The built-in servers; ``settings.servers`` is merged over them key by key."""

DEFAULTS = {
    "servers": {},
    "post_edit": True,
    "severity": "error",
    "max_diagnostics": 20,
    "start_timeout": 10,
    "request_timeout": 10,
    "diagnostics_wait": 3.0,
    "budget": 4.0,
}

SCHEMA = {
    "servers": {
        "description": "Language servers by name, merged over the presets: {\"python\": {\"command\": [argv...], \"extensions\": [\".py\"], "
        "\"markers\": [\"pyproject.toml\"], \"enabled\": true}}. A server is used only when its program is on PATH.",
        "merge": "deep",
    },
    "post_edit": {"description": "After a successful edit or write, append the file's new errors to the result."},
    "severity": {"description": "Lowest severity reported: errors only, or warnings too.", "enum": ["error", "warning"]},
    "max_diagnostics": {"description": "Most diagnostics listed in one answer.", "min": 1, "max": 500},
    "start_timeout": {"description": "Seconds a server may take to start and initialise.", "min": 1, "max": 300},
    "request_timeout": {"description": "Seconds a request to a started server may take.", "min": 1, "max": 300},
    "diagnostics_wait": {"description": "Seconds without a new report from the server before diagnostics count as complete.", "min": 0.1, "max": 60},
    "budget": {"description": "Seconds a post-edit lookup may take in total; past it nothing is appended.", "min": 0.5, "max": 120},
}

KINDS = {
    1: "file", 2: "module", 3: "namespace", 4: "package", 5: "class", 6: "method", 7: "property", 8: "field", 9: "constructor",
    10: "enum", 11: "interface", 12: "function", 13: "variable", 14: "constant", 15: "string", 16: "number", 17: "boolean",
    18: "array", 19: "object", 20: "key", 21: "null", 22: "enum member", 23: "struct", 24: "event", 25: "operator", 26: "type parameter",
}
SEVERITY_NAMES = {1: "error", 2: "warning", 3: "info", 4: "hint"}
ACTIONS = ("diagnostics", "definition", "references", "hover", "symbols")


def to_uri(path):
    return "file://" + quote(str(path))


def from_uri(uri):
    return unquote(urlparse(uri).path)


class Client:
    """One language server process, spoken to with Content-Length framed JSON-RPC."""

    def __init__(self, language, root, argv, start_timeout, request_timeout):
        self.language, self.root, self.argv = language, root, argv
        self.start_timeout, self.request_timeout = start_timeout, request_timeout
        self.proc = None
        self.lock = threading.Lock()
        self.pending = {}
        self.next_id = 0
        self.versions = {}
        self.diagnostics = {}
        self.reports = {}
        self.last_report = {}
        self.baseline = {}
        self.op = threading.RLock()

    def start(self):
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BRAVE_API_KEY")}
        self.proc = subprocess.Popen(
            self.argv, cwd=self.root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True
        )
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        try:
            self.request(
                "initialize",
                {
                    "processId": os.getpid(),
                    "rootUri": to_uri(self.root),
                    "workspaceFolders": [{"uri": to_uri(self.root), "name": os.path.basename(self.root) or "root"}],
                    "capabilities": {
                        "textDocument": {
                            "synchronization": {"didSave": False},
                            "publishDiagnostics": {"relatedInformation": False},
                            "hover": {"contentFormat": ["plaintext", "markdown"]},
                            "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                        },
                        "workspace": {"configuration": True, "workspaceFolders": True},
                    },
                },
                self.start_timeout,
            )
            self.notify("initialized", {})
        except Exception:
            self.stop()
            raise

    @property
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _send(self, message):
        body = json.dumps(message).encode("utf-8")
        try:
            self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
            self.proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            pass

    def _read(self, proc):
        try:
            out = proc.stdout
            while True:
                length = None
                while True:
                    header = out.readline()
                    if not header:
                        return
                    header = header.strip()
                    if not header:
                        break
                    name, _, value = header.partition(b":")
                    if name.lower() == b"content-length":
                        length = int(value)
                if length is None:
                    continue
                try:
                    message = json.loads(out.read(length))
                except ValueError:
                    continue
                self._handle(message)
        finally:
            with self.lock:
                waiters, self.pending = list(self.pending.values()), {}
            for waiter in waiters:
                waiter.put({"error": {"message": "the language server exited"}})
            proc.stdout.close()

    def _handle(self, message):
        if "id" in message and ("result" in message or "error" in message):
            with self.lock:
                waiter = self.pending.pop(message["id"], None)
            if waiter is not None:
                waiter.put(message)
        elif message.get("method") == "textDocument/publishDiagnostics":
            params = message.get("params") or {}
            uri = params.get("uri", "")
            with self.lock:
                self.diagnostics[uri] = params.get("diagnostics") or []
                self.reports[uri] = self.reports.get(uri, 0) + 1
                self.last_report[uri] = time.monotonic()
        elif "id" in message and "method" in message:  # a request of the server: answer so it does not wait for us
            method = message["method"]
            result = [None] * len((message.get("params") or {}).get("items", [])) if method == "workspace/configuration" else None
            self._send({"jsonrpc": "2.0", "id": message["id"], "result": result})

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method, params, timeout=None, cancelled=lambda: False):
        timeout = timeout or self.request_timeout
        waiter = queue.Queue()
        with self.lock:
            self.next_id += 1
            ident = self.next_id
            self.pending[ident] = waiter
        self._send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            try:
                reply = waiter.get(timeout=0.1)
                break
            except queue.Empty:
                pass
            if cancelled():
                raise RuntimeError("interrupted")
            if time.monotonic() >= deadline:
                with self.lock:
                    self.pending.pop(ident, None)
                raise RuntimeError(f"language server {self.language}: {method} timed out after {timeout}s")
        if "error" in reply:
            error = reply["error"]
            raise RuntimeError(f"language server {self.language}: {error.get('message', error) if isinstance(error, dict) else error}")
        return reply.get("result")

    def sync(self, path):
        """Tell the server the file's current text (open it, or change it with the next version)."""
        uri = to_uri(path)
        text = Path(path).read_bytes().decode("utf-8", errors="replace")
        version = self.versions.get(uri, 0) + 1
        self.versions[uri] = version
        with self.lock:
            self.baseline[uri] = self.reports.get(uri, 0)
        if version == 1:
            self.notify(
                "textDocument/didOpen",
                {"textDocument": {"uri": uri, "languageId": self.language, "version": 1, "text": text}},
            )
        else:
            self.notify(
                "textDocument/didChange",
                {"textDocument": {"uri": uri, "version": version}, "contentChanges": [{"text": text}]},
            )
        return uri

    def wait_diagnostics(self, uri, quiet, deadline=None, cancelled=lambda: False):
        """Wait until ``quiet`` seconds pass with no new report for ``uri`` (counted from now); the diagnostics."""
        since = time.monotonic()
        while True:
            now = time.monotonic()
            with self.lock:
                last = max(since, self.last_report.get(uri, 0))
            if now - last >= quiet or (deadline is not None and now >= deadline) or cancelled():
                break
            time.sleep(0.05)
        with self.lock:  # a list the server published before this change says nothing about it
            fresh = self.reports.get(uri, 0) > self.baseline.get(uri, 0)
            return list(self.diagnostics.get(uri, [])) if fresh else []

    def stop(self):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        if proc.poll() is None:
            try:
                self.proc = proc
                self.request("shutdown", None, 2)
                self.notify("exit", None)
            except Exception:
                pass
            finally:
                self.proc = None
        try:
            proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is None:
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                proc.wait()


def merged_servers(user):
    """``PRESETS`` with the ``user`` entries merged over them key by key; malformed entries dropped."""
    servers = {name: {**entry} for name, entry in PRESETS.items()}
    for name, entry in (user or {}).items():
        if not isinstance(entry, dict):
            continue
        servers[name] = {**servers.get(name, {"enabled": True, "install": ""}), **entry}
    return {
        name: e
        for name, e in servers.items()
        if isinstance(e.get("command"), list) and e["command"] and isinstance(e.get("extensions"), list) and isinstance(e.get("markers", []), list)
    }


def render_location(loc, cwd):
    uri = loc.get("uri") or loc.get("targetUri")
    rng = loc.get("range") or loc.get("targetSelectionRange") or {}
    start = rng.get("start", {})
    path = from_uri(uri) if uri else "?"
    try:
        shown = os.path.relpath(path, cwd) if path.startswith(cwd) else path
    except ValueError:
        shown = path
    line, col = start.get("line", 0) + 1, start.get("character", 0) + 1
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[line - 1].strip()
    except (OSError, IndexError):
        text = ""
    return f"{shown}:{line}:{col}" + (f"  {text}" if text else "")


def hover_text(contents):
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        return contents.get("value", "")
    if isinstance(contents, list):
        return "\n\n".join(hover_text(c) for c in contents)
    return ""


def symbol_lines(symbols, depth=0):
    lines = []
    for s in symbols or []:
        rng = s.get("selectionRange") or s.get("range") or (s.get("location") or {}).get("range") or {}
        line = rng.get("start", {}).get("line", 0) + 1
        lines.append(f"{'  ' * depth}L{line} {KINDS.get(s.get('kind'), 'symbol')} {s.get('name', '?')}")
        lines += symbol_lines(s.get("children"), depth + 1)
    return lines


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    servers = merged_servers(settings["servers"])
    clients = {}
    clients_lock = threading.Lock()
    stopping = threading.Event()

    def find_server(path):
        """``(language, entry)`` for ``path``'s extension whose program is on PATH, or ``None``."""
        suffix = Path(path).suffix.lower()
        for language, entry in servers.items():
            if entry.get("enabled", True) and suffix in [e.lower() for e in entry["extensions"]] and shutil.which(entry["command"][0]):
                return language, entry
        return None

    def root_of(path, entry, cwd):
        folder = Path(path).resolve().parent
        for candidate in (folder, *folder.parents):
            if any((candidate / m).exists() for m in entry.get("markers", [])):
                return str(candidate)
        return cwd

    def client_for(language, entry, path, cwd):
        root = root_of(path, entry, cwd)
        key = (language, root)
        with clients_lock:
            client = clients.get(key)
            if client is None or not client.alive:
                if stopping.is_set():
                    raise RuntimeError("language servers are shutting down")
                client = Client(language, root, [shutil.which(entry["command"][0]), *entry["command"][1:]], settings["start_timeout"], settings["request_timeout"])
                clients[key] = client
        with client.op:
            if not client.alive:
                client.start()
        return client

    def resolve(path, ctx):
        if not isinstance(path, str) or not path:
            raise ValueError("path is required")
        full = os.path.realpath(os.path.join(ctx.cwd, path))
        if not os.path.isfile(full):
            raise ValueError(f"{path} is not a file; check the path with glob")
        return full

    def severity_ok(d):
        return d.get("severity", 1) <= (1 if settings["severity"] == "error" else 2)

    def format_diagnostics(path, diags, cwd):
        shown = os.path.relpath(path, cwd) if path.startswith(cwd) else path
        rows = []
        for d in sorted(diags, key=lambda d: (d["range"]["start"]["line"], d["range"]["start"]["character"])):
            start = d["range"]["start"]
            message = " ".join(str(d.get("message", "")).split())
            rows.append((SEVERITY_NAMES.get(d.get("severity", 1), "error"), f"{shown}:{start['line'] + 1}:{start['character'] + 1} {message}"))
        return rows

    def lsp(input, ctx):
        action = input.get("action")
        if action not in ACTIONS:
            raise ValueError(f"action must be one of: {', '.join(ACTIONS)}")
        full = resolve(input.get("path"), ctx)
        found = find_server(full)
        if found is None:
            suffix = Path(full).suffix or "(none)"
            hints = "; ".join(f"{e['command'][0]} ({e.get('install') or 'see its docs'}) for {' '.join(e['extensions'])}" for e in servers.values())
            raise ValueError(f"no language server for files of type {suffix}: install one of {hints}, or add one to extensions.settings.lsp.servers")
        language, entry = found
        client = client_for(language, entry, full, ctx.cwd)
        with client.op:
            uri = client.sync(full)
            cancelled = lambda: ctx.cancelled  # noqa: E731
            if action == "diagnostics":
                diags = [d for d in client.wait_diagnostics(uri, settings["diagnostics_wait"], cancelled=cancelled) if severity_ok(d)]
                if not diags:
                    return "no diagnostics"
                rows = format_diagnostics(full, diags, ctx.cwd)
                out = [f"{sev}: {text}" for sev, text in rows[: settings["max_diagnostics"]]]
                if len(rows) > len(out):
                    out.append(f"[{len(rows) - len(out)} more; fix these first or raise max_diagnostics]")
                return "\n".join(out)
            if action == "symbols":
                result = client.request("textDocument/documentSymbol", {"textDocument": {"uri": uri}}, cancelled=cancelled)
                lines = symbol_lines(result)
                return "\n".join(lines[:500]) if lines else "(no symbols)"
            line, column = input.get("line"), input.get("column")
            if isinstance(line, bool) or not isinstance(line, int) or line < 1 or isinstance(column, bool) or not isinstance(column, int) or column < 1:
                raise ValueError(f"{action} needs line and column (both 1-based integers)")
            position = {"line": line - 1, "character": column - 1}
            if action == "hover":
                result = client.request("textDocument/hover", {"textDocument": {"uri": uri}, "position": position}, cancelled=cancelled)
                text = hover_text((result or {}).get("contents")).strip()
                return text or "(nothing to show at that position)"
            method = "textDocument/definition" if action == "definition" else "textDocument/references"
            params = {"textDocument": {"uri": uri}, "position": position}
            if action == "references":
                params["context"] = {"includeDeclaration": True}
            result = client.request(method, params, cancelled=cancelled)
            locations = result if isinstance(result, list) else [result] if result else []
            if not locations:
                return "(none found)"
            lines = [render_location(loc, ctx.cwd) for loc in locations[: settings["max_diagnostics"]]]
            if len(locations) > len(lines):
                lines.append(f"[{len(locations) - len(lines)} more]")
            return "\n".join(lines)

    minimal.register_tool(
        "lsp",
        lsp,
        "Ask a language server about a file: diagnostics (errors), definition, references and hover at a line and column "
        "(1-based), or symbols (an outline). Prefer it over grep for 'where is this defined/used' and over running the "
        "type checker for one file. Needs the language's server on PATH (pyright, typescript-language-server, gopls, rust-analyzer).",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": list(ACTIONS)},
                "path": {"type": "string", "description": "File, relative to the working folder"},
                "line": {"type": "integer", "description": "1-based; for definition, references and hover"},
                "column": {"type": "integer", "description": "1-based; for definition, references and hover"},
            },
            "required": ["action", "path"],
        },
        read_only=True,
    )

    @minimal.on("tool_result")
    def after_edit(event):
        if not settings["post_edit"] or event["name"] not in ("edit", "write") or event["is_error"]:
            return None
        ctx = event["ctx"]
        path = (event.get("input") or {}).get("path")
        if not isinstance(path, str) or not path:
            return None
        full = os.path.realpath(os.path.join(ctx.cwd, path))
        found = find_server(full)
        if found is None or not os.path.isfile(full):
            return None
        language, entry = found
        deadline = time.monotonic() + settings["budget"]
        answer = queue.Queue()

        def work():
            try:
                client = client_for(language, entry, full, ctx.cwd)
                with client.op:
                    uri = client.sync(full)
                    diags = client.wait_diagnostics(uri, settings["diagnostics_wait"], deadline, stopping.is_set)
                answer.put([d for d in diags if severity_ok(d)])
            except Exception:
                answer.put(None)

        threading.Thread(target=work, name="lsp-post-edit", daemon=True).start()
        try:
            diags = answer.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            return None
        if not diags or time.monotonic() > deadline + 0.5:
            return None
        rows = format_diagnostics(full, diags, ctx.cwd)
        noun = "error(s)" if settings["severity"] == "error" else "diagnostic(s)"
        lines = [f"[lsp] {len(rows)} {noun}:"] + [f"[lsp] {text}" for _, text in rows[: settings["max_diagnostics"]]]
        if len(rows) > settings["max_diagnostics"]:
            lines.append(f"[lsp] ... and {len(rows) - settings['max_diagnostics']} more")
        return {"output": event["output"] + "\n" + "\n".join(lines)}

    @minimal.on_dispose
    def stop_all():
        stopping.set()
        with clients_lock:
            current = list(clients.values())
        threads = [threading.Thread(target=c.stop) for c in current]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
