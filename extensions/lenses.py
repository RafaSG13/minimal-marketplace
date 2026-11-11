"""Output lenses: compress noisy bash output and keep the full text on disk.

Long bash output is shortened (user lenses, built-in lenses, repeated lines,
head and tail) and the full text is saved under .minimal/outputs/.
"""

__version__ = "1.1"
__requires__ = ">=0.2"

import re
import sys
from pathlib import Path

OUTPUT_DIR = ".minimal/outputs"
LENS_DIR = ".minimal/lenses"

PASSING = (
    r".* \.\.\. ok",
    r"[.sx]+",
    r"\S+ [.sx]+\s*(\[\s*\d+%\])?",
    r".* PASSED(\s+\[\s*\d+%\])?",
)


def _python_tests(command, output):
    lines = output.splitlines()
    kept = [line for line in lines if not any(re.fullmatch(p, line) for p in PASSING)]
    hidden = len(lines) - len(kept)
    if not hidden:
        return None
    note = f"[lens python-tests: {hidden} passing lines hidden]"
    if kept and kept[-1].startswith("[exit "):
        kept.insert(len(kept) - 1, note)
    else:
        kept.append(note)
    return "\n".join(kept)


def _repeat(output):
    lines = output.split("\n")
    out, i = [], 0
    while i < len(lines):
        j = i
        while j + 1 < len(lines) and lines[j + 1] == lines[i]:
            j += 1
        run = j - i + 1
        out.append(lines[i])
        if run >= 3:
            out.append(f"[previous line repeated {run - 1} more times]")
        else:
            out.extend(lines[i + 1 : j + 1])
        i = j + 1
    return "\n".join(out)


def _outputs(root):
    folder = Path(root, OUTPUT_DIR)
    return sorted(folder.glob("*.txt")) if folder.is_dir() else []


def _save_output(root, raw):
    numbers = [int(p.stem) for p in _outputs(root) if p.stem.isdecimal()]
    n = max(numbers, default=0) + 1
    folder = Path(root, OUTPUT_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{n:04d}.txt").write_text(raw, encoding="utf-8")
    return n


def _load_user_lenses(root):
    lenses, errors = [], []
    folder = Path(root, LENS_DIR)
    for file in sorted(folder.glob("*.py")) if folder.is_dir() else []:
        try:
            namespace = {"__name__": f"lens_{file.stem}", "__file__": str(file)}
            exec(compile(file.read_text(encoding="utf-8"), str(file), "exec"), namespace)
            pattern, lens = namespace.get("PATTERN"), namespace.get("lens")
            if not isinstance(pattern, str) or not callable(lens):
                raise ValueError("must define PATTERN (str) and lens(command, output)")
            re.compile(pattern)
        except Exception as e:
            errors.append(f"{file.name}: {e}")
            continue
        lenses.append((file.stem, pattern, lens, f"{LENS_DIR}/{file.name}"))
    return lenses, errors


def register(minimal):
    settings = minimal.declare_settings({"min_chars": 2000, "head": 6000, "tail": 12000})
    min_chars, head, tail = settings["min_chars"], settings["head"], settings["tail"]

    user_lenses, errors = _load_user_lenses(Path.cwd())
    lenses = [*user_lenses, ("python-tests", r"\b(pytest|unittest)\b", _python_tests, "(built-in)")]

    def compress(event):
        raw = event["output"]
        if event["name"] != "bash" or len(raw) < min_chars:
            return None
        command = event["input"].get("command", "")
        out = raw
        for name, pattern, lens, _ in lenses:
            if not re.search(pattern, command):
                continue
            try:
                result = lens(command, raw)
            except Exception as e:
                print(f"[lenses] {name} failed: {e}", file=sys.stderr)
                continue
            if isinstance(result, str) and result != raw:
                out = result
                break
        out = _repeat(out)
        last = raw.rstrip().splitlines()[-1] if raw.strip() else ""
        if len(out) > head + tail:
            out = out[:head] + f"\n... [lens: {len(out) - head - tail} characters omitted here]\n" + out[-tail:]
        if out == raw:
            return None
        n = _save_output(event["ctx"].cwd, raw)
        out += (
            f"\n[full output: {OUTPUT_DIR}/{n:04d}.txt, {len(raw.splitlines())} lines; "
            "read it with offset and limit]"
        )
        event["output"] = out
        return {"output": out}

    minimal.on("tool_result", compress)

    minimal.append_system_prompt(
        f"Output lenses: bash output over {min_chars} characters is compressed and the full text is saved under "
        ".minimal/outputs/ (read it with offset and limit when you need hidden lines). When a command you "
        "run repeatedly produces noisy output, write a lens: a file .minimal/lenses/<name>.py defining "
        "PATTERN (a regex searched in the command) and lens(command, output) -> str | None (return the "
        "shortened output, or None to leave it unchanged), then call reload_extensions."
    )

    def lenses_command(args, ctx):
        arg = args.strip()
        if arg not in ("", "clear"):
            raise ValueError("usage: /lenses [clear]")
        saved = _outputs(ctx.cwd)
        if arg == "clear":
            for p in saved:
                p.unlink()
            print(f"Removed {len(saved)} saved output(s).")
            return
        for name, pattern, _, source in lenses:
            print(f"{name}  {pattern}  {source}")
        print(f"{len(saved)} saved output(s) in {OUTPUT_DIR}")

    minimal.register_command(
        "lenses", lenses_command, description="list output lenses; /lenses clear deletes saved outputs"
    )

    if errors:
        raise ValueError("lenses: " + "; ".join(errors))
