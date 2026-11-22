//go:build linux

package main

import (
	"errors"
	"fmt"
	"image"
	"io"
	"log"
	"os"
	"os/exec"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/randr"
	"github.com/jezek/xgb/xproto"
	"github.com/jezek/xgb/xtest"
)

// Linux: X11 only in this version, pure Go (xgb): capture with GetImage on the root window, input with XTEST.
// The app runs from a terminal of the graphical session, so DISPLAY / XAUTHORITY come from it.

const waylandNote = "This computer uses a Wayland session: screenshots and mouse / keyboard control are not " +
	"supported yet. Choose an X11 session at login (for example \"Ubuntu on Xorg\") to let Claude see and use it."

func init() { xgb.Logger = log.New(io.Discard, "", 0) }

type x11Backend struct {
	logf func(string, ...any)

	mu      sync.Mutex
	conn    *xgb.Conn
	root    xproto.Window
	setup   *xproto.SetupInfo
	visual  *xproto.VisualInfo
	depth   byte
	xtestOK bool
	randrOK bool
	want    int     // the screen chosen in Harness (-1: the primary one)
	cur     display // the screen used, in root-window pixels
	info    backendInfo
	infoAt  time.Time
	scratch map[xproto.Keycode]xproto.Keysym // spare keycodes remapped to type characters missing from the layout
	restore *time.Timer
}

func newBackend(dir string, logf func(string, ...any)) backend {
	return &x11Backend{logf: logf, scratch: map[xproto.Keycode]xproto.Keysym{}, want: -1}
}

func isWayland() bool {
	return os.Getenv("WAYLAND_DISPLAY") != "" || os.Getenv("XDG_SESSION_TYPE") == "wayland"
}

// connect opens the X connection if needed (called with mu held).
func (b *x11Backend) connect() error {
	if b.conn != nil {
		return nil
	}
	if os.Getenv("DISPLAY") == "" {
		return errors.New("no graphical session (DISPLAY is not set)")
	}
	c, err := xgb.NewConn()
	if err != nil {
		return err
	}
	setup := xproto.Setup(c)
	scr := setup.DefaultScreen(c)
	b.conn, b.setup, b.root, b.depth = c, setup, scr.Root, scr.RootDepth
	b.visual = nil
	for _, d := range scr.AllowedDepths {
		for i, v := range d.Visuals {
			if v.VisualId == scr.RootVisual {
				b.visual = &d.Visuals[i]
			}
		}
	}
	b.xtestOK = xtest.Init(c) == nil
	b.randrOK = randr.Init(c) == nil
	if !b.xtestOK {
		b.logf("X server without the XTEST extension: no input")
	}
	clear(b.scratch)
	return nil
}

// drop forgets a broken connection; the next request reconnects.
func (b *x11Backend) drop() {
	if b.conn != nil {
		b.conn.Close()
		b.conn = nil
	}
	b.infoAt = time.Time{}
}

func (b *x11Backend) Close() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.restoreScratch()
	b.drop()
}

func (b *x11Backend) Info() backendInfo {
	b.mu.Lock()
	defer b.mu.Unlock()
	if time.Since(b.infoAt) < 2*time.Second {
		return b.info
	}
	inf := backendInfo{Apps: true}
	if isWayland() {
		inf.Note, inf.Code = waylandNote, "unsupported"
	} else if err := b.connect(); err != nil {
		inf.Note, inf.Code = "Cannot reach the screen: "+err.Error()+".", "no_display"
	} else if g, err := xproto.GetGeometry(b.conn, xproto.Drawable(b.root)).Reply(); err != nil {
		b.drop()
		inf.Note, inf.Code = "Lost the connection to the screen.", "no_display"
	} else {
		inf.Displays = b.monitors(int(g.Width), int(g.Height))
		inf.Display = pickDisplay(inf.Displays, b.want)
		b.cur = inf.Displays[inf.Display]
		inf.Screen = &screenInfo{W: b.cur.W, H: b.cur.H, Scale: 1}
		inf.Input = b.xtestOK
		if !b.xtestOK {
			inf.Note, inf.Code = "The X server has no XTEST extension: Claude can see the screen but not use the mouse or keyboard.", "unsupported"
		}
	}
	b.info, b.infoAt = inf, time.Now()
	return inf
}

