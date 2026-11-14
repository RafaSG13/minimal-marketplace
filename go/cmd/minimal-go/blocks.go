package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"unicode/utf8"

	"charm.land/glamour/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

const (
	previewLines  = 8   // lines of a tool body shown before it is expanded
	expandedLines = 500 // most lines of a tool body kept
)

var (
	muted   = lipgloss.NewStyle().Foreground(lipgloss.Color("245"))
	dim     = lipgloss.NewStyle().Foreground(lipgloss.Color("240"))
	accent  = lipgloss.NewStyle().Foreground(lipgloss.Color("75"))
	success = lipgloss.NewStyle().Foreground(lipgloss.Color("10"))
	warning = lipgloss.NewStyle().Foreground(lipgloss.Color("11"))
	failure = lipgloss.NewStyle().Foreground(lipgloss.Color("9"))
	bold    = lipgloss.NewStyle().Bold(true)
)

type blockKind int

const (
	kindUser blockKind = iota
	kindAssistant
	kindTool
	kindOutput
	kindNotice
)

// block is one item of the transcript.
type block struct {
	kind blockKind
	text string // user, assistant, output and notice text
	// level is a notice's "info", "warning" or "error"; an output block is "error" when it came from stderr.
	level string

	call   *Call   // tool
	result *Result // tool: nil while it runs
	body   *[]Line // tool: what an extension's renderer drew, instead of the default body

	cache      string // the block as last drawn
	cacheWidth int
	cacheOpen  bool
	cacheFinal bool
	stale      bool
}

// visible is text with control characters (all but tab and newline) written as \xNN: text from the model or a
// tool must not reach the terminal raw, where escape sequences could rewrite what is on screen.
func visible(text string) string {
	clean := true
	for _, r := range text {
		if isControl(r) {
			clean = false
			break
		}
	}
	if clean {
		return text
	}
	var b strings.Builder
	for _, r := range text {
		if isControl(r) {
			fmt.Fprintf(&b, "\\x%02x", r)
		} else {
			b.WriteRune(r)
		}
	}
	return b.String()
}

func isControl(r rune) bool {
	return r <= 0x08 || (r >= 0x0b && r <= 0x1f) || (r >= 0x7f && r <= 0x9f)
}

// markdown renders assistant text for width columns; a renderer is kept per width.
var markdowns = map[int]*glamour.TermRenderer{}

func markdown(text string, width int) string {
	r, ok := markdowns[width]
	if !ok {
		style := os.Getenv("GLAMOUR_STYLE")
		if style == "" {
			style = "dark"
		}
		var err error
		r, err = glamour.NewTermRenderer(glamour.WithStandardStyle(style), glamour.WithWordWrap(width))
		if err != nil {
			return text
		}
		markdowns[width] = r
	}
	out, err := r.Render(text)
	if err != nil {
		return text
	}
	return trimBlankLines(out)
}

// trimBlankLines drops the lines before and after the text that show nothing (spaces, and styles around them).
func trimBlankLines(text string) string {
	lines := strings.Split(text, "\n")
	blank := func(line string) bool { return strings.TrimSpace(ansi.Strip(line)) == "" }
	for len(lines) > 0 && blank(lines[0]) {
		lines = lines[1:]
	}
	for len(lines) > 0 && blank(lines[len(lines)-1]) {
		lines = lines[:len(lines)-1]
	}
	return strings.Join(lines, "\n")
}

// render draws the block; e says how wide, whether tool bodies are expanded and what extensions can draw, and
// final that the block will not grow any more (an open fence is then drawn closed).
func (b *block) render(e env, final bool) string {
	width, open := e.width, e.open
	if !b.stale && b.cache != "" && b.cacheWidth == width &&
		(b.kind != kindTool || b.cacheOpen == open) && (b.kind != kindAssistant || b.cacheFinal == final) {
		return b.cache
	}
	var out string
	switch b.kind {
	case kindUser:
		out = lipgloss.NewStyle().Background(lipgloss.Color("236")).Padding(0, 1).Width(width).Render(b.text)
	case kindAssistant:
		out = renderReply(e, b.text, final)
	case kindTool:
		out = b.renderTool(width, open)
	case kindOutput:
		style := muted
		if b.level == "error" {
			style = failure
		}
		out = style.Width(width).Render(strings.TrimRight(visible(b.text), "\n"))
	case kindNotice:
		icon, style := "ⓘ", accent
		switch b.level {
		case "warning":
			icon, style = "⚠", warning
		case "error":
			icon, style = "✘", failure
		}
		out = style.Width(width).Render(icon + " " + visible(b.text))
	}
	b.cache, b.cacheWidth, b.cacheOpen, b.cacheFinal, b.stale = out, width, open, final, false
	return out
}

