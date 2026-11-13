package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	"charm.land/bubbles/v2/spinner"
	"charm.land/bubbles/v2/textinput"
	"charm.land/bubbles/v2/viewport"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

const (
	sidebarWidth = 36 // columns of the sidebar, border included
	minForSide   = 90 // narrowest terminal that shows a sidebar
)

// program is the running Bubble Tea program; the terminal is released and restored through it.
var program *tea.Program

// model is the whole interface: the transcript, extension panels, the prompt, the status line and any question
// being asked.
type model struct {
	conn *conn

	width, height int
	vp            viewport.Model
	input         textinput.Model
	spin          spinner.Model

	blocks    []*block
	assistant *block            // the reply being streamed
	tools     map[string]*block // running tool calls by id
	expanded  bool              // tool bodies shown in full

	status       Status
	busy         bool
	interrupting bool
	busySince    time.Time

	modal   modal
	modalID string

	history []string
	cursor  int // position in history while browsing it; len(history) is a new line

	// what extensions add
	panels        []PanelData
	left, right   []Line // status line segments
	sidebarHidden bool
	renderers     map[string]bool    // block kinds extensions draw themselves
	rendered      map[string]*[]Line // their drawings by request key (nil: use the default)
	requested     map[string]bool    // requests sent and not answered yet, by key
	requestKeys   map[string]string  // request key by request id
	nextRequest   int

	fatal string // why the interface must stop
}

func newModel(c *conn) *model {
	input := textinput.New()
	input.Prompt = "❯ "
	input.Placeholder = "Message, or / for commands"
	input.SetVirtualCursor(true)
	vp := viewport.New()
	vp.SoftWrap = false
	return &model{
		conn:        c,
		vp:          vp,
		input:       input,
		spin:        spinner.New(spinner.WithSpinner(spinner.MiniDot), spinner.WithStyle(accent)),
		tools:       map[string]*block{},
		renderers:   map[string]bool{},
		rendered:    map[string]*[]Line{},
		requested:   map[string]bool{},
		requestKeys: map[string]string{},
	}
}

func (m *model) Init() tea.Cmd {
	return m.input.Focus()
}

// --- updates ---------------------------------------------------------------

func (m *model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
		m.layout()
		m.refresh()
		return m, nil
	case tea.QuitMsg:
		return m, tea.Quit
	case tea.KeyPressMsg:
		return m.key(msg)
	case tea.MouseWheelMsg:
		var cmd tea.Cmd
		m.vp, cmd = m.vp.Update(msg)
		return m, cmd
	case spinner.TickMsg:
		if !m.busy {
			return m, nil
		}
		var cmd tea.Cmd
		m.spin, cmd = m.spin.Update(msg)
		return m, cmd
	case Message:
		return m.minimal(msg)
	}
	var cmd tea.Cmd
	m.input, cmd = m.input.Update(msg)
	return m, cmd
}

// minimal handles a line from minimal.
func (m *model) minimal(msg Message) (tea.Model, tea.Cmd) {
	switch msg.T {
	case "hello":
		if msg.Protocol != protocol {
			m.fatal = fmt.Sprintf("minimal speaks protocol %d, this terminal UI %d: remove the cached build and update the go_tui extension", msg.Protocol, protocol)
			return m, tea.Quit
		}
		if msg.Status != nil {
			m.status = *msg.Status
		}
		m.setRenderers(msg.Renderers)
		m.add(&block{kind: kindNotice, level: "info", text: fmt.Sprintf("minimal %s · type a message, or /help · ctrl+c interrupts a turn, ctrl+d quits", msg.Version)})
		m.replay(msg)
		m.problems(msg)
	case "text":
		if m.assistant == nil {
			m.assistant = &block{kind: kindAssistant}
			m.blocks = append(m.blocks, m.assistant)
		}
		m.assistant.text += msg.Chunk
		m.assistant.stale = true
	case "tool_call":
		m.endReply()
		if msg.Call != nil {
			b := &block{kind: kindTool, call: msg.Call, body: msg.Body}
			m.tools[msg.Call.ID] = b
			m.blocks = append(m.blocks, b)
		}
	case "tool_result":
		if msg.Call != nil {
			if b := m.tools[msg.Call.ID]; b != nil {
				b.result, b.body, b.stale = msg.Result, msg.Body, true
				delete(m.tools, msg.Call.ID)
			}
		}
	case "turn_end":
		m.endReply()
		m.tools = map[string]*block{}
		if msg.Error != nil {
			m.add(&block{kind: kindNotice, level: "error", text: "Error: " + *msg.Error})
		}
	case "output":
		level := "info"
		if msg.Stderr {
			level = "error"
		}
		if last := m.last(); last != nil && last.kind == kindOutput && last.level == level {
			last.text += msg.Text
			last.stale = true
		} else {
			m.blocks = append(m.blocks, &block{kind: kindOutput, level: level, text: msg.Text})
		}
		m.endReply()
	case "notify":
		m.add(&block{kind: kindNotice, level: msg.Kind, text: msg.Text})
	case "reloaded":
		m.setRenderers(msg.Renderers)
		m.problems(msg)
	case "panels":
		m.panels = msg.Panels
		m.layout()
	case "segments":
		m.left, m.right = msg.Left, msg.Right
	case "rendered":
		if key, ok := m.requestKeys[msg.ID]; ok {
			delete(m.requestKeys, msg.ID)
			delete(m.requested, key)
			m.rendered[key] = msg.Lines
			m.restale()
		}
	case "idle":
		if msg.Status != nil {
			m.status = *msg.Status
		}
		m.busy, m.interrupting = false, false
		m.endReply()
		m.restale() // replies are final now: a fence left open is drawn closed
		m.input.Focus()
	case "ask", "choose", "choose_many", "ask_text":
		m.modal, m.modalID = newModal(msg), msg.ID
		m.layout()
	case "suspend":
		_ = program.ReleaseTerminal()
		m.conn.suspended()
		return m, nil
	case "resume":
		_ = program.RestoreTerminal()
		return m, nil
	case "quit":
		return m, tea.Quit
	}
	m.refresh()
	return m, nil
}