// monitors lists the screens with RandR 1.5 (one per monitor); without it, the whole root window is one screen.
func (b *x11Backend) monitors(rw, rh int) []display {
	whole := []display{{Name: "Screen", W: rw, H: rh, Main: true}}
	if !b.randrOK {
		return whole
	}
	rep, err := randr.GetMonitors(b.conn, b.root, true).Reply()
	if err != nil || rep == nil || len(rep.Monitors) == 0 {
		return whole
	}
	l := make([]display, 0, len(rep.Monitors))
	for i, m := range rep.Monitors {
		name := fmt.Sprintf("Screen %d", i+1)
		if a, err := xproto.GetAtomName(b.conn, m.Name).Reply(); err == nil && a.Name != "" {
			name = a.Name
		}
		x, y := max(0, int(m.X)), max(0, int(m.Y))
		w, h := min(int(m.Width), rw-x), min(int(m.Height), rh-y)
		if w <= 0 || h <= 0 {
			continue
		}
		l = append(l, display{Name: name, X: x, Y: y, W: w, H: h, Main: m.Primary})
	}
	if len(l) == 0 {
		return whole
	}
	return l
}

func (b *x11Backend) SetDisplay(i int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.want, b.infoAt = i, time.Time{}
}

func (b *x11Backend) Capture() (image.Image, error) {
	inf := b.Info()
	if inf.Screen == nil {
		return nil, &opError{"no_display", inf.Note}
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	if err := b.connect(); err != nil {
		return nil, &opError{"no_display", err.Error()}
	}
	w, h := inf.Screen.W, inf.Screen.H
	bpp, pad := 0, 32 // pad: scanline pad of the format
	for _, f := range b.setup.PixmapFormats {
		if f.Depth == b.depth {
			bpp, pad = int(f.BitsPerPixel), int(f.ScanlinePad)
		}
	}
	if b.visual == nil || (bpp != 32 && bpp != 24 && bpp != 16) {
		return nil, &opError{"unsupported", fmt.Sprintf("screen format not supported (depth %d, %d bpp)", b.depth, bpp)}
	}
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	bypp := bpp / 8
	stride := ((w*bpp + pad - 1) / pad) * pad / 8
	band := max(1, (4<<20)/max(stride, 1))
	msb := b.setup.ImageByteOrder == xproto.ImageOrderMSBFirst
	rm, gm, bm := b.visual.RedMask, b.visual.GreenMask, b.visual.BlueMask
	rs, gs, bs := maskShift(rm), maskShift(gm), maskShift(bm)
	rmax, gmax, bmax := rm>>rs, gm>>gs, bm>>bs
	for y0 := 0; y0 < h; y0 += band {
		bh := min(band, h-y0)
		rep, err := xproto.GetImage(b.conn, xproto.ImageFormatZPixmap, xproto.Drawable(b.root),
			int16(b.cur.X), int16(b.cur.Y+y0), uint16(w), uint16(bh), 0xffffffff).Reply()
		if err != nil {
			b.drop()
			return nil, &opError{"failed", "screen capture failed: " + err.Error()}
		}
		if len(rep.Data) < stride*bh {
			return nil, &opError{"failed", "short screen capture"}
		}
		for y := 0; y < bh; y++ {
			row := rep.Data[y*stride:]
			o := img.PixOffset(0, y0+y)
			for x := 0; x < w; x++ {
				p := row[x*bypp : x*bypp+bypp]
				var v uint32
				if msb {
					for _, c := range p {
						v = v<<8 | uint32(c)
					}
				} else {
					for i := len(p) - 1; i >= 0; i-- {
						v = v<<8 | uint32(p[i])
					}
				}
				img.Pix[o] = scale8((v&rm)>>rs, rmax)
				img.Pix[o+1] = scale8((v&gm)>>gs, gmax)
				img.Pix[o+2] = scale8((v&bm)>>bs, bmax)
				img.Pix[o+3] = 0xff
				o += 4
			}
		}
	}
	return img, nil
}

func maskShift(m uint32) uint32 {
	if m == 0 {
		return 0
	}
	s := uint32(0)
	for m&1 == 0 {
		m >>= 1
		s++
	}
	return s
}

func scale8(v, maxv uint32) uint8 {
	if maxv == 0 {
		return 0
	}
	if maxv == 255 {
		return uint8(v)
	}
	return uint8(v * 255 / maxv)
}

// fake sends one XTEST event and waits for the server to take it.
func (b *x11Backend) fake(typ, detail byte, x, y int16) error {
	if err := b.connect(); err != nil {
		return &opError{"no_display", err.Error()}
	}
	if !b.xtestOK {
		return &opError{"unsupported", "no XTEST extension"}
	}
	if err := xtest.FakeInputChecked(b.conn, typ, detail, 0, b.root, x, y, 0).Check(); err != nil {
		b.drop()
		return &opError{"failed", "input failed: " + err.Error()}
	}
	return nil
}

func (b *x11Backend) Move(x, y int) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.fake(xproto.MotionNotify, 0, int16(x+b.cur.X), int16(y+b.cur.Y))
}

