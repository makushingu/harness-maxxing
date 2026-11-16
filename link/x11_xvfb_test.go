//go:build xvfb && linux

// Real X11 test (not part of `go test`): starts Xvfb and an xterm, then drives them with the X11 backend.
//
//	go test -tags xvfb -run X11 -v      # needs Xvfb and xterm (apt install xvfb xterm)
package main

import (
	"bytes"
	"fmt"
	"image/jpeg"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/xproto"
)

// startXvfb starts Xvfb :77 (1280x800) and points DISPLAY at it.
func startXvfb(t *testing.T) {
	const display = ":77"
	xvfb := exec.Command("Xvfb", display, "-screen", "0", "1280x800x24", "-nolisten", "tcp")
	if err := xvfb.Start(); err != nil {
		t.Skipf("Xvfb: %v", err)
	}
	t.Cleanup(func() { xvfb.Process.Kill(); xvfb.Wait() })
	t.Setenv("DISPLAY", display)
	t.Setenv("WAYLAND_DISPLAY", "")
	t.Setenv("XDG_SESSION_TYPE", "x11")
	deadline := time.Now().Add(10 * time.Second)
	for {
		c, err := xgb.NewConn()
		if err == nil {
			c.Close()
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("Xvfb did not start: %v", err)
		}
		time.Sleep(100 * time.Millisecond)
	}
}

func TestX11Real(t *testing.T) {
	startXvfb(t)
	out := filepath.Join(t.TempDir(), "typed.txt")
	term := exec.Command("xterm", "-u8", "-geometry", "100x30+0+0", "-e", "sh", "-c", `IFS= read -r line; printf %s "$line" > "$0"`, out)
	term.Env = append(os.Environ(), "LANG=C.UTF-8", "LC_ALL=C.UTF-8")
	if err := term.Start(); err != nil {
		t.Skipf("xterm: %v", err)
	}
	t.Cleanup(func() { term.Process.Kill(); term.Wait() })
	time.Sleep(1500 * time.Millisecond)

	be := newBackend(t.TempDir(), testLog)
	defer be.Close()
	inf := be.Info()
	if inf.Screen == nil || inf.Screen.W != 1280 || inf.Screen.H != 800 || !inf.Input || inf.Note != "" {
		t.Fatalf("info %+v %+v", inf, inf.Screen)
	}

	// screenshot: real size, downscaled copy, not uniform (the xterm is drawn on the black root)
	s, err := doShot(be, 640, 70, nil, 0, 0)
	if err != nil {
		t.Fatal(err)
	}
	if s.W != 640 || s.H != 400 || s.SW != 1280 || s.SH != 800 {
		t.Fatalf("shot %dx%d of %dx%d", s.W, s.H, s.SW, s.SH)
	}
	img, err := jpeg.Decode(bytes.NewReader(s.JPEG))
	if err != nil {
		t.Fatal(err)
	}
	r1, g1, b1, _ := img.At(50, 50).RGBA()   // inside the xterm (white background)
	r2, g2, b2, _ := img.At(630, 390).RGBA() // the bare root window (black)
	if r1>>8 < 200 || g1>>8 < 200 || b1>>8 < 200 || r2>>8 > 50 || g2>>8 > 50 || b2>>8 > 50 {
		t.Fatalf("unexpected pixels: xterm %d,%d,%d root %d,%d,%d", r1>>8, g1>>8, b1>>8, r2>>8, g2>>8, b2>>8)
	}
	os.WriteFile(filepath.Join(os.TempDir(), "harness-link-xvfb.jpg"), s.JPEG, 0o600)

	// a click given in capture space (640x400) lands on the real screen (1280x800)
	x, y := 160.0, 100.0
	if err := doInput(be, request{A: "click", X: &x, Y: &y, SW: 640, SH: 400}); err != nil {
		t.Fatal(err)
	}
	c, _ := xgb.NewConn()
	defer c.Close()
	root := xproto.Setup(c).DefaultScreen(c).Root
	p, err := xproto.QueryPointer(c, root).Reply()
	if err != nil || p.RootX != 320 || p.RootY != 200 {
		t.Fatalf("pointer at %d,%d (%v), want 320,200", p.RootX, p.RootY, err)
	}

	// typing reaches the xterm: ASCII, Latin-1 (shift), characters missing from the layout, then keys
	text := "Hello World-42 é€ñ 你好 xyz"
	if err := doInput(be, request{A: "type", Text: text}); err != nil {
		t.Fatal(err)
	}
	if err := doInput(be, request{A: "key", Keys: "backspace enter"}); err != nil {
		t.Fatal(err)
	}
	want := "Hello World-42 é€ñ 你好 xy"
	deadline := time.Now().Add(5 * time.Second)
	for {
		b, _ := os.ReadFile(out)
		if string(b) == want {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("xterm got %q, want %q", b, want)
		}
		time.Sleep(100 * time.Millisecond)
	}

	// scroll and drag run without error; the spare keycodes are given back
	if err := doInput(be, request{A: "scroll", DY: 2}); err != nil {
		t.Fatal(err)
	}
	x2, y2 := 300.0, 300.0
	if err := doInput(be, request{A: "drag", X: &x, Y: &y, X2: &x2, Y2: &y2, MS: 100}); err != nil {
		t.Fatal(err)
	}
	if p, _ := xproto.QueryPointer(c, root).Reply(); p.RootX != 300 || p.RootY != 300 {
		t.Fatalf("after drag pointer at %d,%d", p.RootX, p.RootY)
	}
	time.Sleep(2500 * time.Millisecond)
	xb := be.(*x11Backend)
	xb.mu.Lock()
	left := len(xb.scratch)
	xb.mu.Unlock()
	if left != 0 {
		t.Fatalf("%d spare keycodes still remapped", left)
	}
}

