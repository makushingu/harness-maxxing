package main

import (
	"fmt"
	"io"
	"math"
	"os"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

// The live log: Harness Link runs in the foreground of a terminal and prints what it does there, one short
// line per event or action, so the person sees what Claude does on this computer. Every line also goes to the
// log file; technical lines (logf) only go to the file.

type console struct {
	mu   sync.Mutex
	out  io.Writer
	file func(string, ...any)
}

func newConsole(out io.Writer, file func(string, ...any)) *console {
	return &console{out: out, file: file}
}

// say prints one line with the local time in front.
func (c *console) say(f string, a ...any) {
	msg := fmt.Sprintf(f, a...)
	if c.file != nil {
		c.file("%s", msg)
	}
	if c.out == nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	ts := time.Now().Format("15:04:05")
	for i, line := range strings.Split(msg, "\n") {
		if i > 0 {
			ts = "        "
		}
		fmt.Fprintf(c.out, "%s  %s\n", ts, line)
	}
}

const shownText = 80 // characters of typed text shown in the live log

// shortText quotes s for the live log, cut to n characters, control characters shown as spaces.
func shortText(s string, n int) string {
	var b strings.Builder
	count := 0
	for _, r := range s {
		if count == n {
			b.WriteString("…")
			break
		}
		if r < ' ' || r == 0x7f || r == utf8.RuneError {
			r = ' '
		}
		b.WriteRune(r)
		count++
	}
	return `"` + b.String() + `"`
}

func num(v *float64) string {
	if v == nil || math.IsNaN(*v) || math.IsInf(*v, 0) {
		return "?"
	}
	return fmt.Sprintf("%d", int(math.Round(*v)))
}

// describe is the live-log line of one request (empty: not shown).
func describe(r request) string {
	at := func() string { return num(r.X) + "," + num(r.Y) }
	switch r.T {
	case "shot":
		if r.Crop != nil {
			return fmt.Sprintf("Zoomed screenshot (%d,%d %dx%d)", int(r.Crop.X), int(r.Crop.Y), int(r.Crop.W), int(r.Crop.H))
		}
		return "Screenshot"
	case "apps":
		return "Listed the apps"
	case "open":
		return "Open app " + shortText(r.App, shownText)
	case "input":
		btn := ""
		if r.Button == "right" || r.Button == "middle" {
			btn = " (" + r.Button + " button)"
		}
		switch r.A {
		case "click":
			if r.Double {
				return "Double-click at " + at() + btn
			}
			return "Click at " + at() + btn
		case "long_press":
			return "Long press at " + at()
		case "move":
			return "Move the pointer to " + at()
		case "drag":
			return "Drag from " + at() + " to " + num(r.X2) + "," + num(r.Y2)
		case "scroll":
			dir := "down"
			switch {
			case r.DY < 0:
				dir = "up"
			case r.DY == 0 && r.DX < 0:
				dir = "left"
			case r.DY == 0 && r.DX > 0:
				dir = "right"
			}
			if r.X != nil && r.Y != nil {
				return "Scroll " + dir + " at " + at()
			}
			return "Scroll " + dir
		case "type":
			return "Type " + shortText(r.Text, shownText)
		case "key":
			return "Press " + shortText(r.Keys, shownText)
		}
		return "Input " + shortText(r.A, 20)
	}
	return ""
}

// stdoutConsole is the console of the running app (nil writer when stdout is not usable).
func stdoutConsole(file func(string, ...any)) *console {
	if fi, err := os.Stdout.Stat(); err != nil || fi == nil {
		return newConsole(nil, file)
	}
	return newConsole(os.Stdout, file)
}

// shortErr is an error for the live log: one line, not too long.
func shortErr(err error) string {
	if err == nil {
		return "stopped"
	}
	s := strings.Join(strings.Fields(err.Error()), " ")
	if utf8.RuneCountInString(s) > 300 {
		s = string([]rune(s)[:300]) + "…"
	}
	return s
}
