"""MCP client: use the tools of Model Context Protocol servers (stdio) as tools of the model. Install it with `/ext`.

Declare servers in ``extensions.settings.mcp.servers`` (global; a project's only after ``/trust``)::

    {"servers": {"fs": {"command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."]}}}

Each server's tools appear as ``mcp__<server>__<tool>``. Starting minimal never starts a server: the tool list of each
server is cached (``mcp_cache.json`` in the extension's global data folder, keyed by a hash of ``command``, ``env`` and
``cwd``), and the cached tools are registered at load. After ``session_start`` a background thread lists the servers
that are not cached yet and says ``mcp: <server>: N tools found; run /reload to use them``. A server starts on its first
tool call and stays for the session; one that crashes restarts once. Every tool asks before it runs, unless the server
has ``trust_hints`` and marks the tool ``readOnlyHint`` (then it runs as a read-only tool). ``/mcp`` lists the servers;
``/mcp refresh [server]`` lists them again.

Settings (``/ext settings mcp``): ``servers`` (``{name: {command, env, cwd, trust_hints, enabled}}``, merged key by key
across settings layers), ``timeout`` (seconds to start and list), ``call_timeout`` (seconds for one call) and
``max_chars`` (longest tool output).
"""

import hashlib
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
from collections import deque

from minimal.api import image_block

__version__ = "1.0"
__api__ = "2.4"
__tags__ = ["integration"]

PROTOCOL = "2025-06-18"
SERVER_NAME = re.compile(r"[a-z0-9_-]+")
SECRET_ENV = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BRAVE_API_KEY")
"""Variables a server does not inherit (its own ``env`` setting can still give it one)."""

DEFAULTS = {"servers": {}, "timeout": 30, "call_timeout": 120, "max_chars": 30000}

SCHEMA = {
    "servers": {
        "description": "MCP servers by name ([a-z0-9_-]): {\"command\": [argv...], \"env\": {}, \"cwd\": \"\", "
        "\"trust_hints\": false, \"enabled\": true}. Merged key by key across settings layers; a project's servers "
        "apply only after /trust. trust_hints lets a server's readOnlyHint skip the confirmation prompt.",
        "merge": "deep",
    },
    "timeout": {"description": "Seconds to start a server and list its tools.", "min": 1, "max": 600},
    "call_timeout": {"description": "Seconds one tool call may take.", "min": 1, "max": 3600},
    "max_chars": {"description": "Longest tool output in characters; the rest is cut.", "min": 1000, "max": 1_000_000},
}


def tool_name(server, tool):
    """``mcp__<server>__<tool>`` with characters outside ``[A-Za-z0-9_-]`` turned into ``_``; over 64 characters it
    becomes the first 55, ``_`` and 8 hex digits of the SHA-1 of the whole name."""
    full = "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", f"{server}__{tool}")
    if len(full) <= 64:
        return full
    return full[:55] + "_" + hashlib.sha1(full.encode()).hexdigest()[:8]


def config_hash(entry):
    """What makes a cached tool list stale: the command, its environment and its folder."""
    keys = {k: entry[k] for k in ("command", "env", "cwd")}
    return hashlib.sha256(json.dumps(keys, sort_keys=True).encode()).hexdigest()


