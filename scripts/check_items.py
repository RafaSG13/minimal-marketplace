"""Quality gate for the marketplace's items; stdlib only. Run from anywhere: ``python scripts/check_items.py``.

Prints one line per problem and exits 1 if there is any:

1. every item (``<category>/<name>.py`` or ``<category>/<name>/``) is in the README catalogue, backtick-quoted;
2. on a pull request (``GITHUB_BASE_REF`` set; the checkout needs the base branch, ``fetch-depth: 0``), every
   item changed against ``origin/$GITHUB_BASE_REF`` has another ``__version__`` than on the base (new items are exempt);
3. every ``__tags__`` entry belongs to :data:`TAGS`.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = ("extensions", "themes", "tools", "widgets")
"""The folders that hold items."""
TAGS = ("git", "ui", "safety", "context", "agents", "provider", "theme", "diagnostics", "workflow")
"""The allowed ``__tags__``."""


def items() -> list[Path]:
    """The items on disk, as paths relative to the repository root, category by category."""
    found = []
    for category in CATEGORIES:
        folder = ROOT / category
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.name.startswith(("_", ".")):
                continue
            if (path.is_file() and path.suffix == ".py") or (path.is_dir() and (path / "__init__.py").is_file()):
                found.append(path.relative_to(ROOT))
    return found


def entry(item: Path) -> Path:
    """The module holding an item's metadata: the file, or a package's ``__init__.py``."""
    return item / "__init__.py" if (ROOT / item).is_dir() else item


def catalogue_path(item: Path) -> str:
    """How the README writes an item's path: ``<category>/<name>.py`` or ``<category>/<name>/``."""
    return item.as_posix() + ("/" if (ROOT / item).is_dir() else "")


def module_constants(source: str, names: tuple[str, ...]) -> dict[str, ast.expr]:
    """The value nodes of the top-level assignments to ``names`` in ``source``."""
    found: dict[str, ast.expr] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    found[target.id] = node.value
    return found


def version_of(source: str) -> str | None:
    """The string ``__version__`` of ``source``; ``None`` if it has none."""
    node = module_constants(source, ("__version__",)).get("__version__")
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def check_catalogue(found: list[Path]) -> list[str]:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    return [
        f"{item.as_posix()}: add a row for `{catalogue_path(item)}` to the catalogue in README.md"
        for item in found
        if f"`{catalogue_path(item)}`" not in readme
    ]


def check_tags(found: list[Path]) -> list[str]:
    problems = []
    for item in found:
        node = module_constants((ROOT / entry(item)).read_text(encoding="utf-8"), ("__tags__",)).get("__tags__")
        if node is None:
            continue
        if not isinstance(node, (ast.List, ast.Tuple)) or not all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts
        ):
            problems.append(f"{item.as_posix()}: __tags__ must be a list of strings")
            continue
        for tag in (e.value for e in node.elts):  # type: ignore[attr-defined]
            if tag not in TAGS:
                problems.append(f"{item.as_posix()}: unknown tag {tag!r}; use one of: {', '.join(TAGS)}")
    return problems


def check_versions(found: list[Path], base_ref: str) -> list[str]:
    base = f"origin/{base_ref}"
    diff = git("diff", "--name-only", f"{base}...HEAD")
    if diff.returncode != 0:
        return [f"cannot diff against {base} (checkout with fetch-depth: 0): {diff.stderr.strip()}"]
    changed = set(diff.stdout.split())
    problems = []
    for item in found:
        prefix = catalogue_path(item)
        if not any(path == prefix or path.startswith(prefix) for path in changed):
            continue
        shown = git("show", f"{base}:{entry(item).as_posix()}")
        if shown.returncode != 0:
            continue  # a new item
        old = version_of(shown.stdout)
        new = version_of((ROOT / entry(item)).read_text(encoding="utf-8"))
        if old == new:
            problems.append(f"{item.as_posix()}: changed but __version__ is still {new}; bump it")
    return problems


def main() -> int:
    found = items()
    problems = check_catalogue(found) + check_tags(found)
    base_ref = os.environ.get("GITHUB_BASE_REF")
    if base_ref:
        problems += check_versions(found, base_ref)
    for problem in problems:
        print(problem)
    if not problems:
        print(f"ok: {len(found)} items")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
