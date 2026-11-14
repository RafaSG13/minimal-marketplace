# minimal-go

A terminal UI for [minimal](https://github.com/RafaSG13/Minimal) written in Go with Bubble Tea, Bubbles, Lip Gloss and Glamour. minimal starts it when Go is the frontend you chose, it owns the terminal and starts `minimal serve --ui go` as a child process; the two talk JSON lines over the child's stdin and stdout.

It draws the transcript with Markdown, tool calls, questions, extension panels (`register_panel`), status-line segments (`register_status`) and block renderers (`register_renderer`). Extensions that need Textual (`__frontend__ = "textual"`) are skipped, as under every frontend that is not the Textual one. Items for this frontend are installed with `/ext` into `~/.minimal/extensions/go/` (the project's: `./.minimal/extensions/go/`) from this repository's `go/` folder.

## Install

You need minimal 0.5 or later (the first with `minimal serve`) on your `PATH`, and Go 1.26 or later:

```
uv tool install "mnml-agent @ git+https://github.com/RafaSG13/Minimal"   # from git until minimal 0.5 is on PyPI
go install github.com/RafaSG13/minimal-marketplace/go/cmd/minimal-go@latest
```

`go install` puts `minimal-go` in `$(go env GOBIN)` (default `$(go env GOPATH)/bin`).

## Run

Run `minimal`. When `minimal-go` is on your `PATH` and Go is the frontend you chose (the first-start picker saves it as `ui` in `~/.minimal/settings.json`; `minimal --ui go` picks it for one run), minimal starts it with your arguments.

```
minimal --ui go                  # a new session in the current directory, as Go
minimal-go                       # the same, running the program directly
minimal-go --model <name> ...    # every argument goes to `minimal serve`
minimal-go --help                # minimal serve's own options
```

- `minimal-go` always runs `$MINIMAL_BIN serve --ui go [arguments...]`: `--ui go` tells minimal which frontend it serves, so it loads the extensions installed for Go. `MINIMAL_BIN` names the minimal executable (default: `minimal`, found on `PATH`).
- The server's stderr never reaches the screen: it goes to a log in your cache folder, removed when the session ends well. When the server fails, its last lines and the log's path are printed after the interface closes. Set `MINIMAL_GO_LOG` to a file to keep the log of every session (appended).
- Commands that need the real terminal (`/setup`, `/login`) run on it directly: the interface gives the terminal up meanwhile and takes it back after.
- The exit status is the server's; ctrl+d (or `/exit`) ends the session with 0.

## Keys

| Key | Does |
| --- | ---- |
| `enter` | send the message |
| `esc`, `ctrl+c` | interrupt the running turn; `ctrl+c` also clears the prompt, then quits when it is empty |
| `ctrl+d` | quit (when idle with an empty prompt) |
| `ctrl+o` | expand or collapse tool output |
| `ctrl+b` | hide or show the sidebar |
| `page up`, `page down`, mouse wheel | scroll the transcript |
| `up`, `down` | lines typed before |

## Develop

```
gofmt -l .        # must print nothing
go vet ./...
go test ./...
go build ./cmd/minimal-go
MINIMAL_BIN=/path/to/minimal ./minimal-go   # or put it on PATH and run `minimal`
```

The protocol (version 2) is defined by `minimal serve` and mirrored in `cmd/minimal-go/protocol.go`. The client refuses a server that answers `hello` with another version.
