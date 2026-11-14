package main

import (
	"reflect"
	"strings"
	"testing"
)

func TestSplitReply(t *testing.T) {
	tests := []struct {
		name  string
		text  string
		final bool
		want  []segment
	}{
		{
			name: "plain text is one segment",
			text: "hello\n\nworld",
			want: []segment{{kind: "text", text: "hello\n\nworld"}},
		},
		{
			name:  "closed fence between text",
			text:  "before\n```python\nx = 1\n```\nafter",
			final: true,
			want: []segment{
				{kind: "text", text: "before"},
				{kind: "fence", lang: "python", text: "x = 1\n", closed: true},
				{kind: "text", text: "after"},
			},
		},
		{
			name: "open fence while streaming shows complete lines only and stays open",
			text: "```mermaid\ngraph TD\nA-->",
			want: []segment{{kind: "fence", lang: "mermaid", text: "graph TD\n", closed: false}},
		},
		{
			name: "open fence whose last line is complete is still open",
			text: "```mermaid\ngraph TD\nA-->B\n",
			want: []segment{{kind: "fence", lang: "mermaid", text: "graph TD\nA-->B\n", closed: false}},
		},
		{
			name:  "open fence counts as closed in the final reply",
			text:  "```mermaid\ngraph TD\nA-->B",
			final: true,
			want:  []segment{{kind: "fence", lang: "mermaid", text: "graph TD\nA-->B\n", closed: true}},
		},
		{
			name: "fence opener still being typed is text",
			text: "intro\n```merm",
			want: []segment{{kind: "text", text: "intro\n```merm"}},
		},
		{
			name: "fence opener without a body yet",
			text: "```go\n",
			want: []segment{{kind: "fence", lang: "go", text: "", closed: false}},
		},
		{
			name: "longer fence holds a shorter one",
			text: "````md\n```\ninner\n```\n````\n",
			want: []segment{{kind: "fence", lang: "md", text: "```\ninner\n```\n", closed: true}},
		},
		{
			name: "a closing line must be only backticks",
			text: "```go\nx\n```go\n",
			want: []segment{{kind: "fence", lang: "go", text: "x\n```go\n", closed: false}},
		},
		{
			name: "language is the first word, lowercased",
			text: "``` Python title=x\npass\n```\n",
			want: []segment{{kind: "fence", lang: "python", text: "pass\n", closed: true}},
		},
		{
			name: "fence without language",
			text: "```\nplain\n```\n",
			want: []segment{{kind: "fence", lang: "", text: "plain\n", closed: true}},
		},
		{
			name: "alert with a second paragraph",
			text: "> [!NOTE] Heads up\n> more\n>\n> second\nafter",
			want: []segment{
				{kind: "alert", alert: "note", text: "Heads up\nmore", rest: "> \n> second"},
				{kind: "text", text: "after"},
			},
		},
		{
			name: "alert marker is case-insensitive and may stand alone",
			text: "> [!warning]\n> careful\n",
			want: []segment{{kind: "alert", alert: "warning", text: "careful"}},
		},
		{
			name: "alert line still being typed is text",
			text: "> [!TIP] almost",
			want: []segment{{kind: "text", text: "> [!TIP] almost"}},
		},
		{
			name:  "alert in the final reply",
			text:  "> [!TIP] almost",
			final: true,
			want:  []segment{{kind: "alert", alert: "tip", text: "almost"}},
		},
		{
			name: "an ordinary quote is text",
			text: "> just a quote\n> [!BUG] not an alert",
			want: []segment{{kind: "text", text: "> just a quote\n> [!BUG] not an alert"}},
		},
		{
			name: "an alert inside a fence stays in the fence",
			text: "```\n> [!NOTE] x\n```\n",
			want: []segment{{kind: "fence", lang: "", text: "> [!NOTE] x\n", closed: true}},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := splitReply(tt.text, tt.final)
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("splitReply(%q, %v)\n got %+v\nwant %+v", tt.text, tt.final, got, tt.want)
			}
		})
	}
}

func TestSplitReplyStreamingNeverLosesText(t *testing.T) {
	// every prefix of a reply must split without panicking, and a fence never shows an unfinished line
	reply := "intro\n```mermaid\ngraph TD\nA-->B\n```\n> [!NOTE] Heads up\n> more\n>\n> rest\ndone\n"
	for i := 0; i <= len(reply); i++ {
		for _, final := range []bool{false, true} {
			for _, seg := range splitReply(reply[:i], final) {
				if seg.kind == "fence" && seg.text != "" && !strings.HasSuffix(seg.text, "\n") {
					t.Fatalf("prefix %q: fence shows an unfinished line %q", reply[:i], seg.text)
				}
			}
		}
	}
}
