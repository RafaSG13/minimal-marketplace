# minimal-marketplace

Extensions for [minimal](https://github.com/RafaSG13/Minimal), the terminal coding-agent harness.

## Layout

`extensions/<name>.py`, one file per extension. There is no index: each file carries its own metadata.

- **Name:** the file name. Lowercase letters, digits and `_`, not starting with `_`.
- **Description:** the first line of the module docstring (required).
- **Version:** an optional top-level `__version__ = "1.0"` string.
- The file must define a top-level `register(pi)` function.

## Use

```
/ext search [words]               search the marketplace
/ext install <name> [--project]   install into ~/.minimal/extensions (or ./.minimal/extensions)
/ext uninstall <name> [--project] remove it
/ext publish <path> [name]        propose an extension: pushes a publish/<name>-<timestamp> branch and opens a pull request
```

Publishing never pushes to `main`; extensions are added by merging the pull request. Without push access to this repository, fork it and set `MINIMAL_MARKETPLACE` to your fork's URL before publishing.
