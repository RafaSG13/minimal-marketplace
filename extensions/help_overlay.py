"""Help overlay: /keys lists the key bindings and every slash command, built-in and extension. Install it with `/ext`."""

__version__ = "1.1"
__api__ = "2"
__tags__ = ["ui"]

KEYS = (
    ("Enter", "Send the message"),
    ("Esc", "Interrupt the turn in progress"),
    ("Ctrl+P", "Command palette"),
    ("Ctrl+B", "Hide or show the sidebar"),
    ("Ctrl+Q", "Quit"),
    ("→", "Accept the suggested slash command"),
    ("Click", "Expand or collapse a tool call's output"),
)
"""The terminal UI's built-in keys (README, "Commands"): the API does not expose the live bindings."""

DESCRIPTION_WIDTH = 80
"""Columns of a command's description before it is cut with ``…``."""


def clean(text: object) -> str:
    """``text`` as one printable line: control characters (escape sequences, newlines) become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def format_help(commands: dict[str, str], keys=KEYS, query: str = "") -> str:
    """The listing: keys, then commands sorted by name, rows aligned. ``query`` keeps rows containing it
    (case-insensitive, in the key, name or description); empty sections are left out."""
    needle = clean(query).lower()

    def keep(*fields: str) -> bool:
        return not needle or any(needle in field.lower() for field in fields)

    key_rows = [(clean(key), clean(what)) for key, what in keys]
    key_rows = [row for row in key_rows if keep(*row)]
    command_rows = sorted(
        (f"/{clean(name)}", _clip(clean(description), DESCRIPTION_WIDTH)) for name, description in commands.items()
    )
    command_rows = [row for row in command_rows if keep(*row)]
    sections = []
    for title, rows in (("Keys", key_rows), ("Commands", command_rows)):
        if rows:
            width = max(len(left) for left, _ in rows)
            sections.append("\n".join([title] + [f"  {left.ljust(width)}  {right}".rstrip() for left, right in rows]))
    if not sections:
        return f"Nothing matches {clean(query)!r}. Run /keys alone to list everything."
    return "\n\n".join(sections)


def register(minimal):
    def keys(args, ctx):
        print(format_help(ctx.commands(), query=args or ""))

    for name, description in (
        ("keys", "list the key bindings and slash commands; /keys <text> filters them"),
        ("shortcuts", "alias of /keys"),
    ):
        minimal.register_command(name, keys, description=description)
