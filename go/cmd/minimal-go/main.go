// Command minimal-go is a terminal UI for minimal built with Bubble Tea, Bubbles, Lip Gloss and Glamour.
//
// It owns the terminal and starts `minimal serve --ui go` as a child: the server's events arrive as JSON lines on the
// child's stdout, and the user's actions go to its stdin. Every argument is passed on to `minimal serve`; the
// MINIMAL_BIN environment variable names the minimal executable (default: minimal, found on PATH). Users normally
// run `minimal`, which starts this program when Go is the frontend they chose.
package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"slices"

	tea "charm.land/bubbletea/v2"
	"github.com/charmbracelet/x/term"
)

func main() {
	os.Exit(run(os.Args[1:]))
}

// minimalBin is the minimal executable to run.
func minimalBin() string {
	if bin := os.Getenv("MINIMAL_BIN"); bin != "" {
		return bin
	}
	return "minimal"
}

// run starts `minimal serve --ui go` with args and shows its session; the result is the exit status.
func run(args []string) int {
	bin := minimalBin()
	if slices.Contains(args, "-h") || slices.Contains(args, "--help") {
		return help(bin)
	}
	if !term.IsTerminal(os.Stdin.Fd()) || !term.IsTerminal(os.Stdout.Fd()) {
		fmt.Fprintln(os.Stderr, "minimal-go: needs a terminal on stdin and stdout")
		return 1
	}

	srv, err := startServer(bin, args)
	if err != nil {
		fmt.Fprintf(os.Stderr, "minimal-go: cannot run %s serve: %v\nInstall minimal, or set MINIMAL_BIN to its path.\n", bin, err)
		return 1
	}
	m := newModel(srv.conn)
	program = tea.NewProgram(m)
	srv.listen()

	_, runErr := program.Run()
	code := srv.stop()
	srv.close(code)

	switch {
	case m.fatal != "":
		fmt.Fprintln(os.Stderr, "minimal-go:", m.fatal)
		return 1
	case errors.Is(runErr, tea.ErrInterrupted):
		return 130
	case runErr != nil:
		fmt.Fprintln(os.Stderr, "minimal-go:", runErr)
		return 1
	}
	return code
}

// help prints this program's usage and then the server's own (`minimal serve --help`).
func help(bin string) int {
	fmt.Fprintf(os.Stderr, "Usage: minimal-go [minimal serve arguments]\n\nRuns `%s serve --ui go` (set MINIMAL_BIN to change the executable) and shows it in a terminal UI.\nYou normally start it by running `minimal` with the Go frontend chosen.\nThe server's own help follows.\n\n", bin)
	cmd := exec.Command(bin, "serve", "--ui", "go", "--help")
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		var exit *exec.ExitError
		if errors.As(err, &exit) {
			return exit.ExitCode()
		}
		fmt.Fprintf(os.Stderr, "minimal-go: cannot run %s: %v\n", bin, err)
		return 1
	}
	return 0
}
