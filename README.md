# minimal-marketplace

Extensions for [minimal](https://github.com/RafaSG13/Minimal), the terminal coding-agent harness. Requires minimal 0.4 or later.

## Layout

One folder per category. Each item is either a single `<name>.py` file or a package folder `<name>/` with an `__init__.py` plus helper modules (relative imports such as `from .helpers import X` work). There is no index: each item carries its own metadata.

| Folder        | Holds                                                        | Installed into (global, or `./.minimal/extensions/…` per project) |
|---------------|--------------------------------------------------------------|-------------------------------------------------|
| `extensions/` | general extensions (commands, providers, hooks, …)           | `~/.minimal/extensions/`                        |
| `themes/`     | colour themes for the terminal UI (`minimal.register_theme`) | `~/.minimal/extensions/themes/`                 |
| `tools/`      | tools for the model (`minimal.register_tool`)                | `~/.minimal/extensions/tools/`                  |
| `widgets/`    | terminal UI components and header logos (`minimal.register_widget`, `minimal.register_logo`) | `~/.minimal/extensions/widgets/` |

```
widgets/
  context_gauge.py        a single-file item
  my_panel/               a package item
    __init__.py           docstring, __version__, register(minimal)
    render.py             helper module
```

The category only groups items: any item may register anything. A folder and a file with the same name (`x.py` and `x/`) must not both exist in one category.

- **Name:** the file or folder name. Lowercase letters, digits and `_`, not starting with `_`. Unique within its folder. The extension id is `<name>` in `extensions/`, else `<category>/<name>` (e.g. `widgets/context_gauge`).
- **Description:** the first line of the module docstring (required; `__init__.py` for packages).
- **Version:** a top-level `__version__ = "1.0"` string (required). Bump it on every change so installed copies are offered the update.
- **API:** a top-level `__api__ = "1"` string (required): the [minimal API version](https://github.com/RafaSG13/Minimal/blob/main/docs/extensions.md#api-versions) the item is written for. `"1"` runs on any 1.x, `"1.2"` on 1.2 or a later 1.x. minimal does not load an item without it, or one written for another major version, and `/ext` does not install it.
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

## Use

Install minimal with `uv tool install mnml-agent`, then:

```
/ext                         pick a marketplace and a category, then tick items to install, update or remove
/ext list                    installed items, by scope and category
/ext publish <path> [name]   propose a file or package folder: pushes a publish/<name>-<timestamp> branch and opens a pull request
/theme [name]                switch to an installed theme
```

`/ext publish` puts the item in the category of the folder it comes from (`~/.minimal/extensions/themes/ocean.py` → `themes/`), else in `extensions/`. Publishing never pushes to `main`; items are added by merging the pull request. Without push access to this repository, fork it and set `MINIMAL_MARKETPLACE` to your fork's URL before publishing.

## Contributing

Before opening a pull request, validate every item from the repository root:

```
minimal ext check .
```

It prints `ok`, `WARN` (an optional dependency is missing, e.g. `needs termaid`) or `FAIL` per item and exits non-zero on any `FAIL`. CI runs the same check on every pull request, with minimal's current `main`, so an item that the next minimal API would break fails here before that minimal is released.

If your item imports a third-party package (like `mermaid` and `termaid`), declare it in the item: `__dependencies__ = ["termaid>=0.12"]`. `/ext` offers to install it, and CI runs `minimal ext check --install-deps`, so the item is really loaded and validated.