// endReply ends the reply being streamed: what follows is another block.
func (m *model) endReply() {
	if m.assistant != nil {
		m.assistant.stale = true
		m.assistant = nil
	}
}

// setRenderers takes the block kinds extensions draw; what they drew before is forgotten.
func (m *model) setRenderers(kinds []string) {
	m.renderers = map[string]bool{}
	for _, kind := range kinds {
		m.renderers[kind] = true
	}
	m.rendered = map[string]*[]Line{}
	m.requested = map[string]bool{}
	m.requestKeys = map[string]string{}
	m.restale()
}

// restale makes every reply be drawn again.
func (m *model) restale() {
	for _, b := range m.blocks {
		if b.kind == kindAssistant {
			b.stale = true
		}
	}
}

// lookup is an extension renderer's drawing of block. The first time it asks minimal and answers "not ready":
// the block is drawn the default way until the answer arrives.
func (m *model) lookup(kind string, block map[string]any) (*[]Line, bool) {
	data, _ := json.Marshal(block)
	key := kind + "\x00" + string(data)
	if lines, ok := m.rendered[key]; ok {
		return lines, true
	}
	if !m.requested[key] {
		m.requested[key] = true
		m.nextRequest++
		id := fmt.Sprintf("r%d", m.nextRequest)
		m.requestKeys[id] = key
		m.conn.render(id, kind, block)
	}
	return nil, false
}

// replay draws the resumed session's messages.
func (m *model) replay(msg Message) {
	if msg.Hidden > 0 {
		m.add(&block{kind: kindNotice, level: "info", text: fmt.Sprintf("… %d earlier messages not shown", msg.Hidden)})
	}
	tools := map[string]*block{}
	for _, raw := range msg.Messages {
		var message struct {
			Role    string          `json:"role"`
			Content json.RawMessage `json:"content"`
		}
		if json.Unmarshal(raw, &message) != nil {
			continue
		}
		var text string
		if json.Unmarshal(message.Content, &text) == nil {
			m.blocks = append(m.blocks, &block{kind: kindUser, text: text})
			continue
		}
		var parts []struct {
			Type      string          `json:"type"`
			Text      string          `json:"text"`
			ID        string          `json:"id"`
			Name      string          `json:"name"`
			Input     map[string]any  `json:"input"`
			ToolUseID string          `json:"tool_use_id"`
			Content   json.RawMessage `json:"content"`
			IsError   bool            `json:"is_error"`
		}
		if json.Unmarshal(message.Content, &parts) != nil {
			continue
		}
		for _, p := range parts {
			switch {
			case p.Type == "text" && message.Role == "assistant":
				m.blocks = append(m.blocks, &block{kind: kindAssistant, text: p.Text})
			case p.Type == "tool_use":
				b := &block{kind: kindTool, call: &Call{ID: p.ID, Name: p.Name, Input: p.Input}}
				if lines, ok := msg.Bodies[p.ID]; ok {
					b.body = &lines
				}
				tools[p.ID] = b
				m.blocks = append(m.blocks, b)
			case p.Type == "tool_result":
				if b := tools[p.ToolUseID]; b != nil {
					b.result, b.stale = &Result{ToolUseID: p.ToolUseID, Content: p.Content, IsError: p.IsError}, true
				}
			}
		}
	}
}

