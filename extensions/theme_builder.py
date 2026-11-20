"""Builds a full colour theme from one accent colour: /theme_builder <name> <#rrggbb> [dark|light] [options].

The accent gives the hue; backgrounds, borders, muted text and the other colours are derived from it, and every
text colour is moved along its lightness until it reaches 4.5:1 (WCAG AA) on the raised background, so a pale
accent on a dark theme (or a dark one on a light theme) still reads. Themes are saved in the extension's data
folder and registered again each time extensions load, so they survive ``/reload`` and restarts; the command
reloads once to show the new theme in ``/theme``. Running it again with the same name replaces the theme.

    /theme_builder ocean #4fc3f7 dark --secondary #ff9e64 --error #ff6b6b
    /theme_builder list                 the saved themes
    /theme_builder delete ocean         forget one
    /theme_builder export ocean         write it as a standalone ``themes/ocean.py`` extension into the data folder

Options ``--secondary``, ``--success``, ``--warning`` and ``--error`` take a ``#rrggbb`` colour instead of the derived
one (still moved until it is readable). Settings (``/ext settings theme_builder``): ``text_ratio`` and ``dim_ratio``
(the contrast text and ``dim`` reach), ``secondary_hue_offset`` (degrees from the accent's hue) and ``bg_saturation``
(how tinted the backgrounds are). They apply to every saved theme at the next load.

Install it with ``/ext``.
"""

import colorsys
import json
import os
import re

__version__ = "1.2"
__api__ = "2.3"
__tags__ = ["theme"]

USAGE = (
    "usage: /theme_builder <name> <accent #rrggbb> [dark|light] [--secondary #hex] [--success #hex] [--warning #hex] "
    "[--error #hex]   e.g. /theme_builder ocean #4fc3f7 dark; or /theme_builder list | delete <name> | export <name>"
)
MODES = ("dark", "light")
NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
SUBCOMMANDS = ("list", "delete", "export")
"""Words the command takes as its first argument, so no theme can be named like them."""
OPTIONS = ("secondary", "success", "warning", "error")
"""The colours a ``--<name> <#hex>`` option can set."""
TEXT_RATIO = 4.5
"""Default of the ``text_ratio`` setting: contrast every text colour reaches on the panel background (WCAG AA)."""
DIM_RATIO = 4.5
"""Default of ``dim_ratio``: contrast of ``dim`` (faint text and hints), the same AA floor as the other text."""
SECONDARY_HUE_OFFSET = 40
"""Default of ``secondary_hue_offset``: degrees the secondary colour's hue is turned from the accent's."""
BG_SATURATION = 0.5
"""Default of ``bg_saturation``: the share of the accent's saturation the background keeps (capped at 0.30)."""
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