def parse_servers(value):
    """``(servers, problems)``: the valid entries of the ``servers`` setting, normalised, and one text per bad one."""
    servers, problems = {}, []
    where = "extensions.settings.mcp.servers"
    for name, raw in (value or {}).items():
        at = f"{where}.{name}"
        if not isinstance(name, str) or not SERVER_NAME.fullmatch(name):
            problems.append(f"{where}: {name!r} is not a server name (lowercase letters, digits, _ and -); skipped")
            continue
        if not isinstance(raw, dict):
            problems.append(f"{at} must be an object such as {{\"command\": [\"npx\", ...]}}; skipped")
            continue
        unknown = [k for k in raw if k not in ("command", "env", "cwd", "trust_hints", "enabled")]
        entry = {"command": raw.get("command"), "env": raw.get("env", {}), "cwd": raw.get("cwd", ""), "trust_hints": raw.get("trust_hints", False), "enabled": raw.get("enabled", True)}
        bad = [
            text
            for text, ok in (
                (f"unknown field {unknown[0]!r}" if unknown else "", not unknown),
                ("command must be a non-empty list of non-empty strings", isinstance(entry["command"], list) and bool(entry["command"]) and all(isinstance(p, str) and p for p in entry["command"])),
                ("env must be an object of text values", isinstance(entry["env"], dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in entry["env"].items())),
                ("cwd must be text", isinstance(entry["cwd"], str)),
                ("trust_hints and enabled must be true or false", isinstance(entry["trust_hints"], bool) and isinstance(entry["enabled"], bool)),
            )
            if not ok
        ]
        if bad:
            problems.append(f"{at}: {'; '.join(bad)}; skipped")
            continue
        servers[name] = entry
    return servers, problems


class Server:
    """One MCP server process spoken to with newline-delimited JSON-RPC 2.0."""

    def __init__(self, name, entry, timeout):
        self.name, self.entry, self.timeout = name, entry, timeout
        self.proc = None
        self.pending = {}
        self.lock = threading.Lock()
        self.next_id = 0
        self.stderr = deque(maxlen=20)
        self.restarted = False
        self.failed = None
        self.starting = threading.Lock()

    @property
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, cwd):
        """Spawn the process and run the ``initialize`` handshake; ``RuntimeError``/``ValueError`` when it fails."""
        env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
        env.update(self.entry["env"])
        argv = list(self.entry["command"])
        exe = shutil.which(os.path.expanduser(argv[0]), path=env.get("PATH"))
        if exe is None:
            raise ValueError(
                f"mcp server {self.name}: {argv[0]!r} is not installed or not on PATH; install it or fix "
                f"extensions.settings.mcp.servers.{self.name}.command"
            )
        folder = os.path.join(cwd, os.path.expanduser(self.entry["cwd"])) if self.entry["cwd"] else cwd
        self.stderr.clear()
        if self.proc is not None:  # a dead process being replaced
            try:
                self.proc.stdin.close()
            except OSError:
                pass
        self.proc = subprocess.Popen(
            [exe, *argv[1:]],
            cwd=folder,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._read_err, args=(self.proc,), daemon=True).start()
        try:
            self.request(
                "initialize",
                {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "minimal", "version": __version__}},
                self.timeout,
            )
            self.notify("notifications/initialized")
        except Exception:
            self.stop()
            raise

    def _read(self, proc):
        try:
            self._read_lines(proc)
        finally:
            proc.stdout.close()

    def _read_lines(self, proc):
        for line in proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if "id" in message and ("result" in message or "error" in message):
                with self.lock:
                    waiter = self.pending.pop(message["id"], None)
                if waiter is not None:
                    waiter.put(message)
            elif "id" in message and "method" in message:  # a request from the server
                reply = {"jsonrpc": "2.0", "id": message["id"]}
                if message["method"] == "ping":
                    reply["result"] = {}
                else:
                    reply["error"] = {"code": -32601, "message": "method not supported by this client"}
                self._send(reply)
        with self.lock:  # the process ended: wake every waiter
            waiters, self.pending = list(self.pending.values()), {}
        for waiter in waiters:
            waiter.put({"error": {"message": "the server exited"}})

    def _read_err(self, proc):
        try:
            for line in proc.stderr:
                self.stderr.append(line.decode("utf-8", errors="replace").rstrip())
        finally:
            proc.stderr.close()

    def _send(self, message):
        try:
            self.proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            pass

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})

    def request(self, method, params, timeout, cancelled=lambda: False):
        """The ``result`` of a request; ``RuntimeError`` for an error reply, a timeout, an exit or an interrupt."""
        waiter = queue.Queue()
        with self.lock:
            self.next_id += 1
            ident = self.next_id
            self.pending[ident] = waiter
        self._send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            try:
                reply = waiter.get(timeout=0.2)
                break
            except queue.Empty:
                pass
            if cancelled():
                with self.lock:
                    self.pending.pop(ident, None)
                self.notify("notifications/cancelled", {"requestId": ident, "reason": "interrupted"})
                raise RuntimeError("interrupted")
            if time.monotonic() >= deadline:
                with self.lock:
                    self.pending.pop(ident, None)
                raise RuntimeError(f"mcp server {self.name}: {method} timed out after {timeout}s{self.tail()}")
        if "error" in reply:
            error = reply["error"]
            text = error.get("message", "error") if isinstance(error, dict) else str(error)
            raise RuntimeError(f"mcp server {self.name}: {text}{self.tail() if 'exited' in text else ''}")
        return reply.get("result") or {}

    def tail(self):
        lines = [l for l in self.stderr if l]
        return "; its last stderr lines:\n" + "\n".join(lines[-5:]) if lines else ""

    def list_tools(self, cancelled=lambda: False):
        tools, cursor = [], None
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else {}, self.timeout, cancelled)
            tools += [t for t in result.get("tools", []) if isinstance(t, dict) and isinstance(t.get("name"), str)]
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def stop(self):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is not None:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                return
            try:
                proc.wait(timeout=2)
                return
            except subprocess.TimeoutExpired:
                continue