// problems shows what a reload reported.
func (m *model) problems(msg Message) {
	for _, e := range msg.Errors {
		m.add(&block{kind: kindNotice, level: "error", text: "[extension] could not load " + e})
	}
	for _, s := range msg.Skipped {
		m.add(&block{kind: kindNotice, level: "warning", text: "[extension] skipped " + s})
	}
	if msg.Notice != nil {
		m.add(&block{kind: kindNotice, level: "warning", text: *msg.Notice})
	}
}

func (m *model) add(b *block) {
	m.blocks = append(m.blocks, b)
	m.endReply()
}

func (m *model) last() *block {
	if len(m.blocks) == 0 {
		return nil
	}
	return m.blocks[len(m.blocks)-1]
}

// --- keys ------------------------------------------------------------------

func (m *model) key(msg tea.KeyPressMsg) (tea.Model, tea.Cmd) {
	if m.modal != nil {
		if done, value := m.modal.update(msg); done {
			m.conn.answer(m.modalID, value)
			m.modal = nil
			m.layout()
		}
		return m, nil
	}
	switch msg.String() {
	case "ctrl+c":
		switch {
		case m.busy:
			m.interrupt()
		case m.input.Value() != "":
			m.input.Reset()
		default:
			return m.quit()
		}
		return m, nil
	case "ctrl+d":
		if !m.busy && m.input.Value() == "" {
			return m.quit()
		}
	case "esc":
		if m.busy {
			m.interrupt()
		}
		return m, nil
	case "ctrl+o":
		m.expanded = !m.expanded
		m.refresh()
		return m, nil
	case "ctrl+b":
		m.sidebarHidden = !m.sidebarHidden
		m.layout()
		m.refresh()
		return m, nil
	case "pgup", "pgdown", "ctrl+u", "ctrl+f":
		var cmd tea.Cmd
		m.vp, cmd = m.vp.Update(msg)
		return m, cmd
	case "enter":
		if !m.busy {
			return m.submit()
		}
		return m, nil
	case "up", "down":
		if !m.busy {
			m.browse(msg.String() == "up")
		}
		return m, nil
	}
	if m.busy {
		return m, nil
	}
	var cmd tea.Cmd
	m.input, cmd = m.input.Update(msg)
	return m, cmd
}

func (m *model) quit() (tea.Model, tea.Cmd) {
	m.conn.quit()
	return m, tea.Quit
}

func (m *model) interrupt() {
	if !m.interrupting {
		m.interrupting = true
		m.conn.interrupt()
	}
}

// browse moves through the lines typed before.
func (m *model) browse(older bool) {
	if len(m.history) == 0 {
		return
	}
	if older {
		m.cursor = max(m.cursor-1, 0)
	} else {
		m.cursor = min(m.cursor+1, len(m.history))
	}
	if m.cursor == len(m.history) {
		m.input.Reset()
		return
	}
	m.input.SetValue(m.history[m.cursor])
	m.input.CursorEnd()
}

// submit sends the prompt's line to minimal.
func (m *model) submit() (tea.Model, tea.Cmd) {
	line := strings.TrimSpace(m.input.Value())
	if line == "" {
		return m, nil
	}
	m.history = append(m.history, line)
	m.cursor = len(m.history)
	m.input.Reset()
	if !strings.HasPrefix(line, "/") {
		m.add(&block{kind: kindUser, text: line})
	}
	m.busy, m.interrupting, m.busySince = true, false, time.Now()
	m.endReply()
	m.conn.submit(line)
	m.refresh()
	return m, m.spin.Tick
}

// --- drawing ---------------------------------------------------------------

// panelLines is the panels of an area, as lines of width columns, one blank line between panels.
func (m *model) panelLines(area string, width int) []string {
	var out []string
	for _, p := range m.panels {
		if p.Area != area || len(p.Lines) == 0 {
			continue
		}
		if len(out) > 0 {
			out = append(out, "")
		}
		out = append(out, renderLines(p.Lines, width)...)
	}
	return out
}

// hasSidebar says whether the sidebar is shown: a sidebar panel has something, and there is room.
func (m *model) hasSidebar() bool {
	return !m.sidebarHidden && m.width >= minForSide && len(m.panelLines("sidebar", sidebarWidth)) > 0
}

// mainWidth is the width of everything but the sidebar and the status line.
func (m *model) mainWidth() int {
	if m.hasSidebar() {
		return m.width - sidebarWidth
	}
	return m.width
}

// layout sizes the transcript to what is left under the top panels and above the bottom panels, the prompt (or
// the question) and the status line.
func (m *model) layout() {
	if m.width == 0 {
		return
	}
	w := m.mainWidth()
	taken := 1 // status line
	if m.modal != nil {
		taken += lipgloss.Height(m.modal.view(w))
	} else {
		taken += 2 // working line, prompt
	}
	taken += len(m.panelLines("top", w)) + len(m.panelLines("bottom", w))
	m.vp.SetWidth(w)
	m.vp.SetHeight(max(m.height-taken, 1))
	m.input.SetWidth(max(w-4, 10))
}

