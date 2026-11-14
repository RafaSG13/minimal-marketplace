# minimal-marketplace

<p>
  <a href="https://github.com/RafaSG13/minimal-marketplace/actions/workflows/check.yml"><img src="https://img.shields.io/github/actions/workflow/status/RafaSG13/minimal-marketplace/check.yml?branch=main&label=check" alt="Check status"></a>
  <a href="https://pypi.org/project/mnml-agent/"><img src="https://img.shields.io/pypi/v/mnml-agent?label=minimal&color=6f86f4" alt="minimal on PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ea44f" alt="MIT License"></a>
</p>

Extensions, tools, widgets and themes for [minimal](https://github.com/RafaSG13/Minimal), the terminal coding-agent harness, and the rich terminal UIs that run it. This is minimal's default marketplace: `/ext` lists it out of the box.

Requires minimal 0.5 or later (extension API 2). Until 0.5 is on PyPI, `uv tool install mnml-agent` gets 0.4.0, which cannot read this layout: install minimal from git as shown under [Use](#use). An item written for a newer API than your minimal provides is not offered as is: `/ext` installs the newest older version of it that your minimal can run.

## Layout

One top-level folder per frontend, each with the item categories inside:

```
console/<category>/     items for the plain console (extensions and tools)
textual/<category>/     items for the Textual UI, plus the package: minimal-textual
go/<category>/          items for the Go UI, plus the program: minimal-go
```

`<category>` is `extensions`, `themes`, `tools` or `widgets`. minimal itself ships only the console and a UI-less server (`minimal serve`); each rich UI lives here and is a frontend of its own. An item that suits several frontends is **copied** into each folder; the copies may diverge later. `/ext` shows only the folder of the frontend you are running, and installs into that frontend's own install folder (`~/.minimal/extensions/<folder>/`), so a frontend never loads another one's items.

## Frontends

You always run `minimal`. It starts whichever frontend is installed:

| Frontend (`ui`) | Folder | What it is | Install |
| --------------- | ------ | ---------- | ------- |
| `console` | [`console`](console) | minimal's built-in line-by-line frontend; nothing to install. | (built in) |
| `tui` | [`textual`](textual) | The Textual terminal UI (`minimal-textual`): runs inside minimal. | `uv tool install "mnml-agent @ git+https://github.com/RafaSG13/Minimal" --with "minimal-textual @ git+https://github.com/RafaSG13/minimal-marketplace#subdirectory=textual"` (from git until minimal 0.5 is on PyPI) |
| `go` | [`go`](go) | A terminal UI in Go with Bubble Tea, Bubbles, Lip Gloss and Glamour (`minimal-go`). minimal starts it, and it starts `minimal serve --ui go` and talks to it in JSON lines. Needs Go 1.26 or later. | `go install github.com/RafaSG13/minimal-marketplace/go/cmd/minimal-go@latest` |

minimal finds Textual through its `minimal.frontends` entry point and Go as a `minimal-go` binary on your `PATH`. With only the console, minimal runs it. With exactly one more frontend installed, minimal runs that one. With several, the first start asks which one (an arrow-key picker) and saves your choice as `ui` in `~/.minimal/settings.json`; change it later with that setting, or for one run with `minimal --ui console|tui|go`. Running `minimal-go` directly still works (it always passes `--ui go`), but `minimal` is the one command; see [its README](go/README.md) for the keys and `MINIMAL_BIN`.

### Items in the Go UI

The Go UI has no Python inside: extensions run in the `minimal serve --ui go` process it starts, and it draws what they send. So an item for the Go UI is built on `register_panel` (sidebar, top and bottom panels), `register_status` (status-line segments) or `register_renderer` (code fences, alerts, tool calls). Textual widgets, themes and the header logo do not show in the Go UI, so `go/` has no themes and no `logo`; `command_list` and `session_outline` stand in for `command_menu` and `transcript_minimap`. `minimal serve` loads no item that sets `__frontend__` other than its own.

## Use

Install minimal and the Textual UI (until 0.5 is on PyPI, from git; leave out `--with` for the console only):

```bash
uv tool install "mnml-agent @ git+https://github.com/RafaSG13/Minimal" \
  --with "minimal-textual @ git+https://github.com/RafaSG13/minimal-marketplace#subdirectory=textual"
```

Add the Go UI from the table above if you want it, then run `minimal` and, inside it:

```
/ext                         pick a marketplace and a category, then tick items to install, update or remove
/ext list                    installed items, by scope and category
/ext publish <path> [name]   propose a file or package folder: pushes a publish/<name>-<timestamp> branch and opens a pull request
/theme [name]                switch to an installed theme
```

Each item can go into your global folder (`~/.minimal/extensions/<folder>/`, every project) or the current project's (`./.minimal/extensions/<folder>/`, loaded after `/trust`), where `<folder>` is the running frontend's (`console`, `textual` or `go`). Before installing globally, minimal shows a static scan of what the code can do and asks. If an item declares third-party packages, `/ext` offers to install them into minimal's Python.

## Catalogue

Every item sits in the folder of each frontend it suits. The paths below are the marketplace folders.

### Console (`console/`)

The plain console draws no panels or widgets: only extensions and tools.

#### Extensions

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `compact` | `console/extensions/compact.py` | Summarises the history into a new session when the context reaches a threshold, also in the middle of a long turn; adds `/compact`. |
| `crystallize` | `console/extensions/crystallize.py` | Turns commands the model runs again and again into tools, and the calls you deny into `AGENTS.md` rules (`/crystallize`). |
| `ledger` | `console/extensions/ledger.py` | A sidebar panel of the heaviest tool results in the context, flagging stale reads; `/prune` drops the ones you pick and continues in a new session. |
| `lenses` | `console/extensions/lenses.py` | Shortens long `bash` output (passing Python test lines, repeated lines, head and tail) and keeps the full text in `.minimal/outputs/`. |
| `loose_ends` | `console/extensions/loose_ends.py` | A `note` tool and backlog for what the model could not verify, noticed or left to do; `/ends` reviews it. |
| `retry` | `console/extensions/retry.py` | Retries requests that fail with rate limits, overloads or network errors, with backoff, and can switch to a fallback provider. |
| `scope_fence` | `console/extensions/scope_fence.py` | Blocks edits outside the paths you declare, or over a diff budget (`/fence`). |
| `tripwire` | `console/extensions/tripwire.py` | Re-runs your invariant commands after file changes and tells the model which call broke them (`/tripwire`). |

#### Tools

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `tools/subagent` | `console/tools/subagent.py` | Delegates a task to a fresh agent loop with its own history. |
| `tools/web_search` | `console/tools/web_search.py` | Web search through the Brave Search API. Needs `BRAVE_API_KEY`. |

### Textual (`textual/`)

Everything the Textual UI can show. `animated_logo`, `command_menu`, `model_picker`, `style_pack` and `transcript_minimap` exist only here (`__frontend__ = "textual"`).

#### Extensions

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `compact` | `textual/extensions/compact.py` | Summarises the history into a new session when the context reaches a threshold, also in the middle of a long turn; adds `/compact`. |
| `crystallize` | `textual/extensions/crystallize.py` | Turns commands the model runs again and again into tools, and the calls you deny into `AGENTS.md` rules (`/crystallize`). |
| `ledger` | `textual/extensions/ledger.py` | A sidebar panel of the heaviest tool results in the context, flagging stale reads; `/prune` drops the ones you pick and continues in a new session. |
| `lenses` | `textual/extensions/lenses.py` | Shortens long `bash` output (passing Python test lines, repeated lines, head and tail) and keeps the full text in `.minimal/outputs/`. |
| `loose_ends` | `textual/extensions/loose_ends.py` | A `note` tool and backlog for what the model could not verify, noticed or left to do; `/ends` reviews it. |
| `mermaid` | `textual/extensions/mermaid.py` | Draws `mermaid` code blocks in replies as diagrams. Needs `termaid` (offered on install). |
| `retry` | `textual/extensions/retry.py` | Retries requests that fail with rate limits, overloads or network errors, with backoff, and can switch to a fallback provider. |
| `scope_fence` | `textual/extensions/scope_fence.py` | Blocks edits outside the paths you declare, or over a diff budget (`/fence`). |
| `tripwire` | `textual/extensions/tripwire.py` | Re-runs your invariant commands after file changes and tells the model which call broke them (`/tripwire`). |

#### Tools

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `tools/subagent` | `textual/tools/subagent.py` | Delegates a task to a fresh agent loop with its own history. |
| `tools/web_search` | `textual/tools/web_search.py` | Web search through the Brave Search API. Needs `BRAVE_API_KEY`. |

#### Themes

`amber`, `catppuccin` (Mocha), `catppuccin_latte`, `cyberpunk`, `dark`, `dracula`, `forest`, `gruvbox`, `light`, `nord` and `tokyo_night`, in `textual/themes/`. Install them from `/ext` → Themes and switch with `/theme`.

#### Widgets

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `widgets/animated_logo` | `textual/widgets/animated_logo.py` | The pixel-art logo with a gradient flowing across it (replaces `widgets/logo`: install one or the other). |
| `widgets/callouts` | `textual/widgets/callouts.py` | Renders GitHub alert blockquotes (`> [!NOTE]`, `[!WARNING]`, …) as coloured callouts. |
| `widgets/command_list` | `textual/widgets/command_list.py` | Every slash command, built-in and from extensions, packed into the sidebar (a stand-in for `command_menu` in the Go UI). |
| `widgets/command_menu` | `textual/widgets/command_menu.py` | Type `/` to get every command, narrowed as you type and driven with the arrow keys. |
| `widgets/context_gauge` | `textual/widgets/context_gauge.py` | A one-line bar of how full the context window is, with the prompt-cache hit rate. |
| `widgets/files_touched` | `textual/widgets/files_touched.py` | Files read, edited and written this session, with added and removed lines. |
| `widgets/git_panel` | `textual/widgets/git_panel.py` | Branch, ahead/behind, staged/unstaged/untracked counts and per-file diff stats. |
| `widgets/go_check` | `textual/widgets/go_check.py` | `go vet ./...` of the Go module you are in, with the first diagnostics; reruns after the model edits Go files. |
| `widgets/go_module` | `textual/widgets/go_module.py` | The `go.mod` module path and Go version on the status line, hidden outside Go modules. |
| `widgets/live_activity` | `textual/widgets/live_activity.py` | The tool running now, its elapsed time and the turn's call count. |
| `widgets/logo` | `textual/widgets/logo.py` | A pixel-art M and the minimal wordmark in the welcome header. |
| `widgets/model_picker` | `textual/widgets/model_picker.py` | `/model` opens a list of the models your provider really offers. |
| `widgets/plan_board` | `textual/widgets/plan_board.py` | A `plan` tool the model keeps updated, shown as a checklist with a progress bar. |
| `widgets/session_outline` | `textual/widgets/session_outline.py` | Your prompts in this session, numbered, one line each (a stand-in for `transcript_minimap` in the Go UI). |
| `widgets/style_pack` | `textual/widgets/style_pack.py` | Coloured gutters, a rounded composer and a compact or cozy density. |
| `widgets/token_sparkline` | `textual/widgets/token_sparkline.py` | Input tokens per request as a sparkline, session totals and an estimated cost. |
| `widgets/tool_timeline` | `textual/widgets/tool_timeline.py` | Each turn's tool calls as coloured marks, and calls per tool as bars. |
| `widgets/transcript_minimap` | `textual/widgets/transcript_minimap.py` | One coloured cell per transcript block; click one to scroll to it. |

### Go (`go/`)

What the Go UI can draw: no themes and no logo.

#### Extensions

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `compact` | `go/extensions/compact.py` | Summarises the history into a new session when the context reaches a threshold, also in the middle of a long turn; adds `/compact`. |
| `crystallize` | `go/extensions/crystallize.py` | Turns commands the model runs again and again into tools, and the calls you deny into `AGENTS.md` rules (`/crystallize`). |
| `ledger` | `go/extensions/ledger.py` | A sidebar panel of the heaviest tool results in the context, flagging stale reads; `/prune` drops the ones you pick and continues in a new session. |
| `lenses` | `go/extensions/lenses.py` | Shortens long `bash` output (passing Python test lines, repeated lines, head and tail) and keeps the full text in `.minimal/outputs/`. |
| `loose_ends` | `go/extensions/loose_ends.py` | A `note` tool and backlog for what the model could not verify, noticed or left to do; `/ends` reviews it. |
| `mermaid` | `go/extensions/mermaid.py` | Draws `mermaid` code blocks in replies as diagrams. Needs `termaid` (offered on install). |
| `retry` | `go/extensions/retry.py` | Retries requests that fail with rate limits, overloads or network errors, with backoff, and can switch to a fallback provider. |
| `scope_fence` | `go/extensions/scope_fence.py` | Blocks edits outside the paths you declare, or over a diff budget (`/fence`). |
| `tripwire` | `go/extensions/tripwire.py` | Re-runs your invariant commands after file changes and tells the model which call broke them (`/tripwire`). |

#### Tools

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `tools/subagent` | `go/tools/subagent.py` | Delegates a task to a fresh agent loop with its own history. |
| `tools/web_search` | `go/tools/web_search.py` | Web search through the Brave Search API. Needs `BRAVE_API_KEY`. |

#### Widgets

| Item | Path | What it does |
| ---- | ---- | ------------ |
| `widgets/callouts` | `go/widgets/callouts.py` | Renders GitHub alert blockquotes (`> [!NOTE]`, `[!WARNING]`, …) as coloured callouts. |
| `widgets/command_list` | `go/widgets/command_list.py` | Every slash command, built-in and from extensions, packed into the sidebar (a stand-in for `command_menu` in the Go UI). |
| `widgets/context_gauge` | `go/widgets/context_gauge.py` | A one-line bar of how full the context window is, with the prompt-cache hit rate. |
| `widgets/files_touched` | `go/widgets/files_touched.py` | Files read, edited and written this session, with added and removed lines. |
| `widgets/git_panel` | `go/widgets/git_panel.py` | Branch, ahead/behind, staged/unstaged/untracked counts and per-file diff stats. |
| `widgets/go_check` | `go/widgets/go_check.py` | `go vet ./...` of the Go module you are in, with the first diagnostics; reruns after the model edits Go files. |
| `widgets/go_module` | `go/widgets/go_module.py` | The `go.mod` module path and Go version on the status line, hidden outside Go modules. |
| `widgets/live_activity` | `go/widgets/live_activity.py` | The tool running now, its elapsed time and the turn's call count. |
| `widgets/plan_board` | `go/widgets/plan_board.py` | A `plan` tool the model keeps updated, shown as a checklist with a progress bar. |
| `widgets/session_outline` | `go/widgets/session_outline.py` | Your prompts in this session, numbered, one line each (a stand-in for `transcript_minimap` in the Go UI). |
| `widgets/token_sparkline` | `go/widgets/token_sparkline.py` | Input tokens per request as a sparkline, session totals and an estimated cost. |
| `widgets/tool_timeline` | `go/widgets/tool_timeline.py` | Each turn's tool calls as coloured marks, and calls per tool as bars. |

## Writing an item

### Layout

An item lives in `<frontend>/<category>/`, where `<frontend>` is the folder of a frontend it runs under: `console/`, `textual/` or `go/`. An item that suits several frontends gets one **copy** per folder, and the copies may diverge later: bump `__version__` in each copy you change. Each item is either a single `<name>.py` file or a package folder `<name>/` with an `__init__.py` plus helper modules (relative imports such as `from .helpers import X` work). There is no index: each item carries its own metadata. A top-level folder counts as a frontend folder when it holds at least one category folder; the other files and folders next to them (`textual/src/`, `textual/tests/`, `go/cmd/`, `pyproject.toml`, `go.mod`, …) are not items.

| Category      | Holds                                                        | Installed into (global, or `./.minimal/extensions/<folder>/…` per project) |
|---------------|--------------------------------------------------------------|-------------------------------------------------|
| `extensions/` | general extensions (commands, providers, hooks, …)           | `~/.minimal/extensions/<folder>/`               |
| `themes/`     | colour themes (`minimal.register_theme`)                     | `~/.minimal/extensions/<folder>/themes/`        |
| `tools/`      | tools for the model (`minimal.register_tool`)                | `~/.minimal/extensions/<folder>/tools/`         |
| `widgets/`    | interface components, panels and header logos (`minimal.register_widget`, `minimal.register_panel`, `minimal.register_logo`) | `~/.minimal/extensions/<folder>/widgets/` |

Installing keeps the frontend folder: `textual/widgets/style_pack.py` becomes `~/.minimal/extensions/textual/widgets/style_pack.py`, id `widgets/style_pack`. Only the running frontend's install folder loads.

```
textual/widgets/
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
- **Frontend:** an optional top-level `__frontend__ = "textual"` for an item that imports `textual` or `rich` (say, a widget built with `register_widget`). It loads only in the Textual UI, and an item that sets `__frontend__ = X` must live in the folder `X/` (`textual/widgets/`): `minimal ext check` fails it anywhere else. To only show text, use `minimal.register_panel` or `minimal.register_renderer` (API 1.3) instead: they work in every frontend, so they need no `__frontend__` and can be copied into `console/`, `textual/` and `go/`.
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

It installs the packages the items declare in `__dependencies__`, loads each item of every frontend folder without a terminal and prints `ok`, `WARN` (an optional module is missing) or `FAIL` per item; it exits non-zero on any `FAIL`. An item that imports `textual` or `rich` without `__frontend__ = "textual"` fails too, and so does one whose `__frontend__` names another folder than the one it is in. CI runs the same check on every pull request, with minimal's current `main` (and Textual, which the textual items import), so an item that the next minimal API would break fails here before that minimal is released. The frontends have their own checks: `go vet` and `go test` for `go/`, the unit tests for `textual/`.

Publishing never pushes to `main`; items are added by merging the pull request. Without push access to this repository, fork it and set `MINIMAL_MARKETPLACE` to your fork's URL before `/ext publish`. `/ext publish` puts the item under `<folder>/<category>/` of the frontend you are running (`~/.minimal/extensions/textual/themes/ocean.py` → `textual/themes/`), else in `extensions/`. To offer an item to another frontend, publish it again from that frontend, or copy it by hand. When you add an item, add its row to the [catalogue](#catalogue) in the same pull request. By contributing an item you agree to license it under the MIT License below.

## License

Licensed under the [MIT License](LICENSE).