def build_theme(
    accent,
    mode="dark",
    *,
    text_ratio=TEXT_RATIO,
    dim_ratio=DIM_RATIO,
    secondary_hue_offset=SECONDARY_HUE_OFFSET,
    bg_saturation=BG_SATURATION,
    colors=None,
):
    """The ``register_theme`` keyword arguments of a theme made from ``accent`` (hex text) in ``dark``/``light`` mode.

    Text colours (``foreground``, ``accent``, ``secondary``, ``success``, ``warning``, ``error``, ``muted``, ``code``,
    ``model``, ``path``, ``git_*``, ``diff_*``) reach ``text_ratio`` on ``panel``, hence on ``background``,
    ``surface`` and ``user_bg``, which lie between them; ``dim`` reaches ``dim_ratio`` and ``muted`` a point more.
    ``accent`` is lightened or darkened if it needs it. ``colors`` maps any of :data:`OPTIONS` to a hex colour that
    replaces the derived hue (it is still moved until it is readable).

    Raises:
        ValueError: if ``accent`` or a colour in ``colors`` is not a hex colour, or ``mode`` is not ``dark`` or ``light``.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be dark or light, not {str(mode)[:40]!r}")
    colors = colors or {}
    unknown = sorted(set(colors) - set(OPTIONS))
    if unknown:
        raise ValueError(f"unknown colour option(s) {', '.join(unknown)}; use {', '.join(OPTIONS)}")
    given = {key: parse_hex(value) for key, value in colors.items()}
    dark = mode == "dark"
    seed = parse_hex(accent)
    h, seed_lightness, s = colorsys.rgb_to_hls(*(c / 255 for c in seed))
    black = (0, 0, 0)

    background = hls(h, 0.10 if dark else 0.97, min(s * bg_saturation, 0.30))
    foreground = readable(hls(h, 0.90 if dark else 0.12, min(s, 0.20)), background, max(7.0, text_ratio + 0.5), dark)
    surface = mix(background, foreground, 0.05)
    panel = mix(background, foreground, 0.10)

    def text(color, ratio=text_ratio):
        return readable(color, panel, ratio, dark)

    base = 0.65 if dark else 0.35
    accent_color = text(seed)
    secondary = text(given.get("secondary") or hls(h + secondary_hue_offset / 360, seed_lightness, s))
    success = text(given.get("success") or hls(140 / 360, base, 0.60))
    warning = text(given.get("warning") or hls(40 / 360, base, 0.80))
    error = text(given.get("error") or hls(0.0, base, 0.70))
    muted = text(mix(foreground, background, 0.35), min(max(text_ratio, dim_ratio + 1.0), 9.0))
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
        "dim": text(mix(foreground, background, 0.55), dim_ratio),
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


def check_name(name):
    """``name`` if it can name a theme; ``ValueError`` saying why not otherwise."""
    if not NAME.fullmatch(name):
        raise ValueError(f"theme name {name[:40]!r} must be lowercase letters, digits, - or _ (up to 32); {USAGE}")
    if name == "minimal":
        raise ValueError("the built-in theme 'minimal' cannot be replaced; choose another name")
    if name in SUBCOMMANDS:
        raise ValueError(f"{name!r} is a /theme_builder subcommand and cannot name a theme; choose another name")
    return name


def parse_args(args):
    """``(name, accent, mode, colors)`` from the text of the build command: the accent normalised to ``#rrggbb``,
    ``colors`` the ``--secondary``/``--success``/``--warning``/``--error`` options given, normalised too.

    Raises ``ValueError`` if it is malformed."""
    words = args.split()
    positional, colors = [], {}
    i = 0
    while i < len(words):
        word = words[i]
        if word.startswith("--"):
            option, _, value = word[2:].partition("=")
            if option not in OPTIONS:
                raise ValueError(f"unknown option {word[:40]!r}; use {', '.join('--' + o for o in OPTIONS)}; {USAGE}")
            if not value:
                i += 1
                if i == len(words):
                    raise ValueError(f"--{option} needs a colour, e.g. --{option} #ff9e64")
                value = words[i]
            colors[option] = to_hex(parse_hex(value))
        else:
            positional.append(word)
        i += 1
    if not 2 <= len(positional) <= 3:
        raise ValueError(USAGE)
    name, accent = check_name(positional[0]), to_hex(parse_hex(positional[1]))
    mode = positional[2].lower() if len(positional) == 3 else "dark"
    if mode not in MODES:
        raise ValueError(f"mode must be dark or light, not {positional[2][:40]!r}; {USAGE}")
    return name, accent, mode, colors


def load_saved(path):
    """The saved themes as ``{name: (accent, mode, colors)}`` (``colors``: the options given, as for
    :func:`build_theme`); ``{}`` if there is no file.

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
            colors = {key: to_hex(parse_hex(entry[key])) for key in OPTIONS if key in entry}
            build_theme(accent, mode, colors=colors)
            saved[name] = (accent, mode, colors)
        return saved
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise ValueError(
            f"{path} holds an invalid theme ({e!r}); fix it or delete it to forget the saved themes"
        ) from e


def save(path, saved):
    """Write ``saved`` (``{name: (accent, mode, colors)}``) to ``path`` atomically."""
    data = {name: {"accent": accent, "mode": mode, **colors} for name, (accent, mode, colors) in sorted(saved.items())}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def export_source(name, theme):
    """The source of a standalone ``themes/<name>.py`` extension that registers ``theme`` (``build_theme``'s result)
    under ``name``, with an ``overrides`` setting like the marketplace's own themes."""
    body = "".join(f'    "{key}": {value!r},\n'.replace("'", '"') for key, value in theme.items())
    return f'''"""The {name} theme, exported from /theme_builder. Copy it into a ``themes`` folder of your extensions.

Override any colour without editing this file: ``/ext settings themes/{name.replace("-", "_")} overrides '{{"accent": "#ff8800"}}'``.
"""

import re

__version__ = "1.0"
__api__ = "2.3"
__tags__ = ["theme"]

NAME = "{name}"
PALETTE = {{
{body}}}
HEX = re.compile(r"#[0-9a-fA-F]{{6}}")


def register(minimal):
    settings = minimal.declare_settings(
        {{"overrides": {{}}}},
        {{
            "overrides": {{
                "description": "colours to change in this theme: an object of colour name -> #rrggbb, "
                'e.g. {{"accent": "#ff8800"}}'
            }}
        }},
    )
    palette = dict(PALETTE)
    bad = []
    for key, value in settings["overrides"].items():
        if key == "dark" or key not in palette:
            bad.append(f"unknown colour {{str(key)[:40]!r}}")
        elif not (isinstance(value, str) and HEX.fullmatch(value)):
            bad.append(f"{{key}} must be #rrggbb, got {{str(value)[:40]!r}}")
        else:
            palette[key] = value.lower()
    minimal.register_theme(NAME, **palette)
    if bad:
        raise ValueError(f"overrides: {{'; '.join(bad)}}")
'''


