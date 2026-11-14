package main

import (
	"bytes"
	"reflect"
	"strings"
	"testing"
)

func mustDecode(t *testing.T, line string) Message {
	t.Helper()
	m, ok := decode([]byte(line))
	if !ok {
		t.Fatalf("decode(%s) was rejected", line)
	}
	return m
}

func TestDecodeHello(t *testing.T) {
	m := mustDecode(t, `{"t":"hello","protocol":2,"version":"0.5.0",
		"status":{"model":"m","provider":"p","cwd":"/w","session_id":"s1","context_tokens":1200,"extensions":3,"untrusted":1},
		"messages":[{"role":"user","content":"hi"}],"hidden":4,
		"renderers":["fence:mermaid","tool:bash"],
		"bodies":{"c1":[[["ok","bold"]]]},
		"errors":["x: boom"],"skipped":["y"],"notice":"2 untrusted"}`)
	if m.T != "hello" || m.Protocol != protocol || m.Version != "0.5.0" || m.Hidden != 4 {
		t.Errorf("hello header: %+v", m)
	}
	if m.Status == nil || m.Status.Model != "m" || m.Status.SessionID != "s1" || m.Status.Extensions != 3 || m.Status.Untrusted != 1 ||
		m.Status.ContextTokens == nil || *m.Status.ContextTokens != 1200 {
		t.Errorf("status: %+v", m.Status)
	}
	if len(m.Messages) != 1 || !strings.Contains(string(m.Messages[0]), `"role":"user"`) {
		t.Errorf("messages: %s", m.Messages)
	}
	if !reflect.DeepEqual(m.Renderers, []string{"fence:mermaid", "tool:bash"}) {
		t.Errorf("renderers: %v", m.Renderers)
	}
	if !reflect.DeepEqual(m.Bodies["c1"], []Line{{{"ok", "bold"}}}) {
		t.Errorf("bodies: %v", m.Bodies)
	}
	if !reflect.DeepEqual(m.Errors, []string{"x: boom"}) || !reflect.DeepEqual(m.Skipped, []string{"y"}) || m.Notice == nil || *m.Notice != "2 untrusted" {
		t.Errorf("problems: %+v", m)
	}
}

func TestDecodeHelloNullContext(t *testing.T) {
	m := mustDecode(t, `{"t":"hello","protocol":2,"status":{"model":"m","context_tokens":null},"notice":null}`)
	if m.Status == nil || m.Status.ContextTokens != nil || m.Notice != nil {
		t.Errorf("null fields: %+v", m)
	}
}

