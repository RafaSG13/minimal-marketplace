package main

import (
	"regexp"
	"strings"
)

// segment is a part of an assistant reply: plain Markdown, or a block an extension may draw itself.
type segment struct {
	kind string // "text", "fence" or "alert"

	text string // text: the Markdown; fence: its source (complete lines); alert: its first paragraph after the marker

	// fence
	lang   string
	closed bool

	// alert
	alert string // note, tip, important, warning or caution
	rest  string // the quote's other paragraphs, as Markdown
}

var (
	fenceOpen  = regexp.MustCompile("^ {0,3}(`{3,})[ \t]*([^`]*)$")
	alertStart = regexp.MustCompile(`(?i)^ {0,3}>[ \t]?\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(.*)$`)
	quoteLine  = regexp.MustCompile(`^ {0,3}>[ \t]?(.*)$`)
)

// splitReply cuts a reply into plain Markdown, code fences and alert blockquotes.
//
// While the reply streams (final is false) its last line may be unfinished: a fence shows only complete lines,
// and a fence still open is not closed. With final, an open fence counts as closed.
func splitReply(text string, final bool) []segment {
	lines := strings.Split(text, "\n")
	partial := !final && !strings.HasSuffix(text, "\n") // the last element is an unfinished line
	complete := len(lines)
	if partial {
		complete--
	}
	var segments []segment
	var plain []string
	flush := func() {
		if len(plain) > 0 {
			segments = append(segments, segment{kind: "text", text: strings.Join(plain, "\n")})
			plain = nil
		}
	}
	for i := 0; i < len(lines); {
		line := lines[i]
		if m := fenceOpen.FindStringSubmatch(line); m != nil && i < complete {
			flush()
			lang := strings.ToLower(firstWord(m[2]))
			end, closed := len(lines), false
			for j := i + 1; j < complete; j++ {
				if isFenceClose(lines[j], m[1]) {
					end, closed = j, true
					break
				}
			}
			body := lines[i+1 : min(end, complete)]
			source := ""
			if len(body) > 0 {
				source = strings.Join(body, "\n") + "\n"
			}
			segments = append(segments, segment{kind: "fence", lang: lang, text: source, closed: closed || final})
			if closed {
				i = end + 1
			} else {
				i = len(lines)
			}
			continue
		}
		if m := alertStart.FindStringSubmatch(line); m != nil && i < complete {
			flush()
			j := i
			var quote []string
			for ; j < len(lines); j++ {
				q := quoteLine.FindStringSubmatch(lines[j])
				if q == nil {
					break
				}
				quote = append(quote, q[1])
			}
			quote[0] = m[2]
			first, rest := paragraphs(quote)
			segments = append(segments, segment{kind: "alert", alert: strings.ToLower(m[1]), text: first, rest: rest})
			i = j
			continue
		}
		plain = append(plain, line)
		i++
	}
	flush()
	return segments
}

// paragraphs splits a quote's lines at its first blank line: the first paragraph, and the rest as quoted Markdown.
func paragraphs(quote []string) (first, rest string) {
	end := len(quote)
	for i, line := range quote {
		if strings.TrimSpace(line) == "" && i > 0 {
			end = i
			break
		}
	}
	first = strings.TrimSpace(strings.Join(quote[:end], "\n"))
	var other []string
	for _, line := range quote[end:] {
		other = append(other, "> "+line)
	}
	if strings.TrimSpace(strings.Join(quote[end:], "")) != "" {
		rest = strings.Join(other, "\n")
	}
	return first, rest
}

func isFenceClose(line, fence string) bool {
	trimmed := strings.TrimSpace(line)
	return strings.HasPrefix(trimmed, fence) && strings.Trim(trimmed, "`") == ""
}

func firstWord(s string) string {
	if fields := strings.Fields(s); len(fields) > 0 {
		return fields[0]
	}
	return ""
}