func (b *x11Backend) Button(button string, down bool, _ int) error {
	d := map[string]byte{"left": 1, "middle": 2, "right": 3}[button]
	if d == 0 {
		return badRequest("unknown button %q", button)
	}
	typ := byte(xproto.ButtonRelease)
	if down {
		typ = xproto.ButtonPress
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.fake(typ, d, 0, 0)
}

func (b *x11Backend) Scroll(dx, dy int) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	click := func(btn byte, n int) error {
		for i := 0; i < n; i++ {
			if err := b.fake(xproto.ButtonPress, btn, 0, 0); err != nil {
				return err
			}
			if err := b.fake(xproto.ButtonRelease, btn, 0, 0); err != nil {
				return err
			}
			time.Sleep(8 * time.Millisecond)
		}
		return nil
	}
	axis := func(n int, neg, pos byte) error {
		if n < 0 {
			return click(neg, -n)
		}
		return click(pos, n)
	}
	if err := axis(dy, 4, 5); err != nil { // buttons 4/5 = up/down, 6/7 = left/right
		return err
	}
	return axis(dx, 6, 7)
}

// ---- keyboard ----

var x11Named = map[string]xproto.Keysym{
	"ctrl": 0xffe3, "shift": 0xffe1, "alt": 0xffe9, "cmd": 0xffeb,
	"enter": 0xff0d, "tab": 0xff09, "esc": 0xff1b, "backspace": 0xff08, "delete": 0xffff, "insert": 0xff63,
	"home": 0xff50, "end": 0xff57, "pageup": 0xff55, "pagedown": 0xff56,
	"left": 0xff51, "up": 0xff52, "right": 0xff53, "down": 0xff54,
	"space": 0x20, "capslock": 0xffe5, "printscreen": 0xff61, "menu": 0xff67,
}

// runeKeysym is the keysym of a character: Latin-1 as is, the rest as Unicode keysyms.
func runeKeysym(r rune) xproto.Keysym {
	if (r >= 0x20 && r <= 0x7e) || (r >= 0xa0 && r <= 0xff) {
		return xproto.Keysym(r)
	}
	if r == '€' {
		return 0x20ac
	}
	return xproto.Keysym(0x01000000 | uint32(r))
}

func keyNameKeysym(name string) (xproto.Keysym, bool) {
	if ks, ok := x11Named[name]; ok {
		return ks, true
	}
	if n := functionKey(name); n > 0 {
		return xproto.Keysym(0xffbe + n - 1), true
	}
	r := []rune(name)
	if len(r) == 1 {
		return runeKeysym(r[0]), true
	}
	return 0, false
}

type keymap struct {
	min  xproto.Keycode
	per  int
	syms []xproto.Keysym
}

func (b *x11Backend) keymap() (*keymap, error) {
	if err := b.connect(); err != nil {
		return nil, &opError{"no_display", err.Error()}
	}
	mn, mx := b.setup.MinKeycode, b.setup.MaxKeycode
	rep, err := xproto.GetKeyboardMapping(b.conn, mn, byte(int(mx)-int(mn)+1)).Reply()
	if err != nil {
		b.drop()
		return nil, &opError{"failed", "keyboard mapping: " + err.Error()}
	}
	return &keymap{min: mn, per: int(rep.KeysymsPerKeycode), syms: rep.Keysyms}, nil
}

// find returns the keycode producing ks in column 0 (shift = false) or 1 (shift = true).
func (m *keymap) find(ks xproto.Keysym) (xproto.Keycode, bool, bool) {
	if m.per == 0 {
		return 0, false, false
	}
	for col := 0; col < min(2, m.per); col++ {
		for i := 0; i+col < len(m.syms); i += m.per {
			if m.syms[i+col] == ks {
				return m.min + xproto.Keycode(i/m.per), col == 1, true
			}
		}
	}
	return 0, false, false
}

// free returns the keycodes without any keysym, highest first.
func (m *keymap) free() []xproto.Keycode {
	var l []xproto.Keycode
	for i := len(m.syms)/m.per - 1; i >= 0; i-- {
		empty := true
		for _, s := range m.syms[i*m.per : (i+1)*m.per] {
			if s != 0 {
				empty = false
				break
			}
		}
		if empty && m.min+xproto.Keycode(i) > 8 {
			l = append(l, m.min+xproto.Keycode(i))
		}
	}
	return l
}

// scratchFor maps ks on a spare keycode (or reuses one already mapped to it).
func (b *x11Backend) scratchFor(m *keymap, ks xproto.Keysym, avoid map[xproto.Keycode]bool) (xproto.Keycode, error) {
	for kc, s := range b.scratch {
		if s == ks {
			return kc, nil
		}
	}
	var pick xproto.Keycode
	for _, kc := range m.free() {
		if !avoid[kc] {
			if _, used := b.scratch[kc]; !used {
				pick = kc
				break
			}
		}
	}
	if pick == 0 { // every spare keycode holds a character typed just before: reuse the first one not needed now
		for kc := range b.scratch {
			if !avoid[kc] {
				pick = kc
				break
			}
		}
	}
	if pick == 0 {
		return 0, &opError{"failed", "no spare key to type this character"}
	}
	if err := xproto.ChangeKeyboardMappingChecked(b.conn, 1, pick, 2, []xproto.Keysym{ks, ks}).Check(); err != nil {
		return 0, &opError{"failed", "keyboard mapping: " + err.Error()}
	}
	_, _ = xproto.GetInputFocus(b.conn).Reply() // round trip: the mapping is in place
	b.scratch[pick] = ks
	time.Sleep(25 * time.Millisecond) // clients refresh their keymap on MappingNotify
	return pick, nil
}