def result_blocks(result, limit):
    """The model-facing output of a ``tools/call`` result: text (clipped), or text and image blocks."""
    texts, images = [], []
    for item in result.get("content") or []:
        kind = item.get("type") if isinstance(item, dict) else None
        if kind == "text":
            texts.append(item.get("text", ""))
        elif kind == "image":
            try:
                images.append(image_block(item.get("data", ""), item.get("mimeType", "")))
            except ValueError as e:
                texts.append(f"[image not shown: {e}]")
        elif kind == "resource":
            resource = item.get("resource") or {}
            texts.append(resource.get("text") or f"[resource {resource.get('uri', '')}: {resource.get('mimeType', 'binary')}]")
        elif kind == "resource_link":
            texts.append(f"[resource link {item.get('uri', '')}]")
    text = "\n".join(texts)
    if len(text) > limit:
        text = f"{text[:limit]}\n[clipped {len(text) - limit} chars; ask the server for less (a narrower query or a limit)]"
    if images:
        return [{"type": "text", "text": text or "(image)"}, *images]
    return text


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    servers, problems = parse_servers(settings["servers"])
    for problem in problems:
        minimal.report_problem(problem)
    live = {name: Server(name, entry, settings["timeout"]) for name, entry in servers.items() if entry["enabled"]}
    state = {"status": {}, "discovering": set()}
    stopping = threading.Event()

    def cache_file():
        return minimal.data_dir("global") / "mcp_cache.json"

    def read_cache():
        try:
            data = json.loads(cache_file().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def write_cache(name, entry, tools):
        with cache_lock:
            data = read_cache()
            data[name] = {"hash": config_hash(entry), "tools": tools}
            path = cache_file()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)

    cache_lock = threading.Lock()
    cache = read_cache()

    def cached_tools(name):
        entry = servers[name]
        hit = cache.get(name)
        if isinstance(hit, dict) and hit.get("hash") == config_hash(entry) and isinstance(hit.get("tools"), list):
            return hit["tools"]
        return None

    def ensure_started(server, ctx):
        with server.starting:
            if server.alive:
                return
            if server.proc is not None:  # it was running and died
                if server.restarted:
                    raise RuntimeError(
                        f"mcp server {server.name} exited again after a restart{server.tail()}; fix it, then /reload"
                    )
                server.restarted = True
            server.start(ctx.cwd)

    def call(server, remote, input, ctx):
        ensure_started(server, ctx)
        result = server.request(
            "tools/call", {"name": remote, "arguments": input or {}}, settings["call_timeout"], lambda: ctx.cancelled
        )
        out = result_blocks(result, settings["max_chars"])
        if result.get("isError"):
            raise RuntimeError(out if isinstance(out, str) else out[0]["text"])
        return out

    def make_run(server, remote):
        return lambda input, ctx: call(server, remote, input, ctx)

    for name, server in live.items():
        tools = cached_tools(name)
        state["status"][name] = "cached" if tools is not None else "not listed yet"
        for spec in tools or []:
            remote = spec["name"]
            schema = spec.get("inputSchema") if isinstance(spec.get("inputSchema"), dict) else {}
            schema = {"type": "object", "properties": {}, **schema}
            description = (spec.get("description") or spec.get("title") or remote).strip()
            description = f"[{name}] {description}"
            hinted = servers[name]["trust_hints"] and isinstance(spec.get("annotations"), dict) and spec["annotations"].get("readOnlyHint") is True
            if hinted:
                minimal.register_tool(tool_name(name, remote), make_run(server, remote), description, schema, confirm=False, read_only=True)
            else:
                minimal.register_tool(tool_name(name, remote), make_run(server, remote), description, schema, confirm=True)

    def discover(name, ctx_cwd, notify, *, announce=True):
        """List ``name``'s tools with a process of its own, cache them and say so; returns the count or ``None``."""
        entry = servers[name]
        probe = Server(name, entry, settings["timeout"])
        state["discovering"].add(probe)
        try:
            probe.start(ctx_cwd)
            tools = probe.list_tools(stopping.is_set)
            write_cache(name, entry, tools)
            cache[name] = {"hash": config_hash(entry), "tools": tools}
            state["status"][name] = "cached"
            if announce:
                notify(f"mcp: {name}: {len(tools)} tools found; run /reload to use them", "info")
            return len(tools)
        except Exception as e:
            state["status"][name] = f"failed: {e}"
            if announce:
                notify(f"mcp: {name}: {e}", "warning")
            return None
        finally:
            probe.stop()
            state["discovering"].discard(probe)

    @minimal.on("session_start")
    def start_discovery(payload):
        ctx = payload["ctx"]
        stale = [n for n in live if cached_tools(n) is None]
        if not stale:
            return

        def work():
            for name in stale:
                if stopping.is_set():
                    return
                discover(name, ctx.cwd, ctx.notify)

        threading.Thread(target=work, name="mcp-discovery", daemon=True).start()

    @minimal.on_dispose
    def stop_all():
        stopping.set()
        for server in [*live.values(), *state["discovering"]]:
            server.stop()

    minimal.on("shutdown", lambda payload: stop_all())

    def mcp(args, ctx):
        word, _, rest = args.strip().partition(" ")
        if word == "refresh":
            names = [rest.strip()] if rest.strip() else list(live)
            unknown = [n for n in names if n not in live]
            if unknown:
                return f"unknown server {unknown[0]!r}; configured: {', '.join(live) or 'none'}"
            lines = []
            for name in names:
                count = discover(name, ctx.cwd, ctx.notify, announce=False)
                lines.append(f"{name}: {count} tools found" if count is not None else f"{name}: {state['status'][name]}")
            return "\n".join(lines + ["Run /reload to use the new tool lists."])
        if word:
            return "usage: /mcp [refresh [server]]"
        if not servers:
            return "No MCP servers. Add some under extensions.settings.mcp.servers (/ext settings mcp)."
        rows = []
        for name, entry in servers.items():
            if not entry["enabled"]:
                rows.append(f"{name:<16} disabled")
                continue
            server = live[name]
            tools = cached_tools(name)
            status = "running" if server.alive else state["status"].get(name, "not listed yet")
            count = f"{len(tools)} tools" if tools is not None else "no tool list"
            rows.append(f"{name:<16} {status}  {count}  {' '.join(entry['command'])}")
        return "\n".join(rows)

    minimal.register_command("mcp", mcp, description="MCP servers: /mcp lists them, /mcp refresh [server] lists their tools again")