func TestDecodeMessages(t *testing.T) {
	tests := []struct {
		name  string
		line  string
		check func(t *testing.T, m Message)
	}{
		{"text", `{"t":"text","chunk":"Hel"}`, func(t *testing.T, m Message) {
			if m.Chunk != "Hel" {
				t.Errorf("chunk %q", m.Chunk)
			}
		}},
		{"tool_call", `{"t":"tool_call","call":{"id":"c1","name":"bash","input":{"command":"ls"}},"body":null}`, func(t *testing.T, m Message) {
			if m.Call == nil || m.Call.ID != "c1" || m.Call.Name != "bash" || m.Call.Input["command"] != "ls" {
				t.Errorf("call %+v", m.Call)
			}
			if m.Body != nil {
				t.Errorf("null body must stay nil: %v", *m.Body)
			}
		}},
		{"tool_call with a drawn body", `{"t":"tool_call","call":{"id":"c1","name":"bash","input":{}},"body":[[["$ ls","muted"]]]}`, func(t *testing.T, m Message) {
			if m.Body == nil || !reflect.DeepEqual(*m.Body, []Line{{{"$ ls", "muted"}}}) {
				t.Errorf("body %v", m.Body)
			}
		}},
		{"tool_result", `{"t":"tool_result","call":{"id":"c1","name":"bash","input":{}},"result":{"tool_use_id":"c1","content":"a\nb","is_error":true},"body":null}`, func(t *testing.T, m Message) {
			if m.Result == nil || m.Result.ToolUseID != "c1" || !m.Result.IsError || string(m.Result.Content) != `"a\nb"` {
				t.Errorf("result %+v", m.Result)
			}
		}},
		{"tool_result with block content", `{"t":"tool_result","call":{"id":"c2","name":"read","input":{}},"result":{"tool_use_id":"c2","content":[{"type":"text","text":"x"}],"is_error":false}}`, func(t *testing.T, m Message) {
			if m.Result == nil || m.Result.IsError || !strings.Contains(string(m.Result.Content), `"type":"text"`) {
				t.Errorf("result %+v", m.Result)
			}
		}},
		{"turn_end", `{"t":"turn_end","error":null}`, func(t *testing.T, m Message) {
			if m.Error != nil {
				t.Errorf("error %q", *m.Error)
			}
		}},
		{"turn_end with error", `{"t":"turn_end","error":"rate limited"}`, func(t *testing.T, m Message) {
			if m.Error == nil || *m.Error != "rate limited" {
				t.Errorf("error %v", m.Error)
			}
		}},
		{"output", `{"t":"output","text":"warn\n","stderr":true}`, func(t *testing.T, m Message) {
			if m.Text != "warn\n" || !m.Stderr {
				t.Errorf("output %+v", m)
			}
		}},
		{"notify", `{"t":"notify","text":"saved","kind":"info"}`, func(t *testing.T, m Message) {
			if m.Text != "saved" || m.Kind != "info" {
				t.Errorf("notify %+v", m)
			}
		}},
		{"reloaded", `{"t":"reloaded","renderers":["blockquote:alert"],"errors":[],"skipped":["z"],"notice":null}`, func(t *testing.T, m Message) {
			if !reflect.DeepEqual(m.Renderers, []string{"blockquote:alert"}) || len(m.Errors) != 0 || !reflect.DeepEqual(m.Skipped, []string{"z"}) {
				t.Errorf("reloaded %+v", m)
			}
		}},
		{"idle", `{"t":"idle","status":{"model":"m2","provider":"p","cwd":"/w","session_id":"s","context_tokens":null,"extensions":0,"untrusted":0}}`, func(t *testing.T, m Message) {
			if m.Status == nil || m.Status.Model != "m2" {
				t.Errorf("status %+v", m.Status)
			}
		}},
		{"ask", `{"t":"ask","id":"7","question":"Run rm -rf?"}`, func(t *testing.T, m Message) {
			if m.ID != "7" || m.Question != "Run rm -rf?" {
				t.Errorf("ask %+v", m)
			}
		}},
		{"choose", `{"t":"choose","id":"8","title":"Pick","options":[{"value":"a","label":"Alpha"},{"value":"b","label":"Beta"}]}`, func(t *testing.T, m Message) {
			want := []Option{{Value: "a", Label: "Alpha"}, {Value: "b", Label: "Beta"}}
			if m.ID != "8" || m.Title != "Pick" || !reflect.DeepEqual(m.Options, want) {
				t.Errorf("choose %+v", m)
			}
		}},
		{"choose_many", `{"t":"choose_many","id":"9","title":"Tick","options":[{"value":"a","label":"A","checked":true},{"value":"b","label":"B","checked":false}]}`, func(t *testing.T, m Message) {
			if len(m.Options) != 2 || !m.Options[0].Checked || m.Options[1].Checked {
				t.Errorf("choose_many %+v", m.Options)
			}
		}},
		{"ask_text", `{"t":"ask_text","id":"10","title":"Name?"}`, func(t *testing.T, m Message) {
			if m.ID != "10" || m.Title != "Name?" {
				t.Errorf("ask_text %+v", m)
			}
		}},
		{"suspend", `{"t":"suspend"}`, func(t *testing.T, m Message) {}},
		{"resume", `{"t":"resume"}`, func(t *testing.T, m Message) {}},
		{"quit", `{"t":"quit"}`, func(t *testing.T, m Message) {}},
		{"panels", `{"t":"panels","panels":[{"name":"git","area":"sidebar","lines":[[["main","accent"],[" +2","success"]],[]]},{"name":"gauge","area":"top","lines":[]}]}`, func(t *testing.T, m Message) {
			if len(m.Panels) != 2 {
				t.Fatalf("panels %+v", m.Panels)
			}
			p := m.Panels[0]
			if p.Name != "git" || p.Area != "sidebar" || len(p.Lines) != 2 || !reflect.DeepEqual(p.Lines[0], Line{{"main", "accent"}, {" +2", "success"}}) || len(p.Lines[1]) != 0 {
				t.Errorf("panel %+v", p)
			}
			if m.Panels[1].Area != "top" {
				t.Errorf("panel %+v", m.Panels[1])
			}
		}},
		{"segments", `{"t":"segments","left":[[["a","muted"]]],"right":[[["b","bold"]],[["c",""]]]}`, func(t *testing.T, m Message) {
			if len(m.Left) != 1 || len(m.Right) != 2 || m.Right[1][0][0] != "c" {
				t.Errorf("segments %+v %+v", m.Left, m.Right)
			}
		}},
		{"rendered", `{"t":"rendered","id":"r1","lines":[[["box","accent"]]]}`, func(t *testing.T, m Message) {
			if m.ID != "r1" || m.Lines == nil || !reflect.DeepEqual(*m.Lines, []Line{{{"box", "accent"}}}) {
				t.Errorf("rendered %+v", m)
			}
		}},
		{"rendered with the default drawing", `{"t":"rendered","id":"r2","lines":null}`, func(t *testing.T, m Message) {
			if m.ID != "r2" || m.Lines != nil {
				t.Errorf("rendered %+v", m)
			}
		}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			m := mustDecode(t, tt.line)
			wantT, _, _ := strings.Cut(strings.TrimPrefix(tt.line, `{"t":"`), `"`)
			if m.T != wantT {
				t.Errorf("T = %q, want %q", m.T, wantT)
			}
			tt.check(t, m)
		})
	}
}