func (b *block) renderTool(width int, open bool) string {
	icon, color := warning.Render("◌"), lipgloss.Color("11")
	if b.result != nil {
		if b.result.IsError {
			icon, color = failure.Render("✘"), lipgloss.Color("9")
		} else {
			icon, color = success.Render("✔"), lipgloss.Color("10")
		}
	}
	lines := b.toolBody()
	if b.body != nil {
		lines = renderLines(*b.body, width-2)
	}
	text := icon + " " + toolTitle(b.call)
	if len(lines) > 0 {
		text += "\n" + strings.Join(previewOf(lines, open, b.call.Name == "bash"), "\n")
	}
	return lipgloss.NewStyle().
		BorderStyle(lipgloss.ThickBorder()).
		BorderLeft(true).BorderTop(false).BorderRight(false).BorderBottom(false).
		BorderForeground(color).
		PaddingLeft(1).
		Width(width).
		Render(text)
}

// previewOf is lines cut to previewLines, with a note about the rest; all of them when open.
// A bash call keeps the end of its output, which matters most.
func previewOf(lines []string, open, tail bool) []string {
	hidden := len(lines) - previewLines
	if hidden <= 0 {
		return lines
	}
	if open {
		return append(append([]string{}, lines...), dim.Render("ctrl+o collapses"))
	}
	if tail {
		return append([]string{dim.Render(fmt.Sprintf("… %d earlier lines · ctrl+o expands", hidden))}, lines[hidden:]...)
	}
	return append(append([]string{}, lines[:previewLines]...), dim.Render(fmt.Sprintf("… %d more lines · ctrl+o expands", hidden)))
}

// toolBody is the styled lines under a tool call's title: a diff for edit, the content for write, else the output.
func (b *block) toolBody() []string {
	input := b.call.Input
	failed := b.result != nil && b.result.IsError
	if failed {
		return styledLines(resultText(b.result), failure)
	}
	switch b.call.Name {
	case "edit":
		return editDiff(input)
	case "write":
		if content, ok := input["content"].(string); ok {
			return styledLines(strings.TrimRight(content, "\n"), muted)
		}
	}
	if b.result == nil {
		return nil
	}
	return styledLines(resultText(b.result), muted)
}

func styledLines(text string, style lipgloss.Style) []string {
	text = strings.Trim(visible(text), "\n")
	if text == "" {
		return nil
	}
	lines := strings.Split(strings.ReplaceAll(text, "\t", "    "), "\n")
	if len(lines) > expandedLines {
		lines = lines[:expandedLines]
	}
	for i, line := range lines {
		lines[i] = style.Render(line)
	}
	return lines
}

// editDiff shows each replacement of an edit call as removed and added lines.
func editDiff(input map[string]any) []string {
	replacements := []map[string]any{input}
	if list, ok := input["edits"].([]any); ok {
		replacements = nil
		for _, item := range list {
			if m, ok := item.(map[string]any); ok {
				replacements = append(replacements, m)
			}
		}
	}
	var lines []string
	for _, r := range replacements {
		oldText, ok1 := r["old_string"].(string)
		newText, ok2 := r["new_string"].(string)
		if !ok1 || !ok2 {
			continue
		}
		if len(lines) > 0 {
			lines = append(lines, dim.Render("⋯"))
		}
		for _, line := range strings.Split(strings.TrimRight(visible(oldText), "\n"), "\n") {
			lines = append(lines, failure.Render("- "+line))
		}
		for _, line := range strings.Split(strings.TrimRight(visible(newText), "\n"), "\n") {
			lines = append(lines, success.Render("+ "+line))
		}
	}
	return lines
}

// resultText is the text of a tool_result block's content (a string, or a list of blocks).
func resultText(r *Result) string {
	if r == nil {
		return ""
	}
	var s string
	if json.Unmarshal(r.Content, &s) == nil {
		return s
	}
	var parts []struct {
		Text string `json:"text"`
	}
	if json.Unmarshal(r.Content, &parts) == nil {
		texts := make([]string, 0, len(parts))
		for _, p := range parts {
			texts = append(texts, p.Text)
		}
		return strings.Join(texts, "\n")
	}
	return string(r.Content)
}

// toolTitle is the call's header line: "$ cmd", "read path", or "name {json}".
func toolTitle(call *Call) string {
	name, input := call.Name, call.Input
	if name == "bash" {
		if cmd, ok := input["command"].(string); ok {
			return muted.Render("$ ") + bold.Render(oneLine(cmd, 160))
		}
	}
	title := bold.Render(visible(name))
	if path, ok := input["path"].(string); ok && (name == "read" || name == "write" || name == "edit") {
		title += " " + accent.Render(visible(path))
		if name == "edit" {
			if edits, ok := input["edits"].([]any); ok {
				title += muted.Render(fmt.Sprintf(" (%d edits)", len(edits)))
			}
		}
		return title
	}
	data, _ := json.Marshal(input)
	return title + " " + muted.Render(oneLine(string(data), 120))
}

// oneLine is text on one line of at most limit characters.
func oneLine(text string, limit int) string {
	line := visible(strings.Join(strings.Fields(text), " "))
	if utf8.RuneCountInString(line) <= limit {
		return line
	}
	return string([]rune(line)[:limit-1]) + "…"
}
