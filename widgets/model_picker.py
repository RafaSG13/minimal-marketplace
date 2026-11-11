"""Model picker: /model opens a list of the models your provider really offers; pick one with the arrow keys.

Up/Down move, Enter selects, Esc cancels. The list is fetched live from the
current provider's API (``ctx.models()``, which falls back to the default model).
`/model <number|name>`, and `/model` without the terminal UI, run the built-in
command as before.
"""

from __future__ import annotations

import threading

from rich.text import Text
from textual.binding import Binding
from textual.widgets import OptionList
from textual.widgets.option_list import Option

__version__ = "2.0"
__api__ = "1"

NAME = "model_picker"


class ModelPicker(OptionList):
    DEFAULT_CSS = """
    ModelPicker {
        height: auto; max-height: 14; display: none;
        border: round $accent; border-title-color: $accent; padding: 0 1; background: $surface;
    }
    ModelPicker.-open { display: block; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, ctx) -> None:
        super().__init__(id="model-picker")
        self.ctx = ctx
        self._done: threading.Event | None = None
        self._choice: str | None = None

    # --- called from the command's worker thread ---------------------------

    def choose(self, models: list[str], current: str, title: str) -> str | None:
        """Show the picker and block until the user picks (returns the model) or cancels (None)."""
        done = threading.Event()
        self._done, self._choice = done, None
        self.app.call_from_thread(self._open, models, current, title)
        done.wait()
        self._done = None
        return self._choice

    # --- UI thread ----------------------------------------------------------

    def _open(self, models: list[str], current: str, title: str) -> None:
        self.clear_options()
        for name in models:
            row = Text("● " if name == current else "  ", style="bold")
            row.append(name, style="bold" if name == current else "")
            if name == current:
                row.append("  (current)", style="dim")
            self.add_option(Option(row, id=name))
        self.border_title = f"{title} · ↑↓ move · Enter select · Esc cancel"
        self.highlighted = models.index(current) if current in models else 0
        self.add_class("-open")
        self.focus()

    def _finish(self, choice: str | None) -> None:
        self.remove_class("-open")
        self._choice = choice
        if self._done is not None:
            self._done.set()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self._finish(event.option.id)

    def action_cancel(self) -> None:
        self._finish(None)

    def on_unmount(self) -> None:  # e.g. extensions reloaded while open: release the waiting command
        self._finish(None)


def _model(args: str, ctx) -> None:
    picker = None if args else ctx.widget(NAME)
    if picker is None:  # direct set, or no terminal UI: the built-in /model
        ctx.run_command(f"/model {args}".rstrip(), builtin=True)
        return
    choice = picker.choose(ctx.models(), ctx.model, f"Model · {ctx.provider_name}")
    if choice is None:
        print(f"Model unchanged: {ctx.model}")
    else:
        ctx.set_model(choice)
        print(f"Model: {ctx.model}")


def register(minimal) -> None:
    minimal.register_widget(NAME, ModelPicker, area="bottom")
    minimal.register_command("model", _model, "pick the model from a list, or set it: /model [number|name]")
