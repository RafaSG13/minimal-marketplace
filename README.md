# minimal-marketplace

<p>
  <a href="https://github.com/RafaSG13/minimal-marketplace/actions/workflows/check.yml"><img src="https://img.shields.io/github/actions/workflow/status/RafaSG13/minimal-marketplace/check.yml?branch=main&label=check" alt="Check status"></a>
  <a href="https://pypi.org/project/mnml-agent/"><img src="https://img.shields.io/pypi/v/mnml-agent?label=minimal&color=6f86f4" alt="minimal on PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ea44f" alt="MIT License"></a>
</p>

Extensions, tools, widgets and themes for [minimal](https://github.com/RafaSG13/Minimal), the terminal coding-agent harness, and the rich terminal UIs that run it. This is minimal's default marketplace: `/ext` lists it out of the box.

Requires minimal 0.5 or later. An item written for a newer API than your minimal provides is not offered as is: `/ext` installs the newest older version of it that your minimal can run.

## Layout

```
shared/<category>/               items that work under any frontend
frontends/<name>/<category>/     items for one frontend (`__frontend__ = "<name>"`)
frontends/textual/               the Textual UI, a Python package: minimal-textual
frontends/go/                    the Go UI, a standalone program: minimal-go
```

`<category>` is `extensions`, `themes`, `tools` or `widgets`. minimal itself ships only the console and a UI-less server (`minimal serve`); each rich UI lives here and is a frontend of its own.

## Frontends

| Frontend | What it is | Install |
| -------- | ---------- | ------- |
| [`frontends/textual`](frontends/textual) | The Textual terminal UI (`minimal-textual`): registers the `tui` frontend, which minimal runs by default once it is installed. Its `widgets/` hold the items that need Textual. | `uv tool install mnml-agent --with "minimal-textual @ git+https://github.com/RafaSG13/minimal-marketplace#subdirectory=frontends/textual"` |
| [`frontends/go`](frontends/go) | A terminal UI in Go with Bubble Tea, Bubbles, Lip Gloss and Glamour (`minimal-go`). It starts `minimal serve` and talks to it in JSON lines. Needs Go 1.26 or later. | `go install github.com/RafaSG13/minimal-marketplace/frontends/go/cmd/minimal-go@latest` |

Without either, minimal runs its plain console frontend (`minimal --ui console`). Run the Go UI with `minimal-go`; see [its README](frontends/go/README.md) for the keys and `MINIMAL_BIN`.

## Use

Install minimal with `uv tool install mnml-agent`, add a frontend from the table above if you want one, then, inside minimal:

```
/ext                         pick a marketplace and a category, then tick items to install, update or remove
/ext list                    installed items, by scope and category
/ext publish <path> [name]   propose a file or package folder: pushes a publish/<name>-<timestamp> branch and opens a pull request
/theme [name]                switch to an installed theme
```

Each item can go into your global folder (`~/.minimal/extensions/`, every project) or the current project's (`./.minimal/extensions/`, loaded after `/trust`). Before installing globally, minimal shows a static scan of what the code can do and asks. If an item declares third-party packages, `/ext` offers to install them into minimal's Python. `/ext` marks an item that belongs to one frontend (`textual only`).

## Catalogue

### Extensions

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `compact` | `shared/extensions/compact.py` | Summarises the history into a new session when the context reaches a threshold, also in the middle of a long turn; adds `/compact`. |
| `crystallize` | `shared/extensions/crystallize.py` | Turns commands the model runs again and again into tools, and the calls you deny into `AGENTS.md` rules (`/crystallize`). |
| `ledger` | `shared/extensions/ledger.py` | A sidebar panel of the heaviest tool results in the context, flagging stale reads; `/prune` drops the ones you pick and continues in a new session. |
| `lenses` | `shared/extensions/lenses.py` | Shortens long `bash` output (passing Python test lines, repeated lines, head and tail) and keeps the full text in `.minimal/outputs/`. |
| `loose_ends` | `shared/extensions/loose_ends.py` | A `note` tool and backlog for what the model could not verify, noticed or left to do; `/ends` reviews it. |
| `mermaid` | `shared/extensions/mermaid.py` | Draws `mermaid` code blocks in replies as diagrams. Needs `termaid` (offered on install). |
| `retry` | `shared/extensions/retry.py` | Retries requests that fail with rate limits, overloads or network errors, with backoff, and can switch to a fallback provider. |
| `scope_fence` | `shared/extensions/scope_fence.py` | Blocks edits outside the paths you declare, or over a diff budget (`/fence`). |
| `tripwire` | `shared/extensions/tripwire.py` | Re-runs your invariant commands after file changes and tells the model which call broke them (`/tripwire`). |

### Tools

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `tools/subagent` | `shared/tools/subagent.py` | Delegates a task to a fresh agent loop with its own history. |
| `tools/web_search` | `shared/tools/web_search.py` | Web search through the Brave Search API. Needs `BRAVE_API_KEY`. |

### Widgets

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `widgets/callouts` | `shared/widgets/callouts.py` | Renders GitHub alert blockquotes (`> [!NOTE]`, `[!WARNING]`, …) as coloured callouts. |
| `widgets/context_gauge` | `shared/widgets/context_gauge.py` | A one-line bar of how full the context window is, with the prompt-cache hit rate. |
| `widgets/files_touched` | `shared/widgets/files_touched.py` | Files read, edited and written this session, with added and removed lines. |
| `widgets/git_panel` | `shared/widgets/git_panel.py` | Branch, ahead/behind, staged/unstaged/untracked counts and per-file diff stats. |
| `widgets/live_activity` | `shared/widgets/live_activity.py` | The tool running now, its elapsed time and the turn's call count. |
| `widgets/logo` | `shared/widgets/logo.py` | A pixel-art M and the minimal wordmark in the welcome header. |
| `widgets/plan_board` | `shared/widgets/plan_board.py` | A `plan` tool the model keeps updated, shown as a checklist with a progress bar. |
| `widgets/token_sparkline` | `shared/widgets/token_sparkline.py` | Input tokens per request as a sparkline, session totals and an estimated cost. |
| `widgets/tool_timeline` | `shared/widgets/tool_timeline.py` | Each turn's tool calls as coloured marks, and calls per tool as bars. |

### Textual widgets

For the Textual frontend only (`textual only` in `/ext`).

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `widgets/animated_logo` | `frontends/textual/widgets/animated_logo.py` | The pixel-art logo with a gradient flowing across it (replaces `widgets/logo`: install one or the other). |
| `widgets/command_menu` | `frontends/textual/widgets/command_menu.py` | Type `/` to get every command, narrowed as you type and driven with the arrow keys. |
| `widgets/model_picker` | `frontends/textual/widgets/model_picker.py` | `/model` opens a list of the models your provider really offers. |
| `widgets/style_pack` | `frontends/textual/widgets/style_pack.py` | Coloured gutters, a rounded composer and a compact or cozy density. |
| `widgets/transcript_minimap` | `frontends/textual/widgets/transcript_minimap.py` | One coloured cell per transcript block; click one to scroll to it. |

### Themes

`amber`, `catppuccin` (Mocha), `catppuccin_latte`, `cyberpunk`, `dark`, `dracula`, `forest`, `gruvbox`, `light`, `nord` and `tokyo_night`, all in `shared/themes/`. Install them from `/ext` → Themes and switch with `/theme`.

## Writing an item

### Layout

An item lives in `shared/<category>/` when it works under every frontend, or in `frontends/<name>/<category>/` when it needs one (`frontends/textual/widgets/`). Each item is either a single `<name>.py` file or a package folder `<name>/` with an `__init__.py` plus helper modules (relative imports such as `from .helpers import X` work). There is no index: each item carries its own metadata. The other folders of `frontends/<name>/` (`src/`, `tests/`, the Go program) are not items.

| Category      | Holds                                                        | Installed into (global, or `./.minimal/extensions/…` per project) |
|---------------|--------------------------------------------------------------|-------------------------------------------------|
| `extensions/` | general extensions (commands, providers, hooks, …)           | `~/.minimal/extensions/`                        |
| `themes/`     | colour themes (`minimal.register_theme`)                     | `~/.minimal/extensions/themes/`                 |
| `tools/`      | tools for the model (`minimal.register_tool`)                | `~/.minimal/extensions/tools/`                  |
| `widgets/`    | interface components, panels and header logos (`minimal.register_widget`, `minimal.register_panel`, `minimal.register_logo`) | `~/.minimal/extensions/widgets/` |

Installing flattens the frontend away: `frontends/textual/widgets/style_pack.py` becomes `~/.minimal/extensions/widgets/style_pack.py`, id `widgets/style_pack`.

```
shared/widgets/
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
- **API:** a top-level `__api__ = "1"` string (required): the [minimal API version](https://github.com/RafaSG13/Minimal/blob/main/docs/extensions.md#api-versions) the item is written for. `"1"` runs on any 1.x, `"1.1"` on 1.1 or a later 1.x. minimal does not load an item without it, or one written for another major version, and `/ext` does not install it.
- **Dependencies:** an optional top-level `__dependencies__ = ["termaid>=0.12"]` listing the third-party packages the item imports. `/ext` offers to install the missing ones, and CI installs them before checking the item.
- **Frontend:** an optional top-level `__frontend__ = "textual"` for an item that imports `textual` or `rich` (say, a widget built with `register_widget`). Put it in `frontends/textual/<category>/`. It loads only in the Textual UI, is skipped under every other frontend (`--ui console`, `minimal-go`), and `/ext` marks it `textual only`. To only show text, use `minimal.register_panel` or `minimal.register_renderer` (API 1.3) instead: they work in every frontend.
- The item must define a top-level `register(minimal)` function. Import only from `minimal.api`; everything else in minimal is internal.

A theme needs only `background`, `foreground` and `accent`; minimal derives the other colours:

```python
"""Ocean: deep blue dark theme."""

__version__ = "1.0"
__api__ = "1"


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

It installs the packages the items declare in `__dependencies__`, loads each item without a terminal and prints `ok`, `WARN` (an optional module is missing) or `FAIL` per item; it exits non-zero on any `FAIL`. An item that imports `textual` or `rich` without `__frontend__ = "textual"` fails too. CI runs the same check on every pull request, with minimal's current `main` (and Textual, which the textual-only items import), so an item that the next minimal API would break fails here before that minimal is released. The frontends have their own checks: `go vet` and `go test` for `frontends/go`, the unit tests for `frontends/textual`.

Publishing never pushes to `main`; items are added by merging the pull request. Without push access to this repository, fork it and set `MINIMAL_MARKETPLACE` to your fork's URL before `/ext publish`. `/ext publish` puts the item in the category of the folder it comes from (`~/.minimal/extensions/themes/ocean.py` → `themes/`), else in `extensions/`; it goes under `frontends/<frontend>/` if it sets `__frontend__`, else under `shared/`. When you add an item, add its row to the [catalogue](#catalogue) in the same pull request. By contributing an item you agree to license it under the MIT License below.

## License

Licensed under the [MIT License](LICENSE).