func TestDecodeRejects(t *testing.T) {
	for _, line := range []string{"", "\n", "plain text", "{not json", `{"chunk":"no type"}`, `[1,2]`} {
		if m, ok := decode([]byte(line)); ok {
			t.Errorf("decode(%q) = %+v, want a rejection", line, m)
		}
	}
}

func TestReadMessages(t *testing.T) {
	// stray lines are skipped, an unterminated last line still counts, long lines survive
	long := strings.Repeat("x", 3<<20)
	in := "noise\n" + `{"t":"text","chunk":"a"}` + "\n\n" + `{"t":"text","chunk":"` + long + `"}` + "\n" + `{"t":"quit"}`
	var got []Message
	readMessages(strings.NewReader(in), func(m Message) { got = append(got, m) })
	if len(got) != 3 || got[0].Chunk != "a" || len(got[1].Chunk) != len(long) || got[2].T != "quit" {
		t.Errorf("got %d messages", len(got))
	}
}

func TestClientMessages(t *testing.T) {
	var buf bytes.Buffer
	c := &conn{out: &buf}
	c.submit("hi \"there\"\n")
	c.interrupt()
	c.answer("3", true)
	c.answer("4", []string{"a", "b"})
	c.answer("5", nil)
	c.suspended()
	c.render("r1", "fence:mermaid", map[string]any{"source": "graph TD\n"})
	c.quit()
	want := []string{
		`{"t":"submit","text":"hi \"there\"\n"}`,
		`{"t":"interrupt"}`,
		`{"id":"3","t":"answer","value":true}`,
		`{"id":"4","t":"answer","value":["a","b"]}`,
		`{"id":"5","t":"answer","value":null}`,
		`{"t":"suspended"}`,
		`{"block":{"source":"graph TD\n"},"id":"r1","kind":"fence:mermaid","t":"render"}`,
		`{"t":"quit"}`,
	}
	if got := strings.Split(strings.TrimSuffix(buf.String(), "\n"), "\n"); !reflect.DeepEqual(got, want) {
		t.Errorf("sent\n%s\nwant\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
}
