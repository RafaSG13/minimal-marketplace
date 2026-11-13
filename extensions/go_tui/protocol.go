package main

import (
	"bufio"
	"encoding/json"
	"io"
	"os"
	"sync"
)

// protocol is the version of the JSON lines spoken with minimal (the Python bridge in __init__.py).
const protocol = 1

// Status is what the status line shows (minimal's HostStatus).
type Status struct {
	Model         string `json:"model"`
	Provider      string `json:"provider"`
	Cwd           string `json:"cwd"`
	SessionID     string `json:"session_id"`
	ContextTokens *int   `json:"context_tokens"`
	Extensions    int    `json:"extensions"`
	Untrusted     int    `json:"untrusted"`
}

// Call is a tool call: {id, name, input}.
type Call struct {
	ID    string         `json:"id"`
	Name  string         `json:"name"`
	Input map[string]any `json:"input"`
}

// Result is a tool_result block.
type Result struct {
	ToolUseID string          `json:"tool_use_id"`
	Content   json.RawMessage `json:"content"`
	IsError   bool            `json:"is_error"`
}

// Option is one choice of a choose or choose_many question.
type Option struct {
	Value   string `json:"value"`
	Label   string `json:"label"`
	Checked bool   `json:"checked"`
}

// PanelData is an extension panel as last drawn.
type PanelData struct {
	Name  string `json:"name"`
	Area  string `json:"area"` // top, bottom or sidebar
	Lines []Line `json:"lines"`
}

// Message is a line from minimal. T says which fields are set.
type Message struct {
	T string `json:"t"`

	// hello
	Protocol int               `json:"protocol"`
	Version  string            `json:"version"`
	Messages []json.RawMessage `json:"messages"`
	Hidden   int               `json:"hidden"`

	// hello: what tool renderers drew for the resumed session's calls, by call id
	Bodies map[string][]Line `json:"bodies"`

	// hello, reloaded
	Errors  []string `json:"errors"`
	Skipped []string `json:"skipped"`
	Notice  *string  `json:"notice"`

	// hello, reloaded: the block kinds extensions registered a renderer for
	Renderers []string `json:"renderers"`

	// hello, idle
	Status *Status `json:"status"`

	// text
	Chunk string `json:"chunk"`

	// tool_call, tool_result
	Call   *Call   `json:"call"`
	Result *Result `json:"result"`

	// tool_call, tool_result: what the tool renderer drew; nil for the default drawing
	Body *[]Line `json:"body"`

	// turn_end
	Error *string `json:"error"`

	// notify
	Text string `json:"text"`
	Kind string `json:"kind"`

	// output
	Stderr bool `json:"stderr"`

	// ask, choose, choose_many, ask_text; rendered
	ID       string   `json:"id"`
	Question string   `json:"question"`
	Title    string   `json:"title"`
	Options  []Option `json:"options"`

	// rendered: the reply to a render request (nil: draw the block the default way)
	Lines *[]Line `json:"lines"`

	// panels
	Panels []PanelData `json:"panels"`

	// segments: the status line's extension segments
	Left  []Line `json:"left"`
	Right []Line `json:"right"`
}

// conn writes lines to minimal (our stdout) and reads them from it (our stdin).
type conn struct {
	mu  sync.Mutex
	out io.Writer
}

func (c *conn) send(v any) {
	data, err := json.Marshal(v)
	if err != nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	_, _ = c.out.Write(append(data, '\n'))
}

func (c *conn) submit(text string) { c.send(map[string]any{"t": "submit", "text": text}) }
func (c *conn) interrupt()         { c.send(map[string]any{"t": "interrupt"}) }
func (c *conn) quit()              { c.send(map[string]any{"t": "quit"}) }
func (c *conn) suspended()         { c.send(map[string]any{"t": "suspended"}) }
func (c *conn) answer(id string, value any) {
	c.send(map[string]any{"t": "answer", "id": id, "value": value})
}

// render asks minimal to draw a block with an extension's renderer; the reply is a "rendered" message.
func (c *conn) render(id, kind string, block map[string]any) {
	c.send(map[string]any{"t": "render", "id": id, "kind": kind, "block": block})
}

// readMessages decodes minimal's lines until it closes the pipe; each goes to deliver.
func readMessages(in io.Reader, deliver func(Message)) {
	reader := bufio.NewReaderSize(in, 1<<20)
	for {
		line, err := reader.ReadBytes('\n')
		if len(line) > 0 {
			var m Message
			if json.Unmarshal(line, &m) == nil {
				deliver(m)
			}
		}
		if err != nil {
			return
		}
	}
}

// openTerminal opens the terminal for the interface: stdin and stdout carry the protocol.
func openTerminal() (in, out *os.File, err error) {
	return openTTY()
}
