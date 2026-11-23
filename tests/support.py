"""Shared helpers of the marketplace's tests: loading one item, an ``App`` around it, fake binaries, temp repos.

Run the suite from the repository root: ``python -m unittest discover -s tests`` (with ``minimal`` importable, e.g.
``uv run --no-project --with-editable ../minimal python -m unittest discover -s tests``). Tests import this module as
``from support import ...``.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from minimal import config
from minimal.core.app import App
from minimal.core import session as session_mod
from minimal.extensions import loader
from minimal.extensions.loader import load_extensions
from minimal.extensions.registry import Registry
from minimal.providers.base import Reply

ROOT = Path(__file__).resolve().parents[1]
"""The marketplace checkout."""


class RecordingProvider:
    """Replays ``replies`` in order, recording each request's messages, tool names, system prompt and full tool specs."""

    name = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def stream(self, **kw):
        # Copy the messages: the agent loop appends to the same list after the request.
        self.requests.append(
            SimpleNamespace(
                messages=list(kw["messages"]),
                tools=[t["name"] for t in kw["tools"]],
                specs=list(kw["tools"]),
                system=kw.get("system", ""),
            )
        )
        return self.replies.pop(0)


def text_reply(text, **kw):
    """A final assistant reply with ``text``."""
    return Reply(content=[{"type": "text", "text": text}], stop_reason="end_turn", **kw)


def tool_reply(name, input, id="t1"):
    """An assistant reply that calls ``name`` with ``input``."""
    return Reply(content=[{"type": "tool_use", "id": id, "name": name, "input": input}], stop_reason="tool_use")


class FakeUI:
    """What ``ctx.ui`` offers a test: ``ask`` answers from ``answers`` (default yes) and records the questions."""

    def __init__(self):
        self.answers = []
        self.asked = []
        self.draft = ""

    def ask(self, question, **kw):
        self.asked.append(question)
        return self.answers.pop(0) if self.answers else True

    def get_draft(self):
        return self.draft

    def set_draft(self, text, *, append=False):
        self.draft = self.draft + text if append else text


def item_id(item: str) -> str:
    """The id minimal gives ``item`` (``extensions/x.py`` -> ``x``; ``tools/x.py`` -> ``tools/x``)."""
    parts = Path(item).with_suffix("").parts
    return parts[-1] if parts[0] == "extensions" else "/".join(parts)


class ItemTest(unittest.TestCase):
    """Loads marketplace items with no global or project extensions around; settings go in a temp settings.json."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        for patcher in (
            mock.patch.object(loader, "GLOBAL_EXTENSIONS_DIR", self.tmp / "global"),
            mock.patch.object(config, "SETTINGS_FILE", self.tmp / "settings.json"),
            mock.patch.object(config, "HOME_DIR", self.tmp / "home"),
            mock.patch.object(config, "KEYS_FILE", self.tmp / "home" / "keys.json"),
            mock.patch.object(config, "TRUST_FILE", self.tmp / "home" / "trusted.json"),
            mock.patch.object(session_mod, "SESSIONS_DIR", self.tmp / "home" / "sessions"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        # no signing, hooks, fsmonitor daemons or housekeeping from the developer's own git configuration
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull})
        env.start()
        self.addCleanup(env.stop)
        self._settings: dict[str, dict] = {}
        self._bin: Path | None = None

    # --- loading ----------------------------------------------------------------

    def write_settings(self, **by_item):
        """Set the settings of items (``{"tools/git.py": {...}}`` through ``**{...}`` or ``item=...`` by item id)."""
        self._settings.update(by_item)
        (self.tmp / "settings.json").write_text(json.dumps({"extensions": {"settings": self._settings}}))

    def load(self, item: str, **settings):
        """Load ``item`` (a path relative to the checkout) with ``settings``; returns ``(registry, errors)``."""
        if settings:
            self.write_settings(**{item_id(item): settings})
        registry = Registry()
        layers, _ = config.read_layers(str(self.tmp))
        _, errors = load_extensions(
            registry,
            str(self.tmp),
            config.Settings(layers=tuple(layers), trusted=True),
            extra=[ROOT / item],
        )
        return registry, errors

    def make_app(self, item, replies, *, extra=(), settings=None, session_id="s"):
        """An ``App`` with ``item`` (and the ``extra`` paths) loaded whose provider replays ``replies``."""
        if settings:
            self.write_settings(**{item_id(item): settings})
        sources = [str(ROOT / item) if not os.path.isabs(item) else item, *map(str, extra)]
        app = App(
            registry=Registry(),
            session=session_mod.open_session(session_id),
            cwd=str(self.tmp),
            auto_approve=True,
            trust_project=True,
            extra_extensions=sources,
        )
        _, errors = app.reload_extensions()
        self.assertEqual(errors, [])
        app.provider, app.model = RecordingProvider(replies), "m"
        return app

    def run_turn(self, app, text):
        """Run one turn with the console output captured; returns it (stdout and stderr together)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            app.run_turn(text)
        return out.getvalue()

    def ctx(self, cwd=None, **extra):
        """A stand-in for the ``ctx`` a tool receives."""
        base = dict(
            cwd=str(cwd or self.tmp),
            cancelled=False,
            progress=lambda *a, **k: None,
            git_refresh=lambda: None,
            check_cancelled=lambda: None,
            agent_id="main",
            parent_id=None,
            ui=FakeUI(),
            project_trusted=True,
            notify=lambda *a, **k: None,
            show=lambda *a, **k: None,
            git=lambda: None,
            invalidate=lambda: None,
            queue_user_message=lambda text: None,
        )
        base.update(extra)
        return SimpleNamespace(**base)

    # --- the machine around the item ---------------------------------------------

    def fake_bin(self, name: str, script_text: str) -> Path:
        """Write the executable ``name`` (a ``#!`` script; ``script_text`` is the whole file) into a temp folder put
        first on ``PATH`` for this test."""
        if self._bin is None:
            self._bin = self.tmp / "bin"
            self._bin.mkdir()
            patcher = mock.patch.dict(os.environ, {"PATH": f"{self._bin}{os.pathsep}{os.environ.get('PATH', '')}"})
            patcher.start()
            self.addCleanup(patcher.stop)
        path = self._bin / name
        path.write_text(script_text)
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return path

    def git_repo(self, files: dict[str, str], name: str = "repo") -> Path:
        """A new git repository under the temp folder with ``files`` committed on ``main``."""
        repo = self.tmp / name
        repo.mkdir()
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

        def git(*args):
            subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)

        git("init", "-b", "main")
        git("config", "user.name", "Test")
        git("config", "user.email", "test@example.com")
        git("config", "commit.gpgsign", "false")
        git("config", "gc.auto", "0")  # no detached housekeeping writing into .git while the folder is removed
        git("config", "maintenance.auto", "false")
        for rel, text in files.items():
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        git("add", "-A")
        git("commit", "-m", "initial")
        return repo


def have(binary: str) -> bool:
    """Whether ``binary`` is on ``PATH`` (for ``skipUnless``)."""
    return shutil.which(binary) is not None
