# minimal-marketplace

Extensions for [minimal](https://github.com/RafaSG13/Minimal), the terminal coding-agent harness.

## Layout

One folder per category, one `<name>.py` file per item. There is no index: each file carries its own metadata.

| Folder        | Holds                                                        | Installed into (global, or `./.minimal/extensions/…` per project) |
|---------------|--------------------------------------------------------------|-------------------------------------------------|
| `extensions/` | general extensions (commands, providers, hooks, …)           | `~/.minimal/extensions/`                        |
| `themes/`     | colour themes for the terminal UI (`minimal.register_theme`) | `~/.minimal/extensions/themes/`                 |
| `tools/`      | tools for the model (`minimal.register_tool`)                | `~/.minimal/extensions/tools/`                  |
| `widgets/`    | terminal UI components and header logos (`minimal.register_widget`, `minimal.register_logo`) | `~/.minimal/extensions/widgets/` |

The category only groups files: any file may register anything.

- **Name:** the file name. Lowercase letters, digits and `_`, not starting with `_`. Unique within its folder.
- **Description:** the first line of the module docstring (required).
- **Version:** an optional top-level `__version__ = "1.0"` string.
- The file must define a top-level `register(minimal)` function.

A theme needs only `background`, `foreground` and `accent`; minimal derives the other colours (see `Registry.register_theme`):

```python
"""Ocean: deep blue dark theme."""

__version__ = "1.0"


def register(minimal):
    minimal.register_theme("ocean", dark=True, background="#0b1622", foreground="#d0e4f5", accent="#4fc3f7")
```

## Use

```
/ext                         pick a marketplace and a category, then tick items to install, update or remove
/ext list                    installed items, by scope and category
/ext publish <path> [name]   propose a file: pushes a publish/<name>-<timestamp> branch and opens a pull request
/theme [name]                switch to an installed theme
```

`/ext publish` puts the file in the category of the folder it comes from (`~/.minimal/extensions/themes/ocean.py` → `themes/`), else in `extensions/`. Publishing never pushes to `main`; items are added by merging the pull request. Without push access to this repository, fork it and set `MINIMAL_MARKETPLACE` to your fork's URL before publishing.
