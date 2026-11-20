"""Model picker: /model opens a list of the models your provider really offers; pick one with the arrow keys.

Up/Down move, Enter selects, Esc cancels; type to filter the list. The list is fetched live from the
current provider's API (``ctx.models()``, which falls back to the default model). Favourites are pinned on top,
models matching ``hide`` are left out. `/model <number|name>`, and `/model` without the terminal UI, run the
built-in command as before; Tab after `/model ` completes the names the picker last listed.
"""

from __future__ import annotations

import re
import threading

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.widgets import OptionList
from textual.widgets.option_list import Option

__version__ = "3.0"
__api__ = "2.3"
__tags__ = ["provider", "ui"]

NAME = "model_picker"

AREAS = ("bottom", "top", "footer")
"""Where the picker may sit (it is hidden until opened, so a column would be a poor home)."""

SORTS = ("provider", "alpha")
"""``provider`` keeps the order the provider lists; ``alpha`` sorts by name."""

COMPLETIONS = 50
"""Most names ``/model <Tab>`` offers."""


def clean(text: object) -> str:
    """``text`` as one printable line: control characters become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def compile_hide(patterns) -> list[re.Pattern[str]]:
    """The ``hide`` setting as compiled regexes.

    Raises:
        ValueError: naming the pattern that is not a string or not a valid regular expression.
    """
    found = []
    for pattern in patterns:
        if not isinstance(pattern, str):
            raise ValueError(f"model_picker: hide entries must be strings, not {pattern!r}")
        try:
            found.append(re.compile(pattern))
        except re.error as error:
            raise ValueError(f"model_picker: hide pattern {pattern!r} is not a valid regex: {error}") from None
    return found


def arrange(models: list[str], current: str, favourites: list[str], hide: list[re.Pattern[str]], sort: str) -> list[str]:
    """The names to list: ``hide``-matching ones dropped (never the current model or a favourite), favourites first
    (in the order of the ``favourites`` setting), the rest in provider order or sorted."""
    names = [clean(name) for name in dict.fromkeys(models)]
    if sort == "alpha":
        names.sort(key=str.lower)
    pinned = [name for name in favourites if name in names]
    rest = [
        name
        for name in names
        if name not in pinned and (name == current or not any(pattern.search(name) for pattern in hide))
    ]
    return [*pinned, *rest]


def narrow(names: list[str], needle: str) -> list[str]:
    """The ``names`` containing ``needle`` (case-insensitive)."""
    needle = needle.lower()
    return [name for name in names if needle in name.lower()] if needle else list(names)


class ModelPicker(OptionList):
    DEFAULT_CSS = """
    ModelPicker {
        height: auto; display: none;
        border: round $accent; border-title-color: $accent; padding: 0 1; background: $surface;
    }
    ModelPicker.-open { display: block; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, ctx, settings) -> None:
        super().__init__(id="model-picker")
        self.ctx = ctx
        self.settings = settings
        self.hide = compile_hide(settings["hide"])
        self.styles.max_height = settings["max_height"]
        self._done: threading.Event | None = None
        self._choice: str | None = None
        self._names: list[str] = []
        self._current = ""
        self._title = ""
        self._needle = ""

    # --- called from the command's worker thread ---------------------------

    def choose(self, models: list[str], current: str, title: str) -> str | None:
        """Show the picker and block until the user picks (returns the model) or cancels (None)."""
        done = threading.Event()
        self._done, self._choice = done, None
        names = arrange(models, current, list(self.settings["favourites"]), self.hide, self.settings["sort"])
        self.app.call_from_thread(self._open, names, current, title)
        done.wait()
        self._done = None
        return self._choice

    # --- UI thread ----------------------------------------------------------

    def _row(self, name: str) -> Text:
        settings = self.settings
        is_current = name == self._current
        row = Text("", style="bold")
        current, star = settings["current_marker"], settings["favourite_marker"]
        if current:
            row.append((current if is_current else " " * len(current)) + " ")
        if star and settings["favourites"]:
            row.append((star if name in settings["favourites"] else " " * len(star)) + " ")
        row.append(name, style="bold" if is_current else "")
        if is_current and settings["current_label"]:
            row.append("  " + settings["current_label"], style="dim")
        return row

    def _show(self) -> None:
        shown = narrow(self._names, self._needle)
        self.clear_options()
        if shown:
            for name in shown:
                self.add_option(Option(self._row(name), id=name))
            self.highlighted = shown.index(self._current) if self._current in shown else 0
        else:
            self.add_option(Option(Text("no model matches", style="dim"), disabled=True))
        hint = self.settings["hint"]
        if self.settings["filter"] and self._needle:
            hint = f"filter: {self._needle}  ·  Backspace erases  ·  Esc clears"
        self.border_title = f"{self._title} · {hint}" if hint else self._title

    def _open(self, names: list[str], current: str, title: str) -> None:
        self._names, self._current, self._needle = names, current, ""
        self._title = clean(title)
        self._show()
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

    def on_key(self, event: events.Key) -> None:
        if not self.settings["filter"] or not self.has_class("-open"):
            return
        if event.key == "backspace" and self._needle:
            self._needle = self._needle[:-1]
        elif event.is_printable and event.character is not None:
            self._needle += event.character
        else:
            return
        event.stop()
        event.prevent_default()
        self._show()

    def action_cancel(self) -> None:
        if self._needle:
            self._needle = ""
            self._show()
        else:
            self._finish(None)

    def on_unmount(self) -> None:  # e.g. extensions reloaded while open: release the waiting command
        self._finish(None)