// env is what drawing a block depends on.
func (m *model) env() env {
	return env{width: m.mainWidth(), open: m.expanded, renderers: m.renderers, lookup: m.lookup}
}

// refresh redraws the transcript, staying at the bottom if it was there.
func (m *model) refresh() {
	if m.width == 0 {
		return
	}
	m.layout()
	e := m.env()
	follow := m.vp.AtBottom()
	var b strings.Builder
	var previous *block
	for _, blk := range m.blocks {
		if previous != nil {
			b.WriteString("\n")
			if !(previous.kind == kindTool && blk.kind == kindTool) {
				b.WriteString("\n")
			}
		}
		// A reply still streaming may end in an unfinished line; every other block is final.
		b.WriteString(blk.render(e, blk != m.assistant || !m.busy))
		previous = blk
	}
	m.vp.SetContent(b.String())
	if follow {
		m.vp.GotoBottom()
	}
}

func (m *model) View() tea.View {
	var v tea.View
	if m.width == 0 {
		v = tea.NewView("")
	} else {
		w := m.mainWidth()
		var parts []string
		if top := m.panelLines("top", w); len(top) > 0 {
			parts = append(parts, strings.Join(top, "\n"))
		}
		parts = append(parts, m.vp.View())
		if bottom := m.panelLines("bottom", w); len(bottom) > 0 {
			parts = append(parts, strings.Join(bottom, "\n"))
		}
		if m.modal != nil {
			parts = append(parts, m.modal.view(w))
		} else {
			parts = append(parts, m.working(), m.input.View())
		}
		body := strings.Join(parts, "\n")
		if m.hasSidebar() {
			body = lipgloss.JoinHorizontal(lipgloss.Top, body, m.sidebar(lipgloss.Height(body)))
		}
		v = tea.NewView(body + "\n" + m.statusLine())
	}
	v.AltScreen = true
	v.MouseMode = tea.MouseModeCellMotion
	v.WindowTitle = "minimal"
	return v
}

// sidebar draws the sidebar panels in a column of the given height.
func (m *model) sidebar(height int) string {
	lines := m.panelLines("sidebar", sidebarWidth-3)
	if len(lines) > height {
		lines = lines[:height]
	}
	return lipgloss.NewStyle().
		BorderStyle(lipgloss.NormalBorder()).
		BorderLeft(true).BorderTop(false).BorderRight(false).BorderBottom(false).
		BorderForeground(lipgloss.Color("240")).
		PaddingLeft(1).
		Width(sidebarWidth).
		Height(height).
		Render(strings.Join(lines, "\n"))
}

// working is the line above the prompt while a turn or command runs.
func (m *model) working() string {
	if !m.busy {
		return ""
	}
	if m.interrupting {
		return m.spin.View() + " " + muted.Render("Interrupting…")
	}
	elapsed := time.Since(m.busySince).Seconds()
	return m.spin.View() + " " + muted.Render("Working…") + dim.Render(fmt.Sprintf(" %.0fs · esc interrupts", elapsed))
}

// statusLine shows the model, directory and session, with the extensions' segments.
func (m *model) statusLine() string {
	s := m.status
	sep := dim.Render(" │ ")
	left := " " + accent.Render("◆ "+s.Model) + muted.Render(" · "+s.Provider) + sep + muted.Render(shortPath(s.Cwd))
	for _, segment := range m.left {
		left += sep + renderLine(segment)
	}
	tail := fmt.Sprintf("%d ext · session %s ", s.Extensions, s.SessionID)
	if s.ContextTokens != nil {
		tail = fmt.Sprintf("%.1fk ctx · %s", float64(*s.ContextTokens)/1000, tail)
	}
	var right []string
	for _, segment := range m.right {
		right = append(right, renderLine(segment))
	}
	if s.Untrusted > 0 {
		right = append(right, warning.Render(fmt.Sprintf("⚠ %d untrusted", s.Untrusted)))
	}
	right = append(right, dim.Render(tail))
	rightText := strings.Join(right, dim.Render(" · "))
	gap := m.width - lipgloss.Width(left) - lipgloss.Width(rightText)
	if gap < 1 {
		return ansi.Truncate(left, m.width, "…")
	}
	return left + strings.Repeat(" ", gap) + rightText
}

// shortPath writes the home directory as ~.
func shortPath(path string) string {
	if home, err := os.UserHomeDir(); err == nil && (path == home || strings.HasPrefix(path, home+string(os.PathSeparator))) {
		return "~" + path[len(home):]
	}
	return path
}
