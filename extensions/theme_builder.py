"""Builds a full colour theme from one accent colour: /theme_builder <name> <#rrggbb> [dark|light].

The accent gives the hue; backgrounds, borders, muted text and the other colours are derived from it, and every
text colour is moved along its lightness until it reaches 4.5:1 (WCAG AA) on the raised background, so a pale
accent on a dark theme (or a dark one on a light theme) still reads. Themes are saved in the extension's data
folder and registered again each time extensions load, so they survive ``/reload`` and restarts; the command
reloads once to show the new theme in ``/theme``. Running it again with the same name replaces the theme.

Install it with ``/ext``.
"""

import colorsys
import json
import os
import re

__version__ = "1.1"
__api__ = "2"
__tags__ = ["theme"]

USAGE = "usage: /theme_builder <name> <accent #rrggbb> [dark|light]   e.g. /theme_builder ocean #4fc3f7 dark"
MODES = ("dark", "light")
NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
TEXT_RATIO = 4.5
"""Contrast every text colour reaches on the panel background (WCAG AA for normal text)."""
DIM_RATIO = 3.0
"""Contrast of ``dim`` (faint text and hints): WCAG AA for large text and UI components."""
FILE = "themes.json"


def parse_hex(text):
    """``(r, g, b)`` of ``#rrggbb``, ``rrggbb`` or ``#rgb``; ``ValueError`` saying how to write it otherwise."""
    digits = str(text).strip().removeprefix("#")
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", digits):
        raise ValueError(f"{str(text)[:40]!r} is not a hex colour; write it as #rrggbb, e.g. #4fc3f7")
    return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))


def to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def luminance(rgb):
    """WCAG relative luminance of an ``(r, g, b)`` colour, 0 (black) to 1 (white)."""
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (v / 255 for v in rgb))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG contrast ratio of two ``(r, g, b)`` colours, 1 to 21."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def mix(a, b, t):
    """The colour ``t`` (0 to 1) of the way from ``a`` to ``b``."""
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def hls(h, lightness, saturation):
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h % 1.0, lightness, saturation))


def readable(color, background, ratio, lighter):
    """``color`` moved along its lightness (up if ``lighter``, else down; hue and saturation kept) until it reaches
    ``ratio`` on ``background``."""
    h, lightness, s = colorsys.rgb_to_hls(*(c / 255 for c in color))
    for _ in range(100):
        if contrast(color, background) >= ratio:
            break
        lightness = min(1.0, max(0.0, lightness + (0.01 if lighter else -0.01)))
        color = hls(h, lightness, s)
    return color