def register(minimal) -> None:
    settings = minimal.declare_settings(
        {
            "enabled": True,
            "area": "bottom",
            "order": 0,
            "title": "Model · {provider}",
            "hint": "↑↓ move · Enter select · Esc cancel",
            "max_height": 14,
            "filter": True,
            "sort": "provider",
            "current_marker": "●",
            "current_label": "(current)",
            "favourite_marker": "★",
            "favourites": [],
            "hide": [],
        },
        {
            "enabled": {"description": "Replace /model with the picker. False leaves the built-in /model."},
            "area": {"description": "Where the picker opens (it is hidden until /model).", "enum": list(AREAS)},
            "order": {"description": "Position among the widgets of its area, lower first."},
            "title": {"description": "Border title; {provider} is the current provider's name. \"\" for none."},
            "hint": {"description": "Key hint appended to the border title; \"\" for none."},
            "max_height": {"description": "Rows of the list before it scrolls.", "min": 3, "max": 60},
            "filter": {"description": "Typing narrows the list to the names containing the text."},
            "sort": {"description": "Order of the models: as the provider lists them, or alphabetical.", "enum": list(SORTS)},
            "current_marker": {"description": "Marker before the current model; \"\" for none."},
            "current_label": {"description": "Text after the current model; \"\" for none."},
            "favourite_marker": {"description": "Marker before a favourite model; \"\" for none."},
            "favourites": {"description": "Model names pinned on top of the list, in this order, when the provider offers them."},
            "hide": {
                "description": "Regular expressions: models whose name matches are left out (the current one never is)."
            },
        },
    )
    if not settings["enabled"]:
        return
    hide = compile_hide(settings["hide"])  # fail at load, not when the picker opens
    favourites = [str(name) for name in settings["favourites"]]
    known: list[str] = []  # names the picker last listed, for /model <Tab>: complete() runs on the UI thread, no API

    def complete(args: str, ctx) -> list[str]:
        if args.isdigit():
            return []
        names = arrange([*favourites, *known, ctx.model or ""], ctx.model or "", favourites, hide, settings["sort"])
        return [name for name in narrow([n for n in names if n], args.strip())][:COMPLETIONS]

    def run(args: str, ctx) -> None:
        picker = None if args else ctx.widget(NAME)
        if picker is None:  # direct set, or no terminal UI: the built-in /model
            ctx.run_command(f"/model {args}".rstrip(), builtin=True)
            return
        models = ctx.models()
        known[:] = models
        title = settings["title"].replace("{provider}", clean(ctx.provider_name))
        choice = picker.choose(models, ctx.model, title)
        if choice is None:
            print(f"Model unchanged: {ctx.model}")
        else:
            ctx.set_model(choice)
            print(f"Model: {ctx.model}")

    minimal.register_widget(NAME, lambda ctx: ModelPicker(ctx, settings), area=settings["area"], order=settings["order"])
    minimal.register_command(
        "model", run, "pick the model from a list, or set it: /model [number|name]", complete=complete
    )
