package main

import (
	"reflect"
	"testing"
)

func TestServeArgsAlwaysServeTheGoFrontend(t *testing.T) {
	cases := []struct {
		in   []string
		want []string
	}{
		{nil, []string{"serve", "--ui", "go"}},
		{[]string{"--model", "m", "--yes"}, []string{"serve", "--ui", "go", "--model", "m", "--yes"}},
	}
	for _, c := range cases {
		if got := serveArgs(c.in); !reflect.DeepEqual(got, c.want) {
			t.Errorf("serveArgs(%v) = %v, want %v", c.in, got, c.want)
		}
	}
}