// TestX11Binary runs the real binary, paired by a trailer appended like the server does, against the fake server.
func TestX11Binary(t *testing.T) {
	startXvfb(t)
	tmp := t.TempDir()
	bin := filepath.Join(tmp, "harness-link")
	if out, err := exec.Command("go", "build", "-o", bin+".plain", ".").CombinedOutput(); err != nil {
		t.Fatalf("build: %v %s", err, out)
	}
	fs := newFakeServer(t)
	if out, err := exec.Command("go", "run", "./tools/stamp", bin+".plain", bin, fs.URL, "GOOD").CombinedOutput(); err != nil {
		t.Fatalf("stamp: %v %s", err, out)
	}
	cmd := exec.Command(bin)
	cmd.Env = append(os.Environ(), "HARNESS_LINK_CONFIG_DIR="+filepath.Join(tmp, "cfg"), "HARNESS_LINK_NO_INSTALL=1")
	if testing.Verbose() {
		cmd.Stderr = os.Stderr
	}
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { cmd.Process.Kill(); cmd.Wait() })
	c := fs.next(t)
	h := c.recv(t)
	if h["t"] != "hello" || fmt.Sprint(h["caps"]) != "[screen input apps]" || fmt.Sprint(h["screen"]) != "map[h:800 scale:1 w:1280]" {
		t.Fatalf("hello %v", h)
	}
	m := c.call(t, map[string]any{"t": "shot", "max_w": 640})
	if m["t"] != "ok" || m["w"] != 640.0 || m["h"] != 400.0 || m["sw_screen"] != 1280.0 {
		t.Fatalf("shot %v %v %v", m["t"], m["w"], m["code"])
	}
	m = c.call(t, map[string]any{"t": "input", "a": "click", "x": 100, "y": 50, "sw": 640, "sh": 400})
	if m["t"] != "ok" {
		t.Fatalf("click %v", m)
	}
	x, _ := xgb.NewConn()
	defer x.Close()
	p, _ := xproto.QueryPointer(x, xproto.Setup(x).DefaultScreen(x).Root).Reply()
	if p.RootX != 200 || p.RootY != 100 {
		t.Fatalf("pointer at %d,%d, want 200,100", p.RootX, p.RootY)
	}
	if m := c.call(t, map[string]any{"t": "apps"}); m["t"] != "ok" {
		t.Fatalf("apps %v", m)
	}
}

// Two monitors side by side (RandR 1.5 monitors on one 2560x800 root): the second one is captured and the
// pointer lands on it.
func TestX11TwoScreens(t *testing.T) {
	const display = ":78"
	xvfb := exec.Command("Xvfb", display, "-screen", "0", "2560x800x24", "-nolisten", "tcp")
	if err := xvfb.Start(); err != nil {
		t.Skipf("Xvfb: %v", err)
	}
	t.Cleanup(func() { xvfb.Process.Kill(); xvfb.Wait() })
	t.Setenv("DISPLAY", display)
	t.Setenv("WAYLAND_DISPLAY", "")
	t.Setenv("XDG_SESSION_TYPE", "x11")
	time.Sleep(time.Second)
	for _, args := range [][]string{
		{"--setmonitor", "LEFT", "1280/340x800/210+0+0", "none"},
		{"--setmonitor", "RIGHT", "1280/340x800/210+1280+0", "none"},
		{"--output", "screen", "--primary"},
	} {
		if out, err := exec.Command("xrandr", args...).CombinedOutput(); err != nil {
			t.Logf("xrandr %v: %v %s", args, err, out)
		}
	}
	be := newBackend(t.TempDir(), testLog)
	defer be.Close()
	inf := be.Info()
	if len(inf.Displays) < 2 {
		t.Skipf("RandR monitors not available here: %+v", inf.Displays)
	}
	t.Logf("screens: %+v (using %d)", inf.Displays, inf.Display)
	right := -1
	for i, d := range inf.Displays {
		if d.X == 1280 {
			right = i
		}
	}
	if right < 0 {
		t.Fatalf("no screen at x=1280: %+v", inf.Displays)
	}
	be.SetDisplay(right)
	inf = be.Info()
	if inf.Display != right || inf.Screen.W != 1280 || inf.Screen.H != 800 {
		t.Fatalf("after SetDisplay: %+v", inf)
	}
	img, err := be.Capture()
	if err != nil || img.Bounds().Dx() != 1280 {
		t.Fatalf("capture: %v %v", err, img)
	}
	if err := be.Move(100, 50); err != nil {
		t.Fatal(err)
	}
	c, _ := xgb.NewConn()
	defer c.Close()
	p, err := xproto.QueryPointer(c, xproto.Setup(c).DefaultScreen(c).Root).Reply()
	if err != nil || p.RootX != 1380 || p.RootY != 50 {
		t.Fatalf("pointer at %d,%d (want 1380,50): %v", p.RootX, p.RootY, err)
	}
}
