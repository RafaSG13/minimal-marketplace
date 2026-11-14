# minimal-textual

The Textual terminal UI for [minimal](https://github.com/RafaSG13/Minimal): transcript, prompt, panels, widgets, themes and dialogs. It registers the `tui` frontend through the `minimal.frontends` entry point, and `minimal` runs it once installed: it is used without asking when it is the only frontend besides the console, else the first start asks and saves the choice as `ui` in `~/.minimal/settings.json` (`minimal --ui tui` picks it for one run).

## Install

Add it to a minimal installed as a tool:

```
uv tool install "mnml-agent @ git+https://github.com/RafaSG13/Minimal" --with "minimal-textual @ git+https://github.com/RafaSG13/minimal-marketplace#subdirectory=textual"
```

From a checkout of this repository:

```
uv tool install mnml-agent --with ./textual
```

Without it minimal runs the plain console frontend (`minimal --ui console`).

## Marketplace items

This folder is also the Textual part of the marketplace: `extensions/`, `tools/`, `themes/` and `widgets/` hold the items for this frontend. Install them with `/ext`; they go into `~/.minimal/extensions/textual/` (a project's: `./.minimal/extensions/textual/`), which only this frontend loads. The widgets that import Textual set `__frontend__ = "textual"`. The package itself exports `logo_content(spec)`, which turns a `LogoSpec` into Textual content, for widgets that draw a logo.

## Tests

From this folder, against a checkout of minimal next to this repository:

```
uv run --no-project --with-editable ../../minimal --with-editable . python -m unittest discover -s tests
```
