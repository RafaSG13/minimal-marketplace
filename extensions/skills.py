"""Skills: folders of instructions the model loads on demand. Put `<name>/SKILL.md` under `~/.minimal/skills/` or a trusted project's `.minimal/skills/`.

A skill is a folder whose ``SKILL.md`` starts with a frontmatter block::

    ---
    name: release-notes
    description: How we write release notes and where they go.
    ---
    The instructions...

The system prompt lists each skill's name and description; the model calls the ``skill`` tool to read one before it
relies on it (the result lists the other files in the folder, which it opens with ``read``). A project's skills come
only after ``/trust`` and win over a global skill of the same name. ``/skills`` lists them, ``/skills <name>`` shows
one. Settings (``/ext settings skills``): ``enabled``, ``max_skills`` (listed in the prompt), ``description_chars``
(longest description), ``global_dir`` and ``project_dir`` (where to look; the project one is relative to the working
folder).

Install it with ``/ext``.
"""

import os
import re
from pathlib import Path

__version__ = "1.0"
__api__ = "2.4"
__tags__ = ["context", "workflow"]

DEFAULTS = {
    "enabled": True,
    "max_skills": 50,
    "description_chars": 500,
    "global_dir": "~/.minimal/skills",
    "project_dir": ".minimal/skills",
}

SCHEMA = {
    "enabled": {"description": "Offer skills: the prompt list, the skill tool and /skills."},
    "max_skills": {"description": "Most skills listed in the system prompt.", "min": 1, "max": 500},
    "description_chars": {"description": "Longest description a skill may have; longer ones are rejected.", "min": 20, "max": 2000},
    "global_dir": {"description": "Folder of your skills (each one a folder with a SKILL.md); ~ is expanded."},
    "project_dir": {"description": "Folder of a trusted project's skills, relative to the working folder."},
}

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
MAX_FILES = 50
"""Most files of a skill's folder the ``skill`` tool lists."""
HEAD = "Skills available (load with the skill tool before relying on them):"


def parse_skill(path, description_chars):
    """``(name, description, body)`` of the ``SKILL.md`` at ``path``; ``ValueError`` saying what is wrong with it."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("it must start with a --- frontmatter block holding name: and description:")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError("the frontmatter block is not closed with ---") from None
    fields = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if sep and key.strip():
            fields[key.strip()] = value.strip().strip("\"'")
    name, description = fields.get("name", ""), fields.get("description", "")
    folder = Path(path).parent.name
    if not NAME.fullmatch(name):
        raise ValueError("name must be lowercase letters, digits, _ and - (at most 64, not starting with - or _)")
    if name != folder:
        raise ValueError(f"name {name!r} must equal the folder name {folder!r}")
    if not description:
        raise ValueError("description is required: say when the skill applies")
    if len(description) > description_chars:
        raise ValueError(f"description is {len(description)} characters; the limit is {description_chars}")
    return name, description, "\n".join(lines[end + 1 :]).strip("\n")


def scan(folder, description_chars):
    """``({name: (description, SKILL.md path)}, [problem texts])`` of the skill folders in ``folder``."""
    found, problems = {}, []
    try:
        children = sorted(os.listdir(folder))
    except OSError:
        return found, problems
    for child in children:
        path = Path(folder, child, "SKILL.md")
        if not path.is_file():
            continue
        try:
            name, description, _ = parse_skill(path, description_chars)
        except (ValueError, OSError) as e:
            problems.append(f"skill {path}: {e}; skipped")
            continue
        found[name] = (description, path)
    return found, problems


def register(minimal):
    settings = minimal.declare_settings(DEFAULTS, SCHEMA)
    if not settings["enabled"]:
        return
    reported = set()
    cache = {}

    def report(problems):
        for problem in problems:
            if problem not in reported:
                reported.add(problem)
                minimal.report_problem(problem)

    def folders(ctx):
        """The skill folders in force, global first; the project's only while the project is trusted."""
        out = [Path(os.path.expanduser(settings["global_dir"]))]
        if getattr(ctx, "project_trusted", False):
            out.append(Path(ctx.cwd, settings["project_dir"]))
        return out

    def skills(ctx):
        """``{name: (description, path)}``: project skills over global ones; cached until a SKILL.md changes."""
        merged = {}
        for folder in folders(ctx):
            try:
                stamp = tuple((c, os.stat(Path(folder, c, "SKILL.md")).st_mtime_ns) for c in sorted(os.listdir(folder)) if Path(folder, c, "SKILL.md").is_file())
            except OSError:
                stamp = ()
            key = (str(folder), settings["description_chars"])
            if key not in cache or cache[key][0] != stamp:
                found, problems = scan(folder, settings["description_chars"])
                report(problems)
                cache[key] = (stamp, found)
            merged.update(cache[key][1])
        return merged

    def index(ctx):
        found = skills(ctx)
        if not found:
            return None
        rows = [f"- {name}: {desc}" for name, (desc, _) in sorted(found.items())[: settings["max_skills"]]]
        return "\n".join([HEAD, *rows])

    minimal.register_prompt_section("skills", index)

    def load(name, ctx):
        found = skills(ctx)
        if name not in found:
            known = ", ".join(sorted(found)) or "none installed"
            raise ValueError(f"no skill named {name!r}; known skills: {known}")
        path = found[name][1]
        _, _, body = parse_skill(path, settings["description_chars"])
        root = path.parent
        files = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p.name != "SKILL.md")
        listing = ", ".join(files[:MAX_FILES]) + (f" (+{len(files) - MAX_FILES} more)" if len(files) > MAX_FILES else "")
        return f"# {name}\nFolder: {root}\n\n{body}\n\nFiles: {listing or '(none)'}"

    @minimal.tool(
        read_only=True,
        input_schema={"type": "object", "properties": {"name": {"type": "string", "description": "Skill name from the list in the system prompt"}}, "required": ["name"]},
    )
    def skill(input, ctx):
        """Load a skill: its instructions and the files in its folder. Call it before relying on a listed skill; read-only."""
        return load(str(input.get("name", "")).strip(), ctx)

    def skills_command(args, ctx):
        name = args.strip()
        if name:
            try:
                return load(name, ctx)
            except ValueError as e:
                return str(e)
        found = skills(ctx)
        if not found:
            return f"No skills. Put <name>/SKILL.md folders in {os.path.expanduser(settings['global_dir'])} (or, in a trusted project, {settings['project_dir']})."
        return "\n".join(f"{name:<24} {desc}  [{path.parent}]" for name, (desc, path) in sorted(found.items()))

    minimal.register_command("skills", skills_command, description="list the skills, or show one: /skills [name]")

    report(scan(Path(os.path.expanduser(settings["global_dir"])), settings["description_chars"])[1])
