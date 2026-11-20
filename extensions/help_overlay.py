"""Help overlay: /keys lists the live key bindings and every slash command, built-in and extension. Install it with `/ext`."""

from __future__ import annotations

__version__ = "2.0"
__api__ = "2.3"
__tags__ = ["ui"]

DEFAULT_EXTRA_KEYS = [
    ["Enter", "Send the message"],
    ["Shift+Enter", "Insert a newline (Ctrl+J or Alt+Enter too)"],
    ["Up / Down", "Walk the prompt history"],
    ["Tab or →", "Complete the slash command, argument or @file"],
    ["Ctrl+P", "Command palette"],
    ["Ctrl+Q", "Quit"],
    ["Click", "Expand or collapse a tool call's output"],
]
"""Keys the terminal UI handles that are not bindings ``ctx.keybindings()`` lists; the ``extra_keys`` setting replaces them."""


def clean(text: object) -> str:
    """``text`` as one printable line: control characters (escape sequences, newlines) become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(1, width - 1)].rstrip() + "…"


def pretty_key(key: str) -> str:
    """``"ctrl+b"`` as ``"Ctrl+B"``; ``"shift+tab"`` as ``"Shift+Tab"``."""
    return "+".join(part.capitalize() if len(part) > 1 else part.upper() for part in clean(key).split("+"))


def binding_rows(bindings) -> list[tuple[str, str]]:
    """``(key, text)`` rows for ``ctx.keybindings()``: the description, else the action; an extension's id is appended."""
    rows = []
    for binding in bindings:
        what = clean(binding.description) or clean(binding.action)
        if binding.source != "built-in":
            what = f"{what} [{clean(binding.source)}]"
        rows.append((pretty_key(binding.key), what))
    return rows


def format_help(
    commands: dict[str, str],
    keys=(),
    query: str = "",
    width: int = 80,
    titles: tuple[str, str] = ("Keys", "Commands"),
) -> str:
    """The listing: keys, then commands sorted by name, rows aligned. ``query`` keeps rows containing it
    (case-insensitive, in the key, name or description); empty sections are left out. ``width`` cuts descriptions."""
    needle = clean(query).lower()

    def keep(*fields: str) -> bool:
        return not needle or any(needle in field.lower() for field in fields)

    key_rows = [(clean(key), clean(what)) for key, what in keys]
    key_rows = [row for row in key_rows if keep(*row)]
    command_rows = sorted(
        (f"/{clean(name)}", _clip(clean(description), width)) for name, description in commands.items()
    )
    command_rows = [row for row in command_rows if keep(*row)]
    sections = []
    for title, rows in ((titles[0], key_rows), (titles[1], command_rows)):
        if rows:
            column = max(len(left) for left, _ in rows)
            sections.append("\n".join([clean(title)] + [f"  {left.ljust(column)}  {right}".rstrip() for left, right in rows]))
    if not sections:
        return f"Nothing matches {clean(query)!r}. Run the command without text to list everything."
    return "\n\n".join(sections)


def check_extra_keys(rows) -> list[tuple[str, str]]:
    """``rows`` as ``(key, text)`` pairs.

    Raises:
        ValueError: if an entry is not a two-string list.
    """
    pairs = []
    for row in rows:
        if not (isinstance(row, (list, tuple)) and len(row) == 2 and all(isinstance(item, str) for item in row)):
            raise ValueError(f"help_overlay: extra_keys entries must be [key, text] pairs, not {row!r}")
        pairs.append((row[0], row[1]))
    return pairs


def register(minimal):
    settings = minimal.declare_settings(
        {
            "enabled": True,
            "command": "keys",
            "alias": "shortcuts",
            "width": 80,
            "show_keys": True,
            "show_commands": True,
            "keys_title": "Keys",
            "commands_title": "Commands",
            "extra_keys": DEFAULT_EXTRA_KEYS,
            "hide_commands": [],
        },
        {
            "enabled": {"description": "Register the help command. False registers nothing."},
            "command": {"description": "Name of the help command, without the slash."},
            "alias": {"description": "Name of a second command that does the same; \"\" for none."},
            "width": {
                "description": "Columns of a command's description before it is cut with an ellipsis.",
                "min": 20,
                "max": 400,
            },
            "show_keys": {"description": "List the key bindings."},
            "show_commands": {"description": "List the slash commands."},
            "keys_title": {"description": "Heading of the key bindings section."},
            "commands_title": {"description": "Heading of the commands section."},
            "extra_keys": {
                "description": (
                    "Rows [key, text] added after the live bindings, for keys the UI handles that are not bindings. "
                    "Replaces the default list (Enter, Shift+Enter, history, Tab, Ctrl+P, Ctrl+Q, Click); [] for none."
                )
            },
            "hide_commands": {"description": "Names of commands (without the slash) the listing leaves out."},
        },
    )
    if not settings["enabled"]:
        return
    extra = check_extra_keys(settings["extra_keys"])
    hidden = {str(name).lstrip("/") for name in settings["hide_commands"]}
    titles = (settings["keys_title"], settings["commands_title"])
    name = settings["command"].strip().lstrip("/")
    if not name:
        raise ValueError("help_overlay: command must not be empty")

    def keys(args, ctx):
        rows = (binding_rows(ctx.keybindings()) + extra) if settings["show_keys"] else []
        commands = {} if not settings["show_commands"] else {k: v for k, v in ctx.commands().items() if k not in hidden}
        print(format_help(commands, rows, args or "", settings["width"], titles))

    minimal.register_command(name, keys, description=f"list the key bindings and slash commands; /{name} <text> filters them")
    alias = settings["alias"].strip().lstrip("/")
    if alias and alias != name:
        minimal.register_command(alias, keys, description=f"alias of /{name}")
