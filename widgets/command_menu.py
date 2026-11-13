"""Slash-command menu: type "/" in the prompt to get every command, narrowed as you type, driven with the arrow keys.

Up/Down move the selection, Enter runs the highlighted command, Tab completes it
into the prompt (so you can add arguments), Esc closes the menu. The highlighted
command is also shown as grey ghost text (Right arrow accepts it). Built-in and
extension commands alike, with their descriptions (``ctx.commands()``).
"""

from __future__ import annotations

from rich.text import Text
from textual.suggester import Suggester
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

__version__ = "2.1"
__api__ = "1"
__frontend__ = "textual"


class CommandSuggester(Suggester):
    """Ghost text: the first listed command that extends what was typed after "/"."""

    def __init__(self, inp: Input) -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self.inp = inp

    async def get_suggestion(self, value: str) -> str | None:
        menu = getattr(self.inp, "_command_menu", None)
        if menu is None or not value.startswith("/") or " " in value:
            return None
        query = value[1:].lower()
        for name in menu.ctx.commands():
            if name.lower().startswith(query) and len(name) > len(query):
                return f"/{name}"
        return None


class CommandMenu(OptionList):
    DEFAULT_CSS = """
    CommandMenu {
        height: auto; max-height: 10; display: none;
        border: round $accent; padding: 0 1; background: $surface;
    }
    CommandMenu.-open { display: block; }
    """
    can_focus = False

    def __init__(self, ctx) -> None:
        super().__init__(id="command-menu")
        self.ctx = ctx
        self.input: Input | None = None
        self.dismissed_for: str | None = None  # prompt text the user closed the menu on
        self.matches: list[str] = []

    # --- wiring ------------------------------------------------------------

    def on_mount(self) -> None:
        self.input = self.app.query_one("#prompt", Input)
        _install(self.input)
        self.input._command_menu = self
        self.watch(self.input, "value", self.update_menu)
        self.update_menu(self.input.value)

    def on_unmount(self) -> None:
        if self.input is not None and getattr(self.input, "_command_menu", None) is self:
            self.input._command_menu = None

    # --- state -------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self.has_class("-open")

    def update_menu(self, value: str) -> None:
        if not value.startswith("/") or " " in value or value == self.dismissed_for or (self.input and self.input.disabled):
            self.remove_class("-open")
            if value != self.dismissed_for:
                self.dismissed_for = None
            return
        query = value[1:].lower()
        commands = self.ctx.commands()
        names = [n for n in commands if n.lower().startswith(query)]
        names += [n for n in commands if query in n.lower() and n not in names]
        self.matches = names
        self.clear_options()
        if not names:
            self.remove_class("-open")
            return
        width = max(len(n) for n in names)
        for name in names:
            row = Text()
            row.append(f"/{name.ljust(width)}", style="bold")
            if commands[name]:
                row.append(f"  {commands[name]}", style="dim")
            self.add_option(Option(row, id=name))
        self.highlighted = 0
        self.add_class("-open")

    # --- actions (called from the prompt's key bindings) ------------------

    def move(self, step: int) -> None:
        if self.matches:
            self.highlighted = ((self.highlighted or 0) + step) % len(self.matches)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Make the ghost text follow the highlighted entry when it extends what was typed."""
        if self.input is None or not self.is_open:
            return
        full = f"/{event.option.id}"
        self.input._suggestion = full if full.lower().startswith(self.input.value.lower()) and full != self.input.value else ""

    def current(self) -> str | None:
        if self.highlighted is None or not self.matches:
            return None
        return self.matches[self.highlighted]

    def complete(self) -> None:
        name = self.current()
        if name and self.input:
            self.input.value = f"/{name} "
            self.input.cursor_position = len(self.input.value)

    def close(self) -> None:
        self.dismissed_for = self.input.value if self.input else None
        self.remove_class("-open")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if self.input:
            self.input.value = f"/{event.option.id}"
            self.input.focus()
            self.app.call_later(self.input.action_submit)


# --- prompt patching -----------------------------------------------------------
# Input has no up/down bindings and Enter submits, so the prompt gets extra key
# bindings and a wrapped submit that defer to the menu only while it is open.


def _active(inp: Input) -> CommandMenu | None:
    menu = getattr(inp, "_command_menu", None)
    return menu if menu is not None and menu.is_open else None


def _install(inp: Input) -> None:
    if getattr(inp, "_command_menu_installed", False):
        return
    inp._command_menu_installed = True
    inp._command_menu = None
    inp.suggester = CommandSuggester(inp)

    def action_menu_up() -> None:
        if m := _active(inp):
            m.move(-1)

    def action_menu_down() -> None:
        if m := _active(inp):
            m.move(1)

    def action_menu_complete() -> None:
        if m := _active(inp):
            m.complete()

    def action_menu_close() -> None:
        if m := _active(inp):
            m.close()

    async def action_submit() -> None:
        if (m := _active(inp)) and (name := m.current()):
            inp.value = f"/{name}"
        await Input.action_submit(inp)

    inp.action_menu_up = action_menu_up
    inp.action_menu_down = action_menu_down
    inp.action_menu_complete = action_menu_complete
    inp.action_menu_close = action_menu_close
    inp.action_submit = action_submit
    for key, action in (("up", "menu_up"), ("down", "menu_down"), ("tab", "menu_complete"), ("escape", "menu_close")):
        inp._bindings.bind(key, action, show=False)


def register(minimal) -> None:
    minimal.register_widget("command_menu", CommandMenu, area="bottom")
