package main

import (
	"fmt"
	"strings"

	"charm.land/bubbles/v2/textinput"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
)

// modal is a question that takes over the keyboard until it is answered.
type modal interface {
	// update handles a key. done says the question is answered, with value (nil: cancelled) as the answer.
	update(msg tea.KeyPressMsg) (done bool, value any)
	// view draws it for width columns.
	view(width int) string
}

func newModal(m Message) modal {
	switch m.T {
	case "ask":
		return &confirm{question: m.Question}
	case "choose":
		return &list{title: m.Title, options: m.Options}
	case "choose_many":
		l := &list{title: m.Title, options: m.Options, many: true}
		l.ticked = make([]bool, len(m.Options))
		for i, o := range m.Options {
			l.ticked[i] = o.Checked
		}
		return l
	default: // ask_text
		input := textinput.New()
		input.Prompt = "❯ "
		input.SetVirtualCursor(true)
		input.Focus()
		return &text{title: m.Title, input: input}
	}
}

var panel = lipgloss.NewStyle().
	BorderStyle(lipgloss.RoundedBorder()).
	BorderForeground(lipgloss.Color("75")).
	Padding(0, 1)

// confirm asks a yes/no question.
type confirm struct{ question string }

func (c *confirm) update(msg tea.KeyPressMsg) (bool, any) {
	switch msg.String() {
	case "y", "Y", "enter":
		return true, true
	case "n", "N", "esc", "ctrl+c":
		return true, false
	}
	return false, nil
}

func (c *confirm) view(width int) string {
	body := bold.Render(visible(c.question)) + "\n" + muted.Render("y / enter allow · n / esc deny")
	return panel.Width(width).Render(body)
}

// list picks one option, or ticks any of them.
type list struct {
	title   string
	options []Option
	many    bool
	ticked  []bool
	cursor  int
}

const listRows = 10

func (l *list) update(msg tea.KeyPressMsg) (bool, any) {
	switch msg.String() {
	case "up", "k", "ctrl+p":
		if l.cursor > 0 {
			l.cursor--
		}
	case "down", "j", "ctrl+n":
		if l.cursor < len(l.options)-1 {
			l.cursor++
		}
	case "space", " ":
		if l.many && len(l.options) > 0 {
			l.ticked[l.cursor] = !l.ticked[l.cursor]
		}
	case "enter":
		if l.many {
			values := []string{}
			for i, o := range l.options {
				if l.ticked[i] {
					values = append(values, o.Value)
				}
			}
			return true, values
		}
		if len(l.options) == 0 {
			return true, nil
		}
		return true, l.options[l.cursor].Value
	case "esc", "ctrl+c":
		return true, nil
	}
	return false, nil
}

func (l *list) view(width int) string {
	start := 0
	if l.cursor >= listRows {
		start = l.cursor - listRows + 1
	}
	end := min(start+listRows, len(l.options))
	rows := []string{bold.Render(visible(l.title))}
	for i := start; i < end; i++ {
		pointer, label := "  ", visible(l.options[i].Label)
		if l.many {
			box := "[ ] "
			if l.ticked[i] {
				box = "[x] "
			}
			label = box + label
		}
		if i == l.cursor {
			pointer, label = accent.Render("❯ "), accent.Render(label)
		}
		rows = append(rows, pointer+label)
	}
	if len(l.options) > listRows {
		rows = append(rows, dim.Render(fmt.Sprintf("%d/%d", l.cursor+1, len(l.options))))
	}
	help := "↑/↓ move · enter choose · esc cancel"
	if l.many {
		help = "↑/↓ move · space tick · enter confirm · esc cancel"
	}
	rows = append(rows, muted.Render(help))
	return panel.Width(width).Render(strings.Join(rows, "\n"))
}

// text asks for one line.
type text struct {
	title string
	input textinput.Model
}

func (t *text) update(msg tea.KeyPressMsg) (bool, any) {
	switch msg.String() {
	case "enter":
		return true, t.input.Value()
	case "esc", "ctrl+c":
		return true, nil
	}
	t.input, _ = t.input.Update(msg)
	return false, nil
}

func (t *text) view(width int) string {
	t.input.SetWidth(max(width-6, 10))
	return panel.Width(width).Render(bold.Render(visible(t.title)) + "\n" + t.input.View() + "\n" + muted.Render("enter send · esc cancel"))
}
