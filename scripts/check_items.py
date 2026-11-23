"""Quality gate for the marketplace's items; stdlib only. Run from anywhere: ``python scripts/check_items.py``.

Prints one line per problem and exits 1 if there is any:

1. every item (``<category>/<name>.py`` or ``<category>/<name>/``) is in the README catalogue, backtick-quoted;
2. on a pull request (``GITHUB_BASE_REF`` set; the checkout needs the base branch, ``fetch-depth: 0``), every
   item changed against ``origin/$GITHUB_BASE_REF`` has another ``__version__`` than on the base (new items are exempt);
3. every ``__tags__`` entry belongs to :data:`TAGS`;
4. every theme item (``themes/*.py``) passes the contrast gate (:func:`check_themes`): WCAG ratios of its registered
   colours against ``background`` and ``panel`` reach the floors :data:`TEXT_FLOOR`, :data:`DIM_FLOOR` and
   :data:`PANEL_FLOOR`, and ``pending_bg`` differs from ``success_bg``;
5. every item id in :data:`TESTED` has ``tests/test_<name>.py`` with at least one ``def test_``;
6. in those items, every ``register_tool(...)`` / ``@minimal.tool(...)`` call states ``read_only=`` or ``confirm=``
   and every ``declare_settings(...)`` call passes the defaults and the schema.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = ("extensions", "themes", "tools", "widgets")
"""The folders that hold items."""
TAGS = (
    "git",
    "ui",
    "safety",
    "context",
    "agents",
    "provider",
    "theme",
    "diagnostics",
    "workflow",
    "docker",
    "files",
    "github",
    "search",
    "integration",
    "sandbox",
)
"""The allowed ``__tags__``."""
TESTED: frozenset[str] = frozenset({"extensions/tui_tools", "tools/git", "tools/fs", "tools/docker", "tools/gh", "extensions/pr_review", "extensions/skills", "extensions/mcp", "extensions/lsp"})
"""Ids (``extensions/<name>.py`` or ``tools/<name>.py`` paths without the suffix, e.g. ``tools/git``) of the items that
must have ``tests/test_<name>.py`` and follow the item standard (explicit ``read_only``/``confirm``, a settings
schema). It grows as items are written or audited."""


TEXT_FLOOR = 4.5
"""Contrast on ``background`` of ``foreground``, ``muted``, ``accent``, ``error``, ``success`` and ``warning``
(WCAG AA for normal text)."""
DIM_FLOOR = 4.5
"""Contrast of ``dim`` (hints, bar tracks, context lines) on ``background``; ``dim`` is still text."""
PANEL_FLOOR = 3.0
"""Contrast of ``muted`` and ``dim`` on ``panel``, the raised background of selected rows (WCAG AA for large text)."""
TEXT_COLORS = ("foreground", "muted", "accent", "error", "success", "warning")
SEMANTIC = {
    True: {"success": "#89d281", "warning": "#e5c07b", "error": "#e06c75"},
    False: {"success": "#1a7f37", "warning": "#9a6700", "error": "#cf222e"},
}
"""The state colours minimal gives a theme that leaves them out, for dark (``True``) and light themes
(``minimal.extensions.palette``)."""
HEX = re.compile(r"#[0-9a-fA-F]{6}")


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


def channels(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def luminance(color: str) -> float:
    """WCAG relative luminance of ``#rrggbb``."""
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (v / 255 for v in channels(color)))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two ``#rrggbb`` colours, 1 to 21."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def blend(start: str, end: str, factor: float) -> str:
    """``start`` moved ``factor`` of the way to ``end`` (what ``minimal.extensions.palette.blend`` does)."""
    mixed = (int(x + (y - x) * factor) for x, y in zip(channels(start), channels(end)))
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def complete(dark: bool, colors: dict[str, str]) -> dict[str, str]:
    """``colors`` with the colours the gate reads that a theme may leave out derived as minimal derives them
    (``minimal.extensions.palette.complete``), lowercase."""
    c = {key: value.lower() for key, value in colors.items()}
    background, foreground = c["background"], c["foreground"]
    for key, value in SEMANTIC[dark].items():
        c.setdefault(key, value)
    surface = c.setdefault("surface", blend(background, foreground, 0.05))
    c.setdefault("panel", blend(background, foreground, 0.10))
    c.setdefault("muted", blend(background, foreground, 0.55))
    c.setdefault("dim", blend(background, foreground, 0.38))
    c.setdefault("pending_bg", surface)
    c.setdefault("success_bg", surface)
    return c


def literal(node: ast.expr) -> object:
    """The value of a literal ``node``; ``None`` if it is not one."""
    try:
        return ast.literal_eval(node)
    except ValueError:
        return None


