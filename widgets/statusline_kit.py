"""Status line kit: choose extra status-line segments (title, turns, tokens, usage, branch…), their order and side."""

from __future__ import annotations

from pathlib import Path

from minimal.api import styled_line, theme

__version__ = "2.0"
__api__ = "2.3"
__tags__ = ["ui"]

SEGMENTS = ("model", "cwd", "branch", "title", "session", "turns", "tokens", "usage")
"""Every segment a ``segments_left`` / ``segments_right`` entry may name; they are drawn in the order listed.
The cost estimate is not one of them: widgets/token_sparkline owns it (its ``cost`` status segment)."""

LABELS = {"session": "session", "tokens": "ctx", "turn": "turn", "turns": "turns"}
"""Words in segments (``turn`` and ``turns`` follow the number); ``labels`` overrides them."""

GLYPHS = {"branch": theme.BRANCH, "dirty": "*", "up": "↑", "down": "↓", "home": "~", "ellipsis": "…"}
"""Marks in segments; ``glyphs`` overrides them."""

STYLES = {
    "model": "accent",
    "cwd": "muted",
    "branch_clean": "success",
    "branch_dirty": "warning",
    "title": "foreground",
    "session": "dim",
    "turns": "muted",
    "tokens": "muted",
    "usage": "muted",
    "separator": "dim",
}
"""Style of each segment and of the separator; ``styles`` overrides them."""

DEFAULTS = {
    "enabled": True,
    "segments_left": ["title", "turns", "usage"],
    "segments_right": [],
    "separator": "·",
    "order": 0,
    "title_width": 32,
    "cwd_folders": 2,
    "tokens_percent": False,
    "labels": {},
    "glyphs": {},
    "styles": {},
}

SCHEMA = {
    "enabled": {"description": "Show the segments; false registers nothing."},
    "segments_left": {
        "description": "Segments on the left of the status line, in order: " + ", ".join(SEGMENTS) + "; empty for none."
    },
    "segments_right": {"description": "Segments on the right of the status line, same names; empty for none."},
    "separator": {"description": "Text between the segments of a side."},
    "order": {"description": "Position among the status line's other segments of the same side, lower first."},
    "title_width": {"description": "Columns of the session title.", "min": 4, "max": 200},
    "cwd_folders": {"description": "Folders of the working directory kept when it is deeper.", "min": 1, "max": 20},
    "tokens_percent": {"description": "Add the share of the model's context window to the tokens segment."},
    "labels": {"description": "Override a word: " + ", ".join(LABELS) + ", e.g. {\"tokens\": \"context\"}."},
    "glyphs": {"description": "Override a mark: " + ", ".join(GLYPHS) + ", e.g. {\"up\": \"in\", \"down\": \"out\"}."},
    "styles": {"description": "Override a style: " + ", ".join(STYLES) + ", e.g. {\"model\": \"bold $secondary\"}."},
}
"""Description, enum and range of each setting (``/ext settings widgets/statusline_kit``)."""


def clean(text: object) -> str:
    """``text`` as one printable line: control characters (escape sequences, newlines) become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def clip(text: str, width: int, ellipsis: str = "…") -> str:
    """``text`` cut to ``width`` columns with a trailing ``ellipsis``."""
    return text if len(text) <= width else text[: max(1, width - len(ellipsis))].rstrip() + ellipsis


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


def merged(name: str, given: dict, defaults: dict, problems: list[str], style: bool = False) -> dict:
    """``defaults`` with the entries of ``given`` laid over them; each bad entry is added to ``problems``."""
    result = dict(defaults)
    for key, value in given.items():
        if key not in defaults:
            problems.append(f"'{name}' has no entry {key!r} (known: {', '.join(defaults)})")
        elif not isinstance(value, str):
            problems.append(f"'{name}.{key}' must be text, not {value!r}")
        elif style:
            try:
                styled_line((" ", value))
            except ValueError as error:
                problems.append(f"'{name}.{key}': {error}")
            else:
                result[key] = value
        else:
            result[key] = value
    return result


def configure(settings) -> dict:
    """The settings as a plain dict with ``labels``, ``glyphs`` and ``styles`` laid over their defaults and
    ``left`` / ``right`` the selected segment names.

    Raises:
        ValueError: ``statusline_kit settings: …`` with one sentence per problem and its fix.
    """
    problems: list[str] = []
    config = dict(settings)
    config["labels"] = merged("labels", settings["labels"], LABELS, problems)
    config["glyphs"] = merged("glyphs", settings["glyphs"], GLYPHS, problems)
    config["styles"] = merged("styles", settings["styles"], STYLES, problems, style=True)
    for side in ("left", "right"):
        known, unknown = select(settings[f"segments_{side}"])
        if "cost" in unknown:
            unknown.remove("cost")
            problems.append(
                f"'segments_{side}' lists 'cost', which widgets/token_sparkline owns now: it has a 'cost' status "
                "segment with a price table (move it with /ui)"
            )
        if unknown:
            problems.append(
                f"unknown segment{'s' if len(unknown) > 1 else ''} {', '.join(repr(n) for n in unknown)} in "
                f"'segments_{side}' (known: {', '.join(SEGMENTS)})"
            )
        config[side] = known
    if not (config["left"] or config["right"]) and not any("segments_" in p for p in problems):
        problems.append(f"'segments_left' and 'segments_right' are both empty; list one of {', '.join(SEGMENTS)}")
    if problems:
        raise ValueError(f"statusline_kit settings: {'; '.join(problems)}")
    return config


def format_tokens(count: int) -> str:
    """``count`` tokens as ``950``, ``12.3k`` or ``1.2M``."""
    if count < 1000:
        return str(count)
    if count < 999_950:
        return f"{count / 1000:.1f}k"
    return f"{count / 1_000_000:.1f}M"


def short_path(path: str, home: str, folders: int = 2, home_glyph: str = "~", ellipsis: str = "…") -> str:
    """``path`` with ``home`` written as ``~``, keeping the last ``folders`` folders when it is deeper."""
    under = home and (path == home or path.startswith(home.rstrip("/") + "/"))
    shown = home_glyph + path[len(home) :] if under else path
    parts = shown.split("/")
    return shown if len(parts) <= folders + 1 else ellipsis + "/" + "/".join(parts[-folders:])


def _text(message: dict) -> str:
    """The text a message carries: a string content, or its ``text`` blocks (tool results carry none)."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


