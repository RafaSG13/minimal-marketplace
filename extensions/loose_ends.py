"""Loose ends: a note tool and backlog for unverified, noticed and follow-up items.

The model records what it could not verify, noticed or left undone with the
note tool; /ends lets you review the backlog and close the finished items.
"""

__version__ = "1.3"
__api__ = "1.1"

import json
from datetime import datetime, timezone
from pathlib import Path

from textual.widgets import Static

STATE_FILE = None
KINDS = ("unverified", "noticed", "followup")
GLYPHS = {"unverified": "?", "noticed": "!", "followup": "→"}


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


def _note(input, ctx):
    kind, text, path = input.get("kind"), input.get("text"), input.get("path")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
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


class LooseEndsWidget(Static):
    """Sidebar panel listing the newest open loose ends."""

    DEFAULT_CSS = "LooseEndsWidget { padding: 0 1; }"

    def refresh_state(self, ctx):
        open_items = [i for i in _items() if not i.get("done")]
        if not open_items:
            self.display = False
            return
        lines = [f"LOOSE ENDS ({len(open_items)})"]
        for item in sorted(open_items, key=lambda i: i["id"], reverse=True)[:8]:
            lines.append(f"{GLYPHS.get(item['kind'], '?')} {item['text']}"[:32])
        self.update("\n".join(lines))
        self.display = True


def register(minimal):
    global STATE_FILE
    STATE_FILE = minimal.data_dir() / "state.json"
    minimal.register_tool(
        name="note",
        description=(
            "Record a loose end in the user's backlog: something you could not verify (unverified), "
            "a problem you noticed but were not asked to fix (noticed), or work that remains (followup). "
            "One call per item; still mention it in your answer."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(KINDS)},
                "text": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["kind", "text"],
        },
        run=_note,
        confirm=False,
    )

    minimal.append_system_prompt(
        "Whenever you tell the user that you could not verify something, that you noticed an unrelated "
        "problem, or that work remains, also record it with the note tool."
    )

    minimal.register_widget("loose_ends", lambda ctx: LooseEndsWidget(markup=False), area="sidebar")

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
        ticked = ctx.ui.choose_many("Loose ends · tick the ones that are done", options)
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
