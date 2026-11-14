# minimal-textual

The Textual terminal UI for [minimal](https://github.com/RafaSG13/Minimal): transcript, prompt, panels, widgets, themes and dialogs. It registers the `tui` frontend through the `minimal.frontends` entry point, and minimal runs it by default once installed (`minimal --ui tui`, or `ui` in settings).

## Install

Add it to a minimal installed as a tool:

```
uv tool install mnml-agent --with "minimal-textual @ git+https://github.com/RafaSG13/minimal-marketplace#subdirectory=frontends/textual"
```

From a checkout of this repository:

```
uv tool install mnml-agent --with ./frontends/textual
```

Without it minimal runs the plain console frontend (`minimal --ui console`).

## Widgets

`widgets/` holds the widgets written for this frontend (`__frontend__ = "textual"`); install them with `/ext`. The package itself exports `logo_content(spec)`, which turns a `LogoSpec` into Textual content, for widgets that draw a logo.

## Tests

From this folder, against a checkout of minimal next to this repository:

```
uv run --no-project --with-editable ../../../minimal --with-editable . python -m unittest discover -s tests
```
