# minimal-marketplace

<p>
  <a href="https://github.com/RafaSG13/minimal-marketplace/actions/workflows/check.yml"><img src="https://img.shields.io/github/actions/workflow/status/RafaSG13/minimal-marketplace/check.yml?branch=main&label=check" alt="Check status"></a>
  <a href="https://pypi.org/project/mnml-agent/"><img src="https://img.shields.io/pypi/v/mnml-agent?label=minimal&color=6f86f4" alt="minimal on PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ea44f" alt="MIT License"></a>
</p>

Extensions, tools, widgets and themes for [minimal](https://github.com/RafaSG13/Minimal), the terminal coding-agent harness. This is minimal's default marketplace: `/ext` lists it out of the box.

Requires minimal 0.5 or later (extension API 2). An item written for a newer API than your minimal provides is not offered as is: `/ext` installs the newest older version of it that your minimal can run. The interface items and every theme use the 0.9 customisation API (settings for glyphs, colours, titles, order and limits; `$name` styles; CSS), so with an older minimal `/ext` installs their previous version; themes also take per-colour `overrides`.

## Layout

The repository is flat: one top-level folder per item category.

```
extensions/    general extensions
themes/        colour themes
tools/         tools for the model
widgets/       interface components, panels and header logos
```

Each category holds `<name>.py` files or `<name>/` package folders. `/ext` lists these four folders and installs into `~/.minimal/extensions/` (extensions) or its `themes/`, `tools/` and `widgets/` subfolders, or the same under a project's `./.minimal/extensions/`.

## Use

Install minimal, which includes the Textual terminal UI:

```bash
uv tool install mnml-agent
```

Then run `minimal` and, inside it:

```
/ext                         pick a marketplace and a category, then tick items to install, update or remove
/ext list                    installed items, by scope and category
/ext search <query> [category]  search every marketplace by name, description or tag
/ext publish <path> [name]   propose a file or package folder: pushes a publish/<name>-<timestamp> branch and opens a pull request
/theme [name]                switch to an installed theme
```

Each item can go into your global folder (`~/.minimal/extensions/`, every project) or the current project's (`./.minimal/extensions/`, loaded after `/trust`). Before installing globally, minimal shows a static scan of what the code can do and asks. If an item declares third-party packages, `/ext` offers to install them into minimal's Python.

## Catalogue

The paths below are the marketplace folders.

### Extensions

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `claude_subscription` | `extensions/claude_subscription.py` | The `claude` provider: a Claude Pro/Max subscription through a browser login instead of an API key (`minimal --login claude`). Thinking and pictures work as with `anthropic`, and it knows the `claude-` context windows; default model and windows are settings. Needs minimal 0.9; moves a login kept by an older minimal. |
| `compact` | `extensions/compact.py` | Summarises the history into a new session when the context reaches a threshold (a token count or a fraction of the model's window), also in the middle of a long turn; adds `/compact`. Exchanges kept, summary prompt, model, reasoning effort and toasts are settings; `auto` false leaves only `/compact`. Needs minimal 0.9. |
| `creator` | `extensions/creator.py` | Has the model create extensions, tools, widgets and themes: 2.3 skeletons (settings with schema, titles, keys), the API source and conventions, validation with a lint for API and tags, version bumps, removal, a catalogue row for publishing, and `/create <kind> <name> [description]`. Needs minimal 0.9. |
| `crystallize` | `extensions/crystallize.py` | Turns commands the model runs again and again into tools, and the calls you deny into `AGENTS.md` rules (`/crystallize`); thresholds, rules file and wording are settings. Needs minimal 0.9. |
| `help_overlay` | `extensions/help_overlay.py` | `/keys` (alias `/shortcuts`) lists the live key bindings and every slash command, with an optional filter. Needs minimal 0.9. |
| `ledger` | `extensions/ledger.py` | A sidebar panel of the heaviest tool results in the context, flagging stale reads; `/prune` drops the ones you pick and continues in a new session. |
| `lenses` | `extensions/lenses.py` | Shortens long `bash` output (passing Python test lines, repeated lines, head and tail) and keeps the full text in `.minimal/outputs/`; limits, your own `rules`, saved folder and notes are settings, and `/lenses on\|off` or a key switch it. Needs minimal 0.9. |
| `loose_ends` | `extensions/loose_ends.py` | A `note` tool and backlog for what the model could not verify, noticed or left to do; `/ends` reviews it; panel, limits and wording are settings. Needs minimal 0.9. |
| `mermaid` | `extensions/mermaid.py` | Draws `mermaid` code blocks in replies as diagrams. Needs `termaid` (offered on install). |
| `modes` | `extensions/modes.py` | Plan and build modes: investigate read-only and end with a numbered plan, approve it at the gate when you switch to build, and optionally start in a chosen mode (`/mode`, `Shift+Tab`). Needs minimal 0.7. |
| `retry` | `extensions/retry.py` | Retries requests that fail with rate limits, overloads or network errors, with backoff, and can switch to a fallback provider; statuses, errors and texts that count, backoff factor, messages and a live countdown next to the working indicator are settings. Needs minimal 0.9. |
| `scope_fence` | `extensions/scope_fence.py` | Blocks edits outside the paths you declare, or over a diff budget (`/fence`); messages, exemptions and the budget are settings, with an optional status-line segment and key. Needs minimal 0.9. |
| `term_title` | `extensions/term_title.py` | Names your terminal window or tab `minimal: <project> [idle\|working]` and puts the old title back on exit. |
| `theme_builder` | `extensions/theme_builder.py` | `/theme_builder <name> <#rrggbb> [dark\|light]` builds a full theme from one accent colour and keeps it across restarts; contrast and hue are settings, and `list`, `delete` and `export` manage the saved themes. |
| `tripwire` | `extensions/tripwire.py` | Re-runs your invariant commands (from `/tripwire` or the `commands` setting) after file changes and tells the model which call broke them; shows progress and can notify when one starts failing. Needs minimal 0.9. |
| `tui_tools` | `extensions/tui_tools.py` | Runs terminal UIs inside minimal: `/lazygit`, `/yazi`, `/btop`, `/lazydocker`, `/k9s`, `/gh-dash`, `/tig`, `/gitui` (those found on PATH) and your own tools; `/tui` lists them with install hints, says what a git tool changed and prints the files yazi picked as `@paths`. Needs minimal 0.9. |

### Tools

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `tools/ask_user` | `tools/ask_user.py` | Lets the model ask you a clarifying question (free text or pick one option) instead of guessing; the option limit and the no-answer text are settings. |
| `tools/delegate` | `tools/delegate.py` | Hands a self-contained task to a fresh agent and returns only its final message; tool allow-list, model, reasoning effort, turn limit and role name, progress while it runs, optionally read-only so several delegates overlap; fails with its status instead of hanging. Replaces `tools/subagent`. Needs minimal 0.9. |
| `tools/web_search` | `tools/web_search.py` | Web search through the Brave Search API; parallel (read-only) calls, result count, timeout, clipping, locale and safe search are settings. Needs `BRAVE_API_KEY`. Needs minimal 0.9. |

### Themes

Install them from `/ext` → Themes and switch with `/theme`.

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `themes/accessible_themes` | `themes/accessible_themes.py` | High-contrast dark and light themes, every text colour at least 4.5:1 (WCAG AA); per-colour `overrides`. |
| `themes/amber` | `themes/amber.py` | Dark palette with a yellow accent. |
| `themes/ayu_mirage` | `themes/ayu_mirage.py` | Ayu Mirage: the soft slate-blue Ayu dark theme with an orange accent. |
| `themes/catppuccin` | `themes/catppuccin.py` | Mocha: a soft pastel dark theme with a mauve accent. |
| `themes/catppuccin_latte` | `themes/catppuccin_latte.py` | The light Catppuccin flavour, warm and creamy with a mauve accent. |
| `themes/cyberpunk` | `themes/cyberpunk.py` | Near-black violet with neon pink and cyan. |
| `themes/dark` | `themes/dark.py` | A neutral dark editor palette with a blue accent. |
| `themes/dracula` | `themes/dracula.py` | The classic purple-and-pink dark theme. |
| `themes/everforest` | `themes/everforest.py` | Everforest: comfortable green-tinted dark theme with warm, low-glare colours. |
| `themes/forest` | `themes/forest.py` | Calm dark green with moss and sage tones. |
| `themes/github_dark` | `themes/github_dark.py` | GitHub Dark: the github.com dark palette with a blue accent. |
| `themes/github_light` | `themes/github_light.py` | GitHub Light: the github.com light palette with a blue accent. |
| `themes/gruvbox` | `themes/gruvbox.py` | Retro dark theme with warm, earthy colours and a yellow accent. |
| `themes/kanagawa` | `themes/kanagawa.py` | Kanagawa: dark theme inspired by Hokusai's Great Wave, with ink and wave tones. |
| `themes/light` | `themes/light.py` | A light editor palette with a blue accent. |
| `themes/monokai` | `themes/monokai.py` | Monokai: the vivid Sublime Text dark theme with a green accent. |
| `themes/nord` | `themes/nord.py` | Arctic, north-bluish dark theme. |
| `themes/one_dark` | `themes/one_dark.py` | One Dark: Atom's classic dark theme with a cyan accent. |
| `themes/rose_pine` | `themes/rose_pine.py` | Rosé Pine: soft dark theme with muted pastels and a rose accent. |
| `themes/rose_pine_dawn` | `themes/rose_pine_dawn.py` | Rosé Pine Dawn: the light Rosé Pine, warm parchment with a pine accent. |
| `themes/solarized_dark` | `themes/solarized_dark.py` | Solarized Dark: Ethan Schoonover's precision dark theme with a blue accent. |
| `themes/solarized_light` | `themes/solarized_light.py` | Solarized Light: Ethan Schoonover's precision light theme with a blue accent. |
| `themes/tokyo_night` | `themes/tokyo_night.py` | Deep blue-violet dark theme inspired by Tokyo city lights. |

### Widgets

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `widgets/agent_monitor` | `widgets/agent_monitor.py` | Live agent tree in the sidebar (status, model, calls, elapsed) and `/agents` to inspect any agent and interrupt a running one. Needs minimal 0.7. |
| `widgets/callouts` | `widgets/callouts.py` | Renders GitHub alert blockquotes (`> [!NOTE]`, `[!WARNING]`, …) as coloured callouts. |
| `widgets/context_gauge` | `widgets/context_gauge.py` | A one-line bar of how full the context window is (the model's real window), with the prompt-cache hit rate; glyphs, thresholds and limits are settings. Needs minimal 0.9. |
| `widgets/diff_panel` | `widgets/diff_panel.py` | Sidebar panel with a compact coloured diff (+n −m per file) of the files the model edited or wrote this turn; `/diff` prints the full unified diff. |
| `widgets/errors_panel` | `widgets/errors_panel.py` | A sidebar panel with the session's last tool and provider errors, repeat counts, and `/errors clear`. |
| `widgets/files_touched` | `widgets/files_touched.py` | Files read, edited and written this session, with added and removed lines. |
| `widgets/git_panel` | `widgets/git_panel.py` | Branch, ahead/behind, staged/unstaged/untracked counts and per-file diff stats, with the project name on top (`show_project`); every part, glyph and style is a setting. Replaces `widgets/project_badge`. Needs minimal 0.9. |
| `widgets/live_activity` | `widgets/live_activity.py` | The tool running now, its elapsed time and the turn's call count. |
| `widgets/logo` | `widgets/logo.py` | A pixel-art M and the minimal wordmark in the welcome header, optionally with a gradient flowing across it (`animate`); text, colours, alignment and shadow are settings. Replaces `widgets/animated_logo`. Needs minimal 0.9. |
| `widgets/model_picker` | `widgets/model_picker.py` | `/model` opens a list of the models your provider really offers; favourites and hidden models are settings. Needs minimal 0.9. |
| `widgets/plan_board` | `widgets/plan_board.py` | A `plan` tool the model keeps updated, shown as a checklist with a progress bar. |
| `widgets/statusline_kit` | `widgets/statusline_kit.py` | Choose which extra status-line segments go on the left and on the right and in what order (session title, turns, token usage, model, folder, git branch) with your own labels, glyphs and styles. Needs minimal 0.9. |
| `widgets/style_pack` | `widgets/style_pack.py` | Coloured gutters, a rounded composer and a compact or cozy density, written as CSS (`register_css`) with a setting for each. Needs minimal 0.9. |
| `widgets/token_sparkline` | `widgets/token_sparkline.py` | Input tokens per request as a sparkline, session totals and an estimated cost in the status line; glyphs, styles, cost format and prices are settings. Needs minimal 0.9. |
| `widgets/tool_timeline` | `widgets/tool_timeline.py` | Each turn's tool calls as coloured marks, and calls per tool as bars. |
| `widgets/transcript_minimap` | `widgets/transcript_minimap.py` | One coloured cell per transcript block; click one to scroll to it. |

## Writing an item

### Layout

An item lives in `<category>/`. Each item is either a single `<name>.py` file or a package folder `<name>/` with an `__init__.py` plus helper modules (relative imports such as `from .helpers import X` work). There is no index: each item carries its own metadata. Only the four category folders hold items; anything else next to them (`README.md`, `LICENSE`, `.github/`) does not.

| Category      | Holds                                                        | Installed into (global, or `./.minimal/extensions/…` per project) |
|---------------|--------------------------------------------------------------|-------------------------------------------------|
| `extensions/` | general extensions (commands, providers, hooks, …)           | `~/.minimal/extensions/`                        |
| `themes/`     | colour themes (`minimal.register_theme`)                     | `~/.minimal/extensions/themes/`                 |
| `tools/`      | tools for the model (`minimal.register_tool`)                | `~/.minimal/extensions/tools/`                  |
| `widgets/`    | interface components, panels and header logos (`minimal.register_widget`, `minimal.register_panel`, `minimal.register_logo`) | `~/.minimal/extensions/widgets/` |

Installing keeps the category folder: `widgets/style_pack.py` becomes `~/.minimal/extensions/widgets/style_pack.py`, id `widgets/style_pack`.

```
widgets/
  context_gauge.py        a single-file item
  my_panel/               a package item
    __init__.py           docstring, __version__, __api__, register(minimal)
    render.py             helper module
```

The category only groups items: any item may register anything. A folder and a file with the same name (`x.py` and `x/`) must not both exist in one category.

### Metadata

- **Name:** the file or folder name. Lowercase letters, digits and `_`, not starting with `_`. Unique within its folder. The extension id is `<name>` in `extensions/`, else `<category>/<name>` (e.g. `widgets/context_gauge`).
- **Description:** the first line of the module docstring (required; `__init__.py` for packages).
- **Version:** a top-level `__version__ = "1.0"` string (required). Bump it on every change so installed copies are offered the update.
- **API:** a top-level `__api__ = "2"` string (required): the [minimal API version](https://github.com/RafaSG13/Minimal/blob/main/docs/extensions.md#api-versions) the item is written for. `"2"` runs on any 2.x, `"2.1"` on 2.1 or a later 2.x. minimal does not load an item without it, or one written for another major version, and `/ext` does not install it.
- **Dependencies:** an optional top-level `__dependencies__ = ["termaid>=0.12"]` listing the third-party packages the item imports. `/ext` offers to install the missing ones, and CI installs them before checking the item.
- **Tags:** an optional top-level `__tags__ = ["git", "ui"]`: keywords that `/ext search` and the model's `ext_search` match besides the name and description. Use only these: `git`, `ui`, `safety`, `context`, `agents`, `provider`, `theme`, `diagnostics`, `workflow` (CI rejects any other).
- The item must define a top-level `register(minimal)` function. Import only from `minimal.api`; everything else in minimal is internal.

A theme needs only `background`, `foreground` and `accent`; minimal derives the other colours:

```python
"""Ocean: deep blue dark theme."""

__version__ = "1.0"
__api__ = "2"


def register(minimal):
    minimal.register_theme("ocean", dark=True, background="#0b1622", foreground="#d0e4f5", accent="#4fc3f7")
```

See minimal's [`extensions/example.py`](https://github.com/RafaSG13/Minimal/blob/main/extensions/example.py) for tools, commands, event hooks and widgets, and its [extension guide](https://github.com/RafaSG13/Minimal/blob/main/docs/extensions.md) for the full API.

### Settings

An item can declare user-tunable settings with defaults:

```python
def register(minimal):
    settings = minimal.declare_settings({"limit": 200_000, "warn": 0.5})
```

Users override them in `settings.json` under `extensions.settings.<id>`:

```json
{ "extensions": { "settings": { "widgets/context_gauge": { "limit": 1000000 } } } }
```

Unknown keys and values of the wrong type are reported on reload and the default is kept.

### Good practice

- **Keep state out of the repository.** Save an item's own files under `minimal.data_dir()` (API 1.1), a private folder per project outside the working tree. A file under the project's `.minimal/` can be committed, so a repository could ship it pre-filled.
- **Clean up.** Stop the threads, timers and subprocesses you start in an `minimal.on_dispose(fn)` callback (API 1.1); otherwise every `/reload` leaks them.
- **Fail clearly.** Errors raised by a tool go back to the model as an error result, so say what went wrong and how to fix it.

## Contributing

Before opening a pull request, validate every item from the repository root:

```
minimal ext check --install-deps .
```

It installs the packages the items declare in `__dependencies__`, loads each item of every category folder without a terminal and prints `ok`, `WARN` (an optional module is missing) or `FAIL` per item; it exits non-zero on any `FAIL`. CI runs the same check on every pull request, with minimal's current `main`, so an item that the next minimal API would break fails here before that minimal is released.

Publishing never pushes to `main`; items are added by merging the pull request. Without push access to this repository, fork it and set `MINIMAL_MARKETPLACE` to your fork's URL before `/ext publish`. `/ext publish` puts the item under the category of the folder it comes from (`~/.minimal/extensions/themes/ocean.py` → `themes/`), else in `extensions/`. When you add an item, add its row to the [catalogue](#catalogue) in the same pull request. By contributing an item you agree to license it under the MIT License below.

## License

Licensed under the [MIT License](LICENSE).