def register(minimal):
    settings = minimal.declare_settings(
        {
            "text_ratio": TEXT_RATIO,
            "dim_ratio": DIM_RATIO,
            "secondary_hue_offset": SECONDARY_HUE_OFFSET,
            "bg_saturation": BG_SATURATION,
        },
        {
            "text_ratio": {
                "description": "contrast (WCAG ratio) every text colour reaches on the panel background; 4.5 is AA",
                "min": 3.0,
                "max": 10.0,
            },
            "dim_ratio": {
                "description": "contrast of the dim colour (hints, faint text); muted is built one point above it",
                "min": 1.5,
                "max": 8.0,
            },
            "secondary_hue_offset": {
                "description": "degrees the secondary colour's hue is turned from the accent's (-180 to 180)",
                "min": -180,
                "max": 180,
            },
            "bg_saturation": {
                "description": "how tinted the backgrounds are: the share of the accent's saturation they keep "
                "(0 = grey, capped at 0.30 saturation)",
                "min": 0.0,
                "max": 1.0,
            },
        },
    )
    options = dict(
        text_ratio=settings["text_ratio"],
        dim_ratio=settings["dim_ratio"],
        secondary_hue_offset=settings["secondary_hue_offset"],
        bg_saturation=settings["bg_saturation"],
    )
    folder = minimal.data_dir("global")
    path = folder / FILE
    try:
        saved = load_saved(path)
    except ValueError:  # the command names the problem when the user next builds a theme
        saved = {}
    for name, (accent, mode, colors) in saved.items():
        minimal.register_theme(name, **build_theme(accent, mode, colors=colors, **options))

    def reload(ctx):
        # The registry is rebuilt from disk, so a live register_theme would be gone at the next reload.
        summary = ctx.reload()
        if "\nFailed: " in summary:
            print(summary)

    def store(themes):
        try:
            save(path, themes)
        except OSError as e:
            raise ValueError(f"cannot save the theme to {path} ({e}); make that folder writable") from e

    def known(themes, name):
        if name not in themes:
            have = ", ".join(sorted(themes)) or "none saved"
            raise ValueError(f"no saved theme {name[:40]!r} ({have}); see /theme_builder list")
        return themes[name]

    def listing():
        themes = load_saved(path)
        if not themes:
            print("No saved themes. Make one with /theme_builder <name> <#rrggbb> [dark|light].")
        for name, (accent, mode, colors) in sorted(themes.items()):
            extra = "".join(f" --{key} {value}" for key, value in colors.items())
            print(f"{name}: {accent} {mode}{extra}")

    def delete(name, ctx):
        themes = load_saved(path)
        known(themes, name)
        del themes[name]
        store(themes)
        reload(ctx)
        print(f"Theme {name!r} deleted.")

    def export(name):
        accent, mode, colors = known(load_saved(path), name)
        target = folder / "export" / "themes" / f"{name.replace('-', '_')}.py"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(export_source(name, build_theme(accent, mode, colors=colors, **options)), encoding="utf-8")
        except OSError as e:
            raise ValueError(f"cannot write {target} ({e}); make that folder writable") from e
        print(f"Theme {name!r} exported to {target}; copy it into a themes folder of your extensions to share it.")

    def theme_builder(args, ctx):
        words = args.split()
        if words and words[0] in SUBCOMMANDS:
            command, rest = words[0], words[1:]
            if command == "list" and not rest:
                return listing()
            if command in ("delete", "export") and len(rest) == 1:
                return delete(rest[0], ctx) if command == "delete" else export(rest[0])
            raise ValueError(USAGE)
        name, accent, mode, colors = parse_args(args)
        theme = build_theme(accent, mode, colors=colors, **options)
        themes = load_saved(path)
        themes[name] = (accent, mode, colors)
        store(themes)
        reload(ctx)
        note = f" (accent adjusted to {theme['accent']} for readability)" if theme["accent"] != accent else ""
        print(f"Theme {name!r} ({mode}) saved{note}. Pick it with /theme {name}; it is kept across restarts in {path}.")

    minimal.register_command(
        "theme_builder",
        theme_builder,
        description="make a theme from one colour: /theme_builder <name> <#rrggbb> [dark|light] [--error #hex ...] | list | delete | export",
    )
