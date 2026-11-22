package main

import (
	"fmt"
	"io"
	"math"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

// The live log: Harness Link runs in the foreground of a terminal and prints what it does there, one short
// line per event or action, so the person sees what Claude does on this computer. Every line also goes to the
// log file; technical lines (logf) only go to the file.
//
// In a real terminal the log is styled (colours, a header, one symbol per kind of line, repeated actions folded
// into one line with a counter). Written to a file or a pipe, or with NO_COLOR set, it stays plain text. The
// symbols are all in the WGL4 set, so the Windows console fonts draw them too.

type lineKind int

const (
	lInfo       lineKind = iota // neutral
	lOK                         // connected, accepted
	lWarn                       // a permission is missing, the server cannot be reached
	lErr                        // stopped, removed
	lClaude                     // Claude takes or leaves this computer
	lAction                     // one action of Claude, done
	lActionFail                 // one action of Claude, refused
)

type console struct {
	mu    sync.Mutex
	out   io.Writer
	file  func(string, ...any)
	tty   bool // a terminal: lines can be rewritten (folded repeats)
	color bool

	last  string // the last action line, to fold repeats
	count int
}

func newConsole(out io.Writer, file func(string, ...any)) *console {
	return &console{out: out, file: file}
}

const (
	cReset  = "\x1b[0m"
	cBold   = "\x1b[1m"
	cDim    = "\x1b[2m"
	cAccent = "\x1b[38;5;141m"
	cGreen  = "\x1b[38;5;114m"
	cYellow = "\x1b[38;5;221m"
	cRed    = "\x1b[38;5;203m"
	cGray   = "\x1b[38;5;245m"
)

func (c *console) paint(code, s string) string {
	if !c.color || s == "" {
		return s
	}
	return code + s + cReset
}

func kindStyle(k lineKind) (symbol, color string) {
	switch k {
	case lOK:
		return "●", cGreen
	case lWarn:
		return "▲", cYellow
	case lErr:
		return "■", cRed
	case lClaude:
		return "♦", cAccent
	case lAction:
		return "›", cAccent
	case lActionFail:
		return "×", cRed
	}
	return "·", cGray
}

// emit prints one line of the given kind.
func (c *console) emit(k lineKind, msg string) {
	if c.file != nil {
		c.file("%s", msg)
	}
	if c.out == nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	ts := time.Now().Format("15:04:05")
	if !c.color && !c.tty {
		for i, line := range strings.Split(msg, "\n") {
			if i > 0 {
				ts = "        "
			}
			fmt.Fprintf(c.out, "%s  %s\n", ts, line)
		}
		return
	}
	if k == lAction && c.tty && msg == c.last {
		c.count++
		// back to the previous line and print it again with the counter
		fmt.Fprintf(c.out, "\x1b[1A\r\x1b[2K%s\n", c.line(ts, k, msg, c.count))
		return
	}
	c.last, c.count = "", 0
	if k == lAction {
		c.last, c.count = msg, 1
	}
	fmt.Fprintf(c.out, "%s\n", c.line(ts, k, msg, 1))
}

func (c *console) line(ts string, k lineKind, msg string, n int) string {
	sym, col := kindStyle(k)
	tc := textColor(k, col)
	lines := strings.Split(msg, "\n")
	var b strings.Builder
	b.WriteString("  " + c.paint(cDim, ts) + "  " + c.paint(col, sym) + " " + c.paint(tc, lines[0]))
	for _, l := range lines[1:] {
		b.WriteString("\n             " + c.paint(tc, l))
	}
	if n > 1 {
		b.WriteString(c.paint(cDim, fmt.Sprintf("  ×%d", n)))
	}
	return b.String()
}

func textColor(k lineKind, col string) string {
	switch k {
	case lAction, lInfo:
		return ""
	case lClaude:
		return cBold + col
	}
	return col
}

// logo is "LINK" in big letters, as the Harness Maxxing installer writes "MAXXING" (same blues, top to bottom).
var logo = [...]string{
	"██╗     ██╗███╗   ██╗██╗  ██╗",
	"██║     ██║████╗  ██║██║ ██╔╝",
	"██║     ██║██╔██╗ ██║█████╔╝ ",
	"██║     ██║██║╚██╗██║██╔═██╗ ",
	"███████╗██║██║ ╚████║██║  ██╗",
	"╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝",
}

var logoBlues = [...]int{27, 33, 39, 45, 51, 87}

// header is what Harness Link prints when it starts (only in a terminal): the logo, then how it works.
func (c *console) header() {
	if c.out == nil || (!c.tty && !c.color) {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	fmt.Fprintln(c.out)
	if c.color && termWidth() >= 34 && os.Getenv("HARNESS_LINK_NO_LOGO") == "" { // the install script just showed it
		fmt.Fprintln(c.out, "  "+c.paint(cBold+"\x1b[38;5;75m", "H A R N E S S"))
		for i, l := range logo {
			fmt.Fprintln(c.out, "  "+c.paint(fmt.Sprintf("\x1b[38;5;%dm", logoBlues[i]), l))
		}
	} else {
		fmt.Fprintln(c.out, "  "+c.paint(cBold, "HARNESS LINK"))
	}
	fmt.Fprintln(c.out, "  "+c.paint(cDim, "v"+version+" · Claude can use this computer while this window stays open"))
	fmt.Fprintln(c.out, "  "+c.paint(cDim, "Ctrl+C stops it"))
	fmt.Fprintln(c.out)
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
	fi, err := os.Stdout.Stat()
	if err != nil || fi == nil {
		return newConsole(nil, file)
	}
	c := newConsole(os.Stdout, file)
	if fi.Mode()&os.ModeCharDevice != 0 && os.Getenv("TERM") != "dumb" {
		c.tty = enableANSI(os.Stdout) // Windows: virtual terminal mode of the console
		c.color = c.tty && os.Getenv("NO_COLOR") == ""
	}
	return c
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

// logSay sends the live log to the log file only (tests, no terminal).
func logSay(logf func(string, ...any)) func(lineKind, string) {
	return func(_ lineKind, m string) { logf("%s", m) }
}

// hostOf is the host of the server URL, for the live log.
func hostOf(server string) string {
	if u, err := url.Parse(server); err == nil && u.Host != "" {
		return u.Host
	}
	return server
}
