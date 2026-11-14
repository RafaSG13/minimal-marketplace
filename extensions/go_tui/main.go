// Command go_tui is minimal's terminal UI built with Bubble Tea, Bubbles and Lip Gloss.
//
// minimal (the Python bridge in __init__.py) starts it with pipes: it reads minimal's events as JSON lines on
// stdin and writes the user's actions as JSON lines on stdout. The interface itself is drawn on the controlling
// terminal, which it opens by itself.
package main

import (
	"fmt"
	"os"

	tea "charm.land/bubbletea/v2"
)

func main() {
	in, out, err := openTerminal()
	if err != nil {
		fmt.Fprintln(os.Stderr, "minimal go frontend: needs a terminal:", err)
		os.Exit(1)
	}
	defer in.Close()
	if out != in {
		defer out.Close()
	}

	c := &conn{out: os.Stdout}
	m := newModel(c)
	program = tea.NewProgram(m, tea.WithInput(in), tea.WithOutput(out))
	go func() {
		readMessages(os.Stdin, func(msg Message) { program.Send(msg) })
		program.Send(tea.QuitMsg{}) // minimal closed the pipe: it is gone
	}()
	if _, err := program.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "minimal go frontend:", err)
		os.Exit(1)
	}
	if m.fatal != "" {
		fmt.Fprintln(os.Stderr, "minimal go frontend:", m.fatal)
		os.Exit(1)
	}
}
