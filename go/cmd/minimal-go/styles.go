package main

import (
	"strings"

	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

// Piece is a run of text and its style: a space-separated list of minimal's STYLES names ("bold muted").
type Piece [2]string

// Line is one line of styled text.
type Line []Piece

// colours maps minimal's style colour names to terminal colours.
var colours = map[string]string{
	"accent":       "75",
	"secondary":    "14",
	"success":      "10",
	"warning":      "11",
	"error":        "9",
	"muted":        "245",
	"dim":          "240",
	"diff_added":   "10",
	"diff_removed": "9",
}

// styleFor is the Lip Gloss style of a STYLES string; "" and "foreground" are the terminal's default.
func styleFor(names string) lipgloss.Style {
	style := lipgloss.NewStyle()
	for _, name := range strings.Fields(names) {
		switch name {
		case "bold":
			style = style.Bold(true)
		case "italic":
			style = style.Italic(true)
		case "underline":
			style = style.Underline(true)
		case "reverse":
			style = style.Reverse(true)
		default:
			if c, ok := colours[name]; ok {
				style = style.Foreground(lipgloss.Color(c))
			}
		}
	}
	return style
}

// renderLine draws a line of pieces.
func renderLine(line Line) string {
	var b strings.Builder
	for _, piece := range line {
		text := visible(piece[0])
		if piece[1] == "" {
			b.WriteString(text)
		} else {
			b.WriteString(styleFor(piece[1]).Render(text))
		}
	}
	return b.String()
}

// renderLines draws lines, each cut to width columns.
func renderLines(lines []Line, width int) []string {
	out := make([]string, 0, len(lines))
	for _, line := range lines {
		out = append(out, ansi.Truncate(renderLine(line), width, "…"))
	}
	return out
}
