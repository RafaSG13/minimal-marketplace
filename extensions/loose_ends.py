"""Loose ends: a note tool and backlog for unverified, noticed and follow-up items.

The model records what it could not verify, noticed or left undone with the
note tool; /ends lets you review the backlog and close the finished items. Settings
(`/ext settings loose_ends`) set the panel, glyphs, the longest note, the
instructions the model sees and the review dialog's title.
"""

__version__ = "1.7"
__api__ = "2.3"
__tags__ = ["workflow"]

import json
from datetime import datetime, timezone
from pathlib import Path

from minimal.api import WIDGET_AREAS

STATE_FILE = None
KINDS = ("unverified", "noticed", "followup")
GLYPHS = {"unverified": "?", "noticed": "!", "followup": "→"}
TOOL_DESCRIPTION = (
    "Record a loose end in the user's backlog: something you could not verify (unverified), "
    "a problem you noticed but were not asked to fix (noticed), or work that remains (followup). "
    "One call per item; still mention it in your answer."
)
PROMPT_NOTE = (
    "Whenever you tell the user that you could not verify something, that you noticed an unrelated "
    "problem, or that work remains, also record it with the note tool."
)
DIALOG_TITLE = "Loose ends · tick the ones that are done"

DEFAULTS = {
    "enabled": True,
    "title": "LOOSE ENDS",
    "area": "sidebar",
    "order": 0,
    "rows": 8,
    "text_width": 32,
    "glyphs": GLYPHS,
    "max_text": 0,
    "tool_description": TOOL_DESCRIPTION,
    "prompt_note": PROMPT_NOTE,
    "dialog_title": DIALOG_TITLE,
}

SCHEMA = {
    "enabled": {"description": "Register the note tool, /ends and the panel; false registers nothing."},
    "title": {"description": "Heading line of the panel, followed by the open count."},
    "area": {"description": "Where the panel goes by default (/ui move changes it).", "enum": list(WIDGET_AREAS)},
    "order": {"description": "Position among the panels of the area (lower first)."},
    "rows": {"description": "Newest open loose ends the panel lists.", "min": 1, "max": 100},
    "text_width": {"description": "Columns of each panel row (glyph and text; longer is cut).", "min": 8, "max": 120},
    "glyphs": {
        "description": "Marker per kind: unverified, noticed, followup. Kinds you leave out keep their default."
    },
    "max_text": {
        "description": "Longest note text the tool accepts; a longer one is refused so the model shortens it (0: no limit).",
        "min": 0,
        "max": 10000,
    },
    "tool_description": {"description": "What the model reads about the note tool."},
    "prompt_note": {"description": "Paragraph added to the system prompt (empty: none)."},
    "dialog_title": {"description": "Title of the /ends review dialog."},
}


def merge_glyphs(user):
    """The default glyphs with the user's non-empty printable string overrides; ``ValueError`` for a bad key or value."""
    glyphs = dict(GLYPHS)
    for key, value in user.items():
        if key not in GLYPHS:
            raise ValueError(
                f"loose_ends: extensions.settings.loose_ends.glyphs has unknown kind {key!r} (known: {', '.join(KINDS)})"
            )
        if not isinstance(value, str) or not value or not value.isprintable():
            raise ValueError(
                f"loose_ends: extensions.settings.loose_ends.glyphs.{key} must be a short printable string"
            )
        glyphs[key] = value
    return glyphs


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _items():
    data = _load(STATE_FILE, {})
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def _note(input, ctx, max_text=0):
    kind, text, path = input.get("kind"), input.get("text"), input.get("path")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    if max_text and len(text.strip()) > max_text:
        raise ValueError(f"text is {len(text.strip())} characters; keep it under {max_text} and call note again")
    if path is not None and not isinstance(path, str):
        raise ValueError("path must be a string")
    items = _items()
    new_id = max((i["id"] for i in items), default=0) + 1
    items.append(
        {
            "id": new_id,
            "kind": kind,
            "text": text.strip(),
            "path": path or None,
            "session": ctx.session_id,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "done": False,
        }
    )
    _save(STATE_FILE, {"items": items})
    return f"Noted #{new_id}"


class LooseEndsWidget:
    """Panel listing the newest open loose ends."""

    def __init__(self, settings, glyphs):
        self.settings = settings
        self.glyphs = glyphs

    def render(self, ctx):
        open_items = [i for i in _items() if not i.get("done")]
        if not open_items:
            return None
        lines = [f"{self.settings['title']} ({len(open_items)})"]
        for item in sorted(open_items, key=lambda i: i["id"], reverse=True)[: self.settings["rows"]]:
            lines.append(f"{self.glyphs.get(item['kind'], '?')} {item['text']}"[: self.settings["text_width"]])
        return "\n".join(lines)


def register(minimal):
    global STATE_FILE
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    glyphs = merge_glyphs(settings["glyphs"])
    STATE_FILE = minimal.data_dir() / "state.json"
    minimal.register_tool(
        name="note",
        description=settings["tool_description"],
        input_schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(KINDS)},
                "text": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["kind", "text"],
        },
        run=lambda input, ctx: _note(input, ctx, settings["max_text"]),
        confirm=False,
    )

    if settings["prompt_note"]:
        minimal.append_system_prompt(settings["prompt_note"])

    minimal.register_panel(
        "loose_ends",
        LooseEndsWidget(settings, glyphs).render,
        area=settings["area"],
        order=settings["order"],
    )

    def ends(args, ctx):
        items = _items()
        open_items = [i for i in items if not i.get("done")]
        if not open_items:
            print("No loose ends.")
            return
        options = [
            (str(i["id"]), f"[{i['kind']}] {i['text']}" + (f" ({i['path']})" if i.get("path") else ""), False)
            for i in open_items
        ]
        ticked = ctx.ui.choose_many(settings["dialog_title"], options)
        if ticked is None:
            print("Cancelled.")
            return
        closed = 0
        for item in open_items:
            if str(item["id"]) in ticked:
                item["done"] = True
                closed += 1
        _save(STATE_FILE, {"items": items})
        print(f"Closed {closed} loose end(s).")

    minimal.register_command("ends", ends, description="review loose ends and close the finished ones")
