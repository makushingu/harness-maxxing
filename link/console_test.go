package main

import (
	"bytes"
	"errors"
	"strings"
	"testing"
)

func TestDescribe(t *testing.T) {
	f := func(v float64) *float64 { return &v }
	cases := map[string]request{
		"Screenshot":                         {T: "shot"},
		"Click at 812,440":                   {T: "input", A: "click", X: f(812.4), Y: f(440)},
		"Double-click at 1,2 (right button)": {T: "input", A: "click", X: f(1), Y: f(2), Double: true, Button: "right"},
		"Drag from 1,2 to 3,4":               {T: "input", A: "drag", X: f(1), Y: f(2), X2: f(3), Y2: f(4)},
		"Scroll up":                          {T: "input", A: "scroll", DY: -3},
		`Type "chien"`:                       {T: "input", A: "type", Text: "chien"},
		`Press "cmd+l"`:                      {T: "input", A: "key", Keys: "cmd+l"},
		`Open app "Firefox"`:                 {T: "open", App: "Firefox"},
	}
	for want, r := range cases {
		if got := describe(r); got != want {
			t.Errorf("describe(%+v) = %q, want %q", r, got, want)
		}
	}
	long := describe(request{T: "input", A: "type", Text: strings.Repeat("é", 100) + "\nx"})
	if !strings.HasSuffix(long, `…"`) || strings.Contains(long, "\n") || len([]rune(long)) != shownText+8 {
		t.Errorf("long text: %q", long)
	}
}

func TestConsoleSay(t *testing.T) {
	var out bytes.Buffer
	var file []string
	c := newConsole(&out, func(f string, a ...any) { file = append(file, f) })
	c.emit(lInfo, "Connected to https://ui.example.com")
	c.emit(lInfo, "one\ntwo")
	lines := strings.Split(strings.TrimRight(out.String(), "\n"), "\n")
	if len(lines) != 3 || !strings.HasSuffix(lines[0], "  Connected to https://ui.example.com") ||
		len(lines[0]) < 10 || lines[0][2] != ':' || !strings.HasPrefix(lines[2], "          two") {
		t.Fatalf("console: %q", out.String())
	}
	if len(file) != 2 {
		t.Fatalf("file log: %v", file)
	}
	if s := shortErr(errors.New("a\n  b")); s != "a b" {
		t.Fatalf("shortErr: %q", s)
	}
}

func TestAccessLine(t *testing.T) {
	cases := []struct{ before, now, want string }{
		{"", "wait", "Waiting for your OK"},
		{"wait", "control", "Accepted (Control)"},
		{"", "view", "Ready (View only)"},
		{"view", "control", "Now Control"},
		{"control", "view", "Now View only"},
	}
	for _, c := range cases {
		if _, got := accessLine(c.before, c.now); !strings.HasPrefix(got, c.want) {
			t.Errorf("accessLine(%q, %q) = %q", c.before, c.now, got)
		}
	}
}