def theme_palettes(source: str) -> list[tuple[str, dict[str, object]]]:
    """The ``(name, colours)`` a theme module registers, read without importing it.

    Understood: ``register_theme("name", dark=..., background=..., ...)`` with literal keywords; ``**PALETTE`` where
    ``PALETTE`` is a top-level dict literal; and, for a ``**palette`` that is not a top-level name (a local copy
    with overrides, a loop variable), every top-level palette dict literal (``{colours}``, named by ``NAME``) or
    ``{name: {colours}}`` table. ``dark`` may be a key of the palette.
    """
    tree = ast.parse(source)
    consts: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            consts[node.targets[0].id] = literal(node.value)
    found: list[tuple[str, dict[str, object]]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) == "register_theme"):
            continue
        name = literal(node.args[0]) if node.args else None
        colors: dict[str, object] = {}
        tables = False
        for keyword in node.keywords:
            if keyword.arg is not None:
                colors[keyword.arg] = literal(keyword.value)
            elif isinstance(keyword.value, ast.Name) and isinstance(consts.get(keyword.value.id), dict):
                colors.update(consts[keyword.value.id])  # type: ignore[arg-type]
            else:
                tables = True
        if tables:
            for key, value in consts.items():
                if isinstance(value, dict) and value and all(isinstance(v, dict) and "background" in v for v in value.values()):
                    found += [(str(k), dict(v)) for k, v in value.items()]
                elif isinstance(value, dict) and "background" in value:
                    found.append((str(consts.get("NAME", key)), dict(value)))
        else:
            found.append((name if isinstance(name, str) else "?", colors))
    return found


def check_theme(label: str, colors: dict[str, object]) -> list[str]:
    """The contrast problems of one theme's colours (see :func:`check_themes`)."""
    problems = []
    for key in ("background", "foreground", "accent"):
        if not (isinstance(colors.get(key), str) and HEX.fullmatch(colors[key])):  # type: ignore[arg-type]
            return [f"{label}: {key} must be a #rrggbb literal"]
    bad = [k for k, v in colors.items() if k != "dark" and not (isinstance(v, str) and HEX.fullmatch(v))]
    if bad:
        return [f"{label}: not a #rrggbb literal: {', '.join(sorted(bad))}"]
    c = complete(bool(colors.get("dark", True)), {k: v for k, v in colors.items() if k != "dark"})  # type: ignore[misc]

    def need(text: str, ground: str, floor: float) -> None:
        ratio = contrast(c[text], c[ground])
        if ratio < floor:
            problems.append(f"{label}: {text} {c[text]} on {ground} {c[ground]} is {ratio:.2f}:1, below {floor}:1")

    for text in TEXT_COLORS:
        need(text, "background", TEXT_FLOOR)
    need("dim", "background", DIM_FLOOR)
    for text in ("muted", "dim"):
        need(text, "panel", PANEL_FLOOR)
    if c["pending_bg"] == c["success_bg"]:
        problems.append(f"{label}: pending_bg and success_bg are both {c['pending_bg']}; make them differ")
    return problems


def check_themes(found: list[Path]) -> list[str]:
    """The contrast gate: for every ``themes/`` item, ``foreground``, ``muted``, ``accent``, ``error``, ``success`` and
    ``warning`` reach :data:`TEXT_FLOOR` and ``dim`` reaches :data:`DIM_FLOOR` on ``background``; ``muted`` and ``dim``
    reach :data:`PANEL_FLOOR` on ``panel``; ``pending_bg`` differs from ``success_bg``. Colours a theme leaves out
    are derived as minimal does."""
    problems = []
    for item in found:
        if item.parts[0] != "themes":
            continue
        palettes = theme_palettes((ROOT / entry(item)).read_text(encoding="utf-8"))
        if not palettes:
            problems.append(f"{item.as_posix()}: no register_theme(...) with literal colours found for the contrast gate")
        for name, colors in palettes:
            problems += check_theme(f"{item.as_posix()} [{name}]", colors)
    return problems


def check_tests(found: list[Path]) -> list[str]:
    """Every item of :data:`TESTED` has a test file with at least one test (and every id names an item)."""
    on_disk = {item.with_suffix("").as_posix() for item in found}
    problems = []
    for ident in sorted(TESTED):
        if ident not in on_disk:
            problems.append(f"{ident}: listed in TESTED but there is no such item")
            continue
        name = Path(ident).name
        test = ROOT / "tests" / f"test_{name}.py"
        if not test.is_file() or "def test_" not in test.read_text(encoding="utf-8"):
            problems.append(f"{ident}: no tests/test_{name}.py with a test")
    return problems


def _call_name(node: ast.Call) -> str:
    return getattr(node.func, "attr", getattr(node.func, "id", ""))


def check_standard(found: list[Path]) -> list[str]:
    """The item standard's mechanical part, for the items of :data:`TESTED`: tools state ``read_only=``/``confirm=``
    and settings declare a schema."""
    problems = []
    for item in found:
        if item.with_suffix("").as_posix() not in TESTED or item.parts[0] not in ("extensions", "tools"):
            continue
        tree = ast.parse((ROOT / entry(item)).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            keywords = {k.arg for k in node.keywords}
            if name in ("register_tool", "tool") and not (keywords & {"read_only", "confirm"}) and None not in keywords:
                problems.append(f"{item.as_posix()}:{node.lineno}: {name}(...) must state read_only= or confirm=")
            if name == "declare_settings" and len(node.args) + len(keywords & {"schema"}) < 2:
                problems.append(f"{item.as_posix()}:{node.lineno}: declare_settings(...) needs the defaults and a schema")
    return problems


def main() -> int:
    found = items()
    problems = (
        check_catalogue(found) + check_tags(found) + check_themes(found) + check_tests(found) + check_standard(found)
    )
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