class Digest:
    """What the segments need from the messages, kept up to date by reading only those added since the last look.

    ``title`` is the first line of the first user message with text, ``turns`` counts the user's typed messages (not
    those holding only tool results) and ``input`` / ``output`` sum the replies' usage. A shorter list, or one whose
    last-seen message is not the same object any more (``/new``, a rewind), is read again from the start.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.count = 0
        self.last: object = None
        self.title = ""
        self.turns = 0
        self.input = 0
        self.output = 0

    def update(self, messages: list) -> "Digest":
        if self.count > len(messages) or (self.count and messages[self.count - 1] is not self.last):
            self.reset()
        for message in messages[self.count :]:
            if not isinstance(message, dict):
                continue
            if message.get("role") == "user":
                text = _text(message).strip()
                if text:
                    self.turns += 1
                    self.title = self.title or clean(text.splitlines()[0])
            elif message.get("role") == "assistant" and isinstance(message.get("usage"), dict):
                self.input += int(message["usage"].get("input_tokens") or 0)
                self.output += int(message["usage"].get("output_tokens") or 0)
        self.count = len(messages)
        self.last = messages[-1] if messages else None
        return self


def segment(name: str, facts: dict, config: dict) -> list | None:
    """Pieces of the segment ``name`` for ``facts`` (see :func:`facts_of`), or None when it has nothing to show."""
    labels, glyphs, styles = config["labels"], config["glyphs"], config["styles"]
    digest = facts["digest"]
    if name == "model":
        return [(clean(facts["model"]), styles["model"])] if facts["model"] else None
    if name == "cwd":
        if not facts["cwd"]:
            return None
        shown = short_path(facts["cwd"], facts["home"], config["cwd_folders"], glyphs["home"], glyphs["ellipsis"])
        return [(clean(shown), styles["cwd"])]
    if name == "branch":
        git = facts["git"]
        if git is None:
            return None
        text = f"{glyphs['branch']} {clean(git.branch) if git.branch else 'detached'}"
        text += f" {glyphs['dirty']}" if git.dirty and glyphs["dirty"] else ""
        return [(text, styles["branch_dirty" if git.dirty else "branch_clean"])]
    if name == "title":
        title = clip(digest.title, config["title_width"], glyphs["ellipsis"])
        return [(title, styles["title"])] if digest.title else None
    if name == "session":
        return [(f"{labels['session']} {facts['session']}".strip(), styles["session"])] if facts["session"] else None
    if name == "turns":
        turns = digest.turns
        word = labels["turn"] if turns == 1 else labels["turns"]
        return [(f"{turns} {word}".rstrip(), styles["turns"])] if turns else None
    if name == "tokens":
        tokens = facts["context_tokens"]
        if tokens is None:
            return None
        text = f"{labels['tokens']} {format_tokens(tokens)}".strip()
        if config["tokens_percent"] and facts["context_window"]:
            text += f" {min(tokens / facts['context_window'], 1):.0%}"
        return [(text, styles["tokens"])]
    if name == "usage":
        if not (digest.input or digest.output):
            return None
        up, down = glyphs["up"], glyphs["down"]
        return [(f"{up}{format_tokens(digest.input)} {down}{format_tokens(digest.output)}", styles["usage"])]
    raise ValueError(f"unknown segment {name!r}")


def build_line(names: list[str], facts: dict, config: dict) -> list | None:
    """Pieces of one side's segment for ``names`` (already :func:`select`-ed), joined by the separator; None if none."""
    pieces: list = []
    for name in names:
        part = segment(name, facts, config)
        if part:
            if pieces:
                pieces.append((f" {config['separator']} ", config["styles"]["separator"]))
            pieces.extend(part)
    return pieces or None


def facts_of(ctx, digest: Digest, names: list[str]) -> dict:
    """What the segments ``names`` are drawn from, taken from ``ctx`` (its messages read into ``digest``)."""
    return {
        "model": ctx.model,
        "cwd": ctx.cwd,
        "home": str(Path.home()),
        "git": ctx.git() if "branch" in names else None,
        "session": ctx.session_id,
        "context_tokens": ctx.context_tokens,
        "context_window": ctx.context_window,
        "digest": digest.update(ctx.messages),
    }


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    config = configure(settings)
    digest = Digest()
    for side, name in (("left", "statusline_kit"), ("right", "statusline_kit_right")):
        if config[side]:
            minimal.register_status(
                name,
                lambda ctx, names=config[side]: build_line(names, facts_of(ctx, digest, names), config),
                side=side,
                order=config["order"],
            )