def build_theme(accent, mode="dark"):
    """The ``register_theme`` keyword arguments of a theme made from ``accent`` (hex text) in ``dark``/``light`` mode.

    Text colours (``foreground``, ``accent``, ``secondary``, ``success``, ``warning``, ``error``, ``muted``, ``code``,
    ``model``, ``path``, ``git_*``, ``diff_*``) reach :data:`TEXT_RATIO` on ``panel``, hence on ``background``,
    ``surface`` and ``user_bg``, which lie between them. ``accent`` is lightened or darkened if it needs it.

    Raises:
        ValueError: if ``accent`` is not a hex colour or ``mode`` is not ``dark`` or ``light``.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be dark or light, not {str(mode)[:40]!r}")
    dark = mode == "dark"
    seed = parse_hex(accent)
    h, seed_lightness, s = colorsys.rgb_to_hls(*(c / 255 for c in seed))
    black = (0, 0, 0)

    background = hls(h, 0.10 if dark else 0.97, min(s * 0.5, 0.30))
    foreground = readable(hls(h, 0.90 if dark else 0.12, min(s, 0.20)), background, 7.0, dark)
    surface = mix(background, foreground, 0.05)
    panel = mix(background, foreground, 0.10)

    def text(color, ratio=TEXT_RATIO):
        return readable(color, panel, ratio, dark)

    base = 0.65 if dark else 0.35
    accent_color = text(seed)
    secondary = text(hls(h + 40 / 360, seed_lightness, s))
    success = text(hls(140 / 360, base, 0.60))
    warning = text(hls(40 / 360, base, 0.80))
    error = text(hls(0.0, base, 0.70))
    muted = text(mix(foreground, background, 0.35))
    palette = {
        "background": background,
        "foreground": foreground,
        "accent": accent_color,
        "surface": surface,
        "panel": panel,
        "secondary": secondary,
        "success": success,
        "warning": warning,
        "error": error,
        "muted": muted,
        "dim": text(mix(foreground, background, 0.55), DIM_RATIO),
        "border": readable(mix(background, foreground, 0.30), background, 3.0, dark),
        "focus": accent_color,
        "user_bg": mix(background, foreground, 0.07),
        "pending_bg": mix(background, accent_color, 0.08),
        "success_bg": mix(background, success, 0.12),
        "error_bg": mix(background, error, 0.16),
        "code": text(hls(h - 60 / 360, seed_lightness, s)),
        "model": accent_color,
        "path": secondary,
        "status_bg": mix(background, black, 0.35 if dark else 0.05),
        "git_clean": success,
        "git_dirty": warning,
        "selection": mix(background, accent_color, 0.35),
        "diff_added": success,
        "diff_removed": error,
    }
    return {"dark": dark, **{key: to_hex(value) for key, value in palette.items()}}


def parse_args(args):
    """``(name, accent, mode)`` from the command's text, the accent normalised to ``#rrggbb``.

    Raises ``ValueError`` if it is malformed."""
    parts = args.split()
    if not 2 <= len(parts) <= 3:
        raise ValueError(USAGE)
    name, accent = parts[0], to_hex(parse_hex(parts[1]))
    mode = parts[2].lower() if len(parts) == 3 else "dark"
    if not NAME.fullmatch(name):
        raise ValueError(f"theme name {name[:40]!r} must be lowercase letters, digits, - or _ (up to 32); {USAGE}")
    if name == "minimal":
        raise ValueError("the built-in theme 'minimal' cannot be replaced; choose another name")
    if mode not in MODES:
        raise ValueError(f"mode must be dark or light, not {parts[2][:40]!r}; {USAGE}")
    return name, accent, mode


def load_saved(path):
    """The saved themes as ``{name: (accent, mode)}``; ``{}`` if there is no file.

    Raises ``ValueError`` naming the file if it is unusable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise ValueError(f"{path} is unreadable ({e}); fix it or delete it to forget the saved themes") from e
    try:
        saved = {}
        for name, entry in data.items():
            if not NAME.fullmatch(name) or name == "minimal":
                raise ValueError(f"bad theme name {name[:40]!r}")
            accent, mode = to_hex(parse_hex(entry["accent"])), entry["mode"]
            build_theme(accent, mode)
            saved[name] = (accent, mode)
        return saved
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise ValueError(
            f"{path} holds an invalid theme ({e!r}); fix it or delete it to forget the saved themes"
        ) from e


def save(path, saved):
    """Write ``saved`` (``{name: (accent, mode)}``) to ``path`` atomically."""
    data = {name: {"accent": accent, "mode": mode} for name, (accent, mode) in sorted(saved.items())}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def register(minimal):
    path = minimal.data_dir("global") / FILE
    try:
        saved = load_saved(path)
    except ValueError:  # the command names the problem when the user next builds a theme
        saved = {}
    for name, (accent, mode) in saved.items():
        minimal.register_theme(name, **build_theme(accent, mode))

    def theme_builder(args, ctx):
        name, accent, mode = parse_args(args)
        theme = build_theme(accent, mode)
        themes = load_saved(path)
        themes[name] = (accent, mode)
        try:
            save(path, themes)
        except OSError as e:
            raise ValueError(f"cannot save the theme to {path} ({e}); make that folder writable") from e
        # The registry is rebuilt from disk, so a live register_theme would be gone at the next reload.
        summary = ctx.reload()
        if "\nFailed: " in summary:
            print(summary)
        note = f" (accent adjusted to {theme['accent']} for readability)" if theme["accent"] != accent else ""
        print(f"Theme {name!r} ({mode}) saved{note}. Pick it with /theme {name}; it is kept across restarts in {path}.")

    minimal.register_command(
        "theme_builder",
        theme_builder,
        description="make a theme from one colour: /theme_builder <name> <#rrggbb> [dark|light]",
    )
