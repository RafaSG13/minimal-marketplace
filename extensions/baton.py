"""Baton: hand a task off as one file with summary, base commit and patch."""

import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from minimal.agent import tool_specs
from minimal.app import build_system_prompt
from minimal.session import new_id, open_session

__version__ = "1.0"

USAGE = "usage: /baton pass [note] | /baton take <path>"
BATON_DIR = ".minimal/batons"
MAX_UNTRACKED = 1_000_000
BEGIN = b"<!-- baton:patch:begin -->"
END = b"<!-- baton:patch:end -->"
GIT_SCOPE = ("--", ".", ":(exclude).minimal")
HANDOFF_REQUEST = (
    "Stop here and do not call any tools. Write a handoff note for another engineer who will continue this task "
    "with a different agent and none of this conversation: the goal and the user's instructions, decisions made "
    "and why, files changed (with paths), commands run and their relevant results, the current state, and what "
    "remains to be done, in order. Be specific and complete; plain text."
)


def _git(cwd, *args):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _git_bytes(cwd, *args, ok=(0,)):
    """Raw stdout of a git command (patches must not go through text decoding), or ``None`` on failure."""
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode in ok else None


def _text(blocks):
    return "".join(block["text"] for block in blocks if block["type"] == "text")


def _patch(cwd):
    """Return ``(patch bytes, paths skipped for size)``: tracked changes plus untracked files up to 1 MB."""
    patch = _git_bytes(cwd, "diff", "--binary", "HEAD", *GIT_SCOPE) or b""
    skipped = []
    listing = _git(cwd, "ls-files", "--others", "--exclude-standard", "-z", *GIT_SCOPE) or ""
    for path in filter(None, listing.split("\0")):
        try:
            size = os.lstat(Path(cwd, path)).st_size
        except OSError:
            continue
        if size > MAX_UNTRACKED:
            skipped.append(path)
            continue
        # exit status 1 only means "the files differ", which is the normal result against /dev/null
        patch += _git_bytes(cwd, "diff", "--binary", "--no-index", "--", "/dev/null", path, ok=(0, 1)) or b""
    return patch, skipped


def _count_files(patch):
    return sum(1 for line in patch.split(b"\n") if line.startswith(b"diff --git "))


def _pass(note, ctx):
    cwd = ctx.cwd
    base = (_git(cwd, "rev-parse", "HEAD") or "").strip()
    if not base:
        raise ValueError("not a git repository with a commit")
    if not ctx.messages or ctx.messages[-1]["role"] != "assistant":
        raise ValueError("nothing to hand off")

    reply = ctx.provider.stream(
        model=ctx.model,
        system=build_system_prompt(ctx.registry, ctx.cwd),
        messages=[*ctx.messages, {"role": "user", "content": HANDOFF_REQUEST}],
        tools=tool_specs(ctx.registry),
        on_text=None,
    )
    summary = _text(reply.content).strip()
    if not summary or any(block["type"] == "tool_use" for block in reply.content):
        raise ValueError("the model did not return a summary")

    patch, skipped = _patch(cwd)
    if patch and not patch.endswith(b"\n"):
        patch += b"\n"
    branch = (_git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    created = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    head = (
        f"# Baton {ctx.session.id}\n\n"
        f"- from: {ctx.provider_name} · {ctx.model}\n"
        f"- base: {base}\n"
        f"- branch: {branch}\n"
        f"- created: {created}\n"
        f"- note: {note or '-'}\n\n"
        f"## Summary\n\n{summary}\n\n"
    )
    target = Path(cwd, BATON_DIR, f"{ctx.session.id}.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(head.encode("utf-8") + BEGIN + b"\n" + patch + END + b"\n")

    message = (
        f"Baton written: {BATON_DIR}/{ctx.session.id}.md (base {base[:7]}, {_count_files(patch)} file(s) in the patch). "
        "Send or commit this file; the receiver runs /baton take <path>."
    )
    if skipped:
        message += f" not included (over 1 MB): {', '.join(skipped)}"
    print(message)


def _parse(data):
    """Split a baton file into ``(from, base, summary, patch bytes)``; ``ValueError`` when a part is missing."""
    lines = data.split(b"\n")
    try:
        begin = lines.index(BEGIN)
        end = lines.index(END, begin + 1)
        summary_at = lines.index(b"## Summary")
    except ValueError:
        raise ValueError("not a baton file") from None
    if summary_at > begin:
        raise ValueError("not a baton file")
    fields = {}
    for line in lines[:summary_at]:
        text = line.decode("utf-8", "replace")
        for key in ("from", "base"):
            if text.startswith(f"- {key}: "):
                fields.setdefault(key, text[len(key) + 4 :].strip())
    if "from" not in fields or "base" not in fields:
        raise ValueError("not a baton file")
    summary = b"\n".join(lines[summary_at + 1 : begin]).decode("utf-8", "replace").strip()
    patch = b"".join(line + b"\n" for line in lines[begin + 1 : end])
    return fields["from"], fields["base"], summary, patch


def _take(path, ctx):
    file = Path(ctx.cwd, path)
    if not file.is_file():
        raise ValueError(f"no such file: {path}")
    origin, base, summary, patch = _parse(file.read_bytes())

    head = (_git(ctx.cwd, "rev-parse", "HEAD") or "").strip()
    if not head:
        raise ValueError("not a git repository with a commit")
    if head != base:
        raise ValueError(f"HEAD is {head[:7]} but the baton was made on {base[:7]}; check out {base} first")

    if patch:
        fd, name = tempfile.mkstemp(suffix=".patch")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(patch)
            for extra in (("--check",), ()):
                r = subprocess.run(["git", "apply", *extra, name], cwd=ctx.cwd, capture_output=True, text=True)
                if r.returncode != 0:
                    first = (r.stderr.strip().splitlines() or ["git apply failed"])[0]
                    raise ValueError(f"the patch does not apply: {first}")
        finally:
            os.unlink(name)

    if ctx.messages:
        ctx.session.save()
        ctx.session = open_session(new_id())
    ctx.messages.extend(
        [
            {
                "role": "user",
                "content": (
                    f"Handoff from another engineer's agent session ({origin}). "
                    f"The working tree already contains their changes.\n\n{summary}"
                ),
            },
            {"role": "assistant", "content": [{"type": "text", "text": "Understood. I will continue from this handoff."}]},
        ]
    )
    ctx.session.save()
    print(f"Baton taken: {_count_files(patch)} file(s) patched, session {ctx.session.id} starts from the summary.")


def _baton(args, ctx):
    action, _, rest = args.strip().partition(" ")
    if action == "pass":
        _pass(rest.strip(), ctx)
    elif action == "take" and rest.strip():
        _take(rest.strip(), ctx)
    else:
        raise ValueError(USAGE)


def register(minimal):
    minimal.register_command(
        "baton",
        _baton,
        description="hand off: /baton pass [note] | /baton take <path>",
    )