// restoreScratch gives the spare keycodes back their empty mapping (called with mu held).
func (b *x11Backend) restoreScratch() {
	if b.restore != nil {
		b.restore.Stop()
		b.restore = nil
	}
	if b.conn == nil {
		clear(b.scratch)
		return
	}
	for kc := range b.scratch {
		_ = xproto.ChangeKeyboardMappingChecked(b.conn, 1, kc, 2, []xproto.Keysym{0, 0}).Check()
	}
	clear(b.scratch)
}

// scheduleRestore restores the spare keycodes 2 s after the last use (called with mu held).
func (b *x11Backend) scheduleRestore() {
	if len(b.scratch) == 0 {
		return
	}
	if b.restore != nil {
		b.restore.Stop()
	}
	b.restore = time.AfterFunc(2*time.Second, func() {
		b.mu.Lock()
		defer b.mu.Unlock()
		b.restoreScratch()
	})
}

func (b *x11Backend) keyEvent(kc xproto.Keycode, down bool) error {
	typ := byte(xproto.KeyRelease)
	if down {
		typ = xproto.KeyPress
	}
	return b.fake(typ, byte(kc), 0, 0)
}

func (b *x11Backend) Key(name string, down bool) error {
	ks, ok := keyNameKeysym(name)
	if !ok {
		return badRequest("unknown key %q", name)
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	m, err := b.keymap()
	if err != nil {
		return err
	}
	kc, _, found := m.find(ks)
	if !found {
		if kc, err = b.scratchFor(m, ks, nil); err != nil {
			return err
		}
	}
	defer b.scheduleRestore()
	return b.keyEvent(kc, down)
}

func (b *x11Backend) Text(s string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	m, err := b.keymap()
	if err != nil {
		return err
	}
	defer b.scheduleRestore()
	shiftKC, _, haveShift := m.find(0xffe1)
	var prev xproto.Keycode
	for _, r := range s {
		var ks xproto.Keysym
		switch r {
		case '\r':
			continue
		case '\n':
			ks = 0xff0d
		case '\t':
			ks = 0xff09
		default:
			ks = runeKeysym(r)
		}
		kc, shift, found := m.find(ks)
		if found && shift && !haveShift {
			found = false
		}
		if !found {
			shift = false
			if kc, err = b.scratchFor(m, ks, map[xproto.Keycode]bool{prev: true}); err != nil {
				return err
			}
		}
		if shift {
			if err := b.keyEvent(shiftKC, true); err != nil {
				return err
			}
		}
		err := b.keyEvent(kc, true)
		if err == nil {
			err = b.keyEvent(kc, false)
		}
		if shift {
			_ = b.keyEvent(shiftKC, false)
		}
		if err != nil {
			return err
		}
		prev = kc
		time.Sleep(3 * time.Millisecond)
	}
	return nil
}

// ---- apps ----

func (b *x11Backend) Apps() ([]app, error) { return desktopApps(xdgAppDirs()), nil }

// Launch starts the Exec line of a listed .desktop file, detached from the app (own session, no stdio).
func (b *x11Backend) Launch(a app) error {
	f, err := os.Open(a.target)
	if err != nil {
		return &opError{"not_found", "app file is gone"}
	}
	e, ok := parseDesktopFile(io.LimitReader(f, 256<<10))
	f.Close()
	if !ok {
		return &opError{"not_found", "app cannot be started"}
	}
	argv, err := parseExec(e.Exec)
	if err != nil {
		return &opError{"failed", "bad Exec line: " + err.Error()}
	}
	path := argv[0]
	if !strings.Contains(path, "/") {
		if path, err = exec.LookPath(path); err != nil {
			return &opError{"not_found", argv[0] + " is not installed"}
		}
	}
	cmd := exec.Command(path, argv[1:]...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if h, err := os.UserHomeDir(); err == nil {
		cmd.Dir = h
	}
	if err := cmd.Start(); err != nil {
		return &opError{"failed", "cannot start " + a.Name + ": " + err.Error()}
	}
	go cmd.Wait() // reap it; it is not ours to stop
	return nil
}

// secureInput: no system-wide "password field focused" signal here; the live log shows typed text (cut).
func secureInput() bool { return false }
