"""Status line kit: choose extra status-line segments (title, turns, tokens, usage, cost, branch…) and their order."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from minimal.api import STATUS_SIDES, theme

__version__ = "1.1"
__api__ = "2"
__tags__ = ["ui"]

SEGMENTS = ("model", "cwd", "branch", "title", "session", "turns", "tokens", "usage", "cost")
"""Every segment a ``segments`` entry may name; they are drawn in the order listed."""

DEFAULTS = {
    "segments": ["title", "turns", "usage"],
    "side": "left",
    "separator": "·",
    "title_width": 32,
    "price_in": 0.0,
    "price_out": 0.0,
}
"""``segments``: which to show, in order (``SEGMENTS``); ``side``: ``left`` or ``right`` of the status line;
``separator``: between segments; ``title_width``: columns of the title; ``price_in`` / ``price_out``: USD per
million input / output tokens, needed by the ``cost`` segment."""

GIT = ["git", "-c", "core.fsmonitor=false", "--no-optional-locks"]
"""git without fsmonitor (a repository's config must not run commands) and without taking locks."""

REFRESH = 5.0
"""Seconds between reads of the repository's branch."""


def clean(text: object) -> str:
    """``text`` as one printable line: control characters (escape sequences, newlines) become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def clip(text: str, width: int) -> str:
    """``text`` cut to ``width`` columns with a trailing ``…``."""
    return text if len(text) <= width else text[: max(1, width - 1)].rstrip() + "…"


def select(names: list) -> tuple[list[str], list[str]]:
    """``(known, unknown)`` from the configured ``names``: known ones deduplicated in the order given."""
    known: list[str] = []
    unknown: list[str] = []
    for name in names:
        label = str(name)
        if label in SEGMENTS:
            if label not in known:
                known.append(label)
        elif label not in unknown:
            unknown.append(label)
    return known, unknown


def check_settings(settings: dict) -> list[str]:
    """What is wrong with ``settings``, one sentence per problem with the fix; empty if usable."""
    problems = []
    known, unknown = select(settings["segments"])
    if unknown:
        problems.append(
            f"unknown segment{'s' if len(unknown) > 1 else ''} {', '.join(repr(n) for n in unknown)} in 'segments' "
            f"(known: {', '.join(SEGMENTS)})"
        )
    elif not known:
        problems.append(f"'segments' is empty; list at least one of {', '.join(SEGMENTS)}")
    if settings["side"] not in STATUS_SIDES:
        problems.append(f"'side' must be one of {', '.join(STATUS_SIDES)}, not {settings['side']!r}")
    if "cost" in known and not (settings["price_in"] > 0 or settings["price_out"] > 0):
        problems.append("the 'cost' segment needs 'price_in' and/or 'price_out' (USD per million tokens)")
    if settings["title_width"] < 4:
        problems.append("'title_width' must be at least 4")
    return problems


def format_tokens(count: int) -> str:
    """``count`` tokens as ``950``, ``12.3k`` or ``1.2M``."""
    if count < 1000:
        return str(count)
    if count < 999_950:
        return f"{count / 1000:.1f}k"
    return f"{count / 1_000_000:.1f}M"


def short_path(path: str, home: str) -> str:
    """``path`` with ``home`` written as ``~``, keeping the last two folders when it is deeper."""
    shown = "~" + path[len(home) :] if home and (path == home or path.startswith(home.rstrip("/") + "/")) else path
    parts = shown.split("/")
    return shown if len(parts) <= 3 else "…/" + "/".join(parts[-2:])


def _text(message: dict) -> str:
    """The text a message carries: a string content, or its ``text`` blocks (tool results carry none)."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def session_title(messages: list) -> str:
    """First line of the session's first message from the user, or ``""`` (the session header's title is not on ``ctx``)."""
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "user":
            text = _text(message).strip()
            if text:
                return clean(text.splitlines()[0])
    return ""


def turn_count(messages: list) -> int:
    """Messages the user typed: user messages with text, not those holding only tool results."""
    return sum(1 for m in messages if isinstance(m, dict) and m.get("role") == "user" and _text(m).strip())


def usage_totals(messages: list) -> tuple[int, int]:
    """``(input, output)`` tokens summed over the replies that reported usage."""
    total_in = total_out = 0
    for message in messages:
        usage = message.get("usage") if isinstance(message, dict) else None
        if isinstance(usage, dict):
            total_in += int(usage.get("input_tokens") or 0)
            total_out += int(usage.get("output_tokens") or 0)
    return total_in, total_out


def parse_branch(status: str) -> tuple[str, bool] | None:
    """``(branch, dirty)`` from ``git status --porcelain=v1 --branch`` output, or None if it is not a repository's."""
    lines = status.splitlines()
    if not lines or not lines[0].startswith("## "):
        return None
    head = lines[0][3:].removeprefix("No commits yet on ").split(" [", 1)[0].split("...", 1)[0]
    return ("detached" if head.startswith("HEAD (no branch)") else head), len(lines) > 1


def read_branch(cwd: str | None) -> tuple[str, bool] | None:
    """``(branch, dirty)`` of the repository containing ``cwd``; None outside one or without git."""
    try:
        result = subprocess.run(
            [*GIT, "status", "--porcelain=v1", "--branch"], cwd=cwd, capture_output=True, text=True, timeout=2
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_branch(result.stdout) if result.returncode == 0 else None


def segment(name: str, facts: dict, settings: dict) -> list | None:
    """Pieces of the segment ``name`` for ``facts`` (see :func:`facts_of`), or None when it has nothing to show."""
    messages = facts["messages"]
    if name == "model":
        return [(facts["model"], "accent")] if facts["model"] else None
    if name == "cwd":
        return [(short_path(facts["cwd"], facts["home"]), "muted")] if facts["cwd"] else None
    if name == "branch":
        if facts["branch"] is None:
            return None
        branch, dirty = facts["branch"]
        return [(f"{theme.BRANCH} {clean(branch)}{' *' if dirty else ''}", "warning" if dirty else "success")]
    if name == "title":
        title = session_title(messages)
        return [(clip(title, settings["title_width"]), "foreground")] if title else None
    if name == "session":
        return [(f"session {facts['session']}", "dim")] if facts["session"] else None
    if name == "turns":
        turns = turn_count(messages)
        return [(f"{turns} turn{'' if turns == 1 else 's'}", "muted")] if turns else None
    if name == "tokens":
        tokens = facts["context_tokens"]
        return [(f"ctx {format_tokens(tokens)}", "muted")] if tokens is not None else None
    total_in, total_out = usage_totals(messages)
    if not (total_in or total_out):
        return None
    if name == "usage":
        return [(f"↑{format_tokens(total_in)} ↓{format_tokens(total_out)}", "muted")]
    if name == "cost":
        cost = (total_in * settings["price_in"] + total_out * settings["price_out"]) / 1_000_000
        return [(f"~${cost:.2f}" if cost >= 0.01 else f"~${cost:.4f}", "muted")]
    raise ValueError(f"unknown segment {name!r}")


def build_line(names: list[str], facts: dict, settings: dict) -> list | None:
    """Pieces of the whole segment for ``names`` (already :func:`select`-ed), joined by the separator; None if empty."""
    pieces: list = []
    for name in names:
        part = segment(name, facts, settings)
        if part:
            if pieces:
                pieces.append((f" {settings['separator']} ", "dim"))
            pieces.extend(part)
    return pieces or None


class Branch:
    """The repository's ``(branch, dirty)``, read on a thread at most every ``REFRESH`` seconds."""

    def __init__(self) -> None:
        self.value: tuple[str, bool] | None = None
        self.fetched = 0.0
        self.fetching = False
        self.stopped = False

    def get(self, cwd: str | None) -> tuple[str, bool] | None:
        if not self.stopped and not self.fetching and time.monotonic() - self.fetched >= REFRESH:
            self.fetching = True
            threading.Thread(target=self._fetch, args=(cwd,), daemon=True).start()
        return self.value

    def _fetch(self, cwd: str | None) -> None:
        """Runs on a thread: read the repository, then publish the result for the next redraw."""
        try:
            self.value = read_branch(cwd)
        finally:
            self.fetched = time.monotonic()
            self.fetching = False


def facts_of(ctx, branch: tuple[str, bool] | None) -> dict:
    """What the segments are drawn from, taken from ``ctx``."""
    return {
        "model": ctx.model,
        "cwd": ctx.cwd,
        "home": str(Path.home()),
        "branch": branch,
        "session": ctx.session_id,
        "context_tokens": ctx.context_tokens,
        "messages": ctx.messages,
    }


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS)
    if problems := check_settings(settings):
        raise ValueError(f"statusline_kit settings: {'; '.join(problems)}")
    names, _ = select(settings["segments"])
    branch = Branch()
    minimal.on_dispose(lambda: setattr(branch, "stopped", True))

    def render(ctx):
        return build_line(names, facts_of(ctx, branch.get(ctx.cwd) if "branch" in names else None), settings)

    minimal.register_status("statusline_kit", render, side=settings["side"])
