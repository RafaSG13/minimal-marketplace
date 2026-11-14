package main

import (
	"fmt"
	"strings"
)

// env is what drawing a block depends on besides the block.
type env struct {
	width int
	open  bool // tool bodies are expanded

	// renderers has the block kinds extensions registered a renderer for ("fence:mermaid", "blockquote:alert", ...).
	renderers map[string]bool
	// lookup is an extension renderer's drawing of block: the lines, and whether the answer is known yet.
	// A nil result with ready true means the renderer chose the default drawing.
	lookup func(kind string, block map[string]any) (lines *[]Line, ready bool)
}

// splitsReplies says whether a renderer may want a part of a reply, so that it has to be cut into segments.
func (e env) splitsReplies() bool {
	for kind := range e.renderers {
		if kind == "blockquote:alert" || strings.HasPrefix(kind, "fence:") {
			return true
		}
	}
	return false
}

// renderReply draws an assistant reply: Markdown, with the fences and alerts extensions draw themselves.
func renderReply(e env, text string, final bool) string {
	text = visible(text)
	if !e.splitsReplies() {
		return markdown(text, e.width-2)
	}
	var parts []string
	for _, seg := range splitReply(text, final) {
		switch seg.kind {
		case "fence":
			if out, ok := e.drawFence(seg); ok {
				parts = append(parts, out)
			} else {
				parts = append(parts, markdown("```"+seg.lang+"\n"+seg.text+"```", e.width-2))
			}
		case "alert":
			if out, ok := e.drawAlert(seg); ok {
				parts = append(parts, out)
			} else {
				parts = append(parts, markdown(alertMarkdown(seg), e.width-2))
			}
		default:
			if strings.TrimSpace(seg.text) != "" {
				parts = append(parts, markdown(seg.text, e.width-2))
			}
		}
	}
	return strings.Join(parts, "\n\n")
}

// drawFence is the fence as its extension renderer drew it, if there is one and it has answered.
func (e env) drawFence(seg segment) (string, bool) {
	kind := "fence:" + seg.lang
	if !e.renderers[kind] || strings.TrimSpace(seg.text) == "" {
		return "", false
	}
	lines, ready := e.lookup(kind, map[string]any{
		"kind": kind, "language": seg.lang, "source": seg.text, "closed": seg.closed, "width": max(e.width-4, 20),
	})
	if !ready || lines == nil {
		return "", false
	}
	return indent(renderLines(*lines, e.width-2)), true
}

// drawAlert is the alert's first paragraph as its renderer drew it, then the rest of the quote as Markdown.
func (e env) drawAlert(seg segment) (string, bool) {
	if !e.renderers["blockquote:alert"] {
		return "", false
	}
	lines, ready := e.lookup("blockquote:alert", map[string]any{
		"kind": "blockquote:alert", "alert": seg.alert, "text": seg.text, "width": max(e.width-4, 20),
	})
	if !ready || lines == nil {
		return "", false
	}
	out := indent(renderLines(*lines, e.width-2))
	if seg.rest != "" {
		out += "\n\n" + markdown(seg.rest, e.width-2)
	}
	return out, true
}

// alertMarkdown is an alert as plain Markdown, for when no renderer draws it.
func alertMarkdown(seg segment) string {
	var quote []string
	for i, line := range strings.Split(seg.text, "\n") {
		if i == 0 {
			line = fmt.Sprintf("[!%s] %s", strings.ToUpper(seg.alert), line)
		}
		quote = append(quote, "> "+line)
	}
	out := strings.Join(quote, "\n")
	if seg.rest != "" {
		out += "\n>\n" + seg.rest
	}
	return out
}

// indent lines by the two columns of margin the Markdown rendering has.
func indent(lines []string) string {
	for i, line := range lines {
		lines[i] = "  " + line
	}
	return strings.Join(lines, "\n")
}
