//go:build darwin

package main

import (
	"errors"
	"fmt"
	"image"
	"image/jpeg"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
	"unicode/utf16"
	"unsafe"

	"github.com/ebitengine/purego"
)

// macOS: screenshots with /usr/sbin/screencapture (the chosen display, -D n), input with CoreGraphics events posted to the
// HID event tap (needs the Accessibility permission), keyboard layout read with UCKeyTranslate. No cgo: purego.

const (
	cgPath   = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
	cfPath   = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
	axPath   = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
	tisPath  = "/System/Library/Frameworks/Carbon.framework/Carbon"
	paneScr  = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
	paneAX   = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
	shotTool = "/usr/sbin/screencapture"
)

type cgPoint struct{ X, Y float64 }

type cgRect struct{ X, Y, W, H float64 } // CGRect: origin then size, in global points

var (
	cgMainDisplayID               func() uint32
	cgGetActiveDisplayList        func(max uint32, ids *uint32, n *uint32) int32
	cgDisplayBounds               func(uint32) cgRect
	cgDisplayIsBuiltin            func(uint32) uint32
	cgDisplayPixelsWide           func(uint32) uintptr
	cgDisplayPixelsHigh           func(uint32) uintptr
	cgDisplayCopyDisplayMode      func(uint32) uintptr
	cgDisplayModeGetPixelWidth    func(uintptr) uintptr
	cgDisplayModeGetPixelHeight   func(uintptr) uintptr
	cgDisplayModeRelease          func(uintptr)
	cgPreflightScreenCaptureAcc   func() bool
	cgRequestScreenCaptureAcc     func() bool
	cgRequestPostEventAccess      func() bool
	cgEventCreateMouseEvent       func(src uintptr, typ uint32, pt cgPoint, button uint32) uintptr
	cgEventCreateKeyboardEvent    func(src uintptr, key uint16, down bool) uintptr
	cgEventKeyboardSetUnicodeStr  func(ev uintptr, n uintptr, s *uint16)
	cgEventSetFlags               func(ev uintptr, flags uint64)
	cgEventSetIntegerValueField   func(ev uintptr, field uint32, v int64)
	cgEventCreateScrollWheelEvent func(src uintptr, units uint32, count uint32, w1, w2, w3 int32) uintptr
	cgEventPost                   func(tap uint32, ev uintptr)
	cfRelease                     func(uintptr)
	cfDataGetBytePtr              func(uintptr) uintptr
	axIsProcessTrusted            func() bool
	tisCopyCurrentKeyboardLayout  func() uintptr
	tisCopyCurrentASCIILayout     func() uintptr
	tisGetInputSourceProperty     func(src, key uintptr) uintptr
	lmGetKbdType                  func() uint8
	isSecureEventInputEnabled     func() uint8
	ucKeyTranslate                func(layout uintptr, code, action uint16, mods, kbdType, opts uint32, dead *uint32, max uintptr, n *uintptr, out *uint16) int32
	tisUnicodeLayoutKey           uintptr

	cgLoadErr  error
	cgLoadOnce sync.Once
)

// optional registers fn if the symbol exists (older macOS lack some of them).
func optional(lib uintptr, fn any, name string) {
	if _, err := purego.Dlsym(lib, name); err == nil {
		purego.RegisterLibFunc(fn, lib, name)
	}
}

// deref reads the pointer stored at address p (a global variable of a framework).
func deref(p uintptr) uintptr { return **(**uintptr)(unsafe.Pointer(&p)) }

func loadCG() error {
	cgLoadOnce.Do(func() {
		cg, err := purego.Dlopen(cgPath, purego.RTLD_NOW|purego.RTLD_GLOBAL)
		if err != nil {
			cgLoadErr = err
			return
		}
		cf, err := purego.Dlopen(cfPath, purego.RTLD_NOW|purego.RTLD_GLOBAL)
		if err != nil {
			cgLoadErr = err
			return
		}
		purego.RegisterLibFunc(&cgMainDisplayID, cg, "CGMainDisplayID")
		optional(cg, &cgGetActiveDisplayList, "CGGetActiveDisplayList")
		optional(cg, &cgDisplayBounds, "CGDisplayBounds")
		optional(cg, &cgDisplayIsBuiltin, "CGDisplayIsBuiltin")
		purego.RegisterLibFunc(&cgDisplayPixelsWide, cg, "CGDisplayPixelsWide")
		purego.RegisterLibFunc(&cgDisplayPixelsHigh, cg, "CGDisplayPixelsHigh")
		purego.RegisterLibFunc(&cgDisplayCopyDisplayMode, cg, "CGDisplayCopyDisplayMode")
		purego.RegisterLibFunc(&cgDisplayModeGetPixelWidth, cg, "CGDisplayModeGetPixelWidth")
		purego.RegisterLibFunc(&cgDisplayModeGetPixelHeight, cg, "CGDisplayModeGetPixelHeight")
		purego.RegisterLibFunc(&cgDisplayModeRelease, cg, "CGDisplayModeRelease")
		purego.RegisterLibFunc(&cgEventCreateMouseEvent, cg, "CGEventCreateMouseEvent")
		purego.RegisterLibFunc(&cgEventCreateKeyboardEvent, cg, "CGEventCreateKeyboardEvent")
		purego.RegisterLibFunc(&cgEventKeyboardSetUnicodeStr, cg, "CGEventKeyboardSetUnicodeString")
		purego.RegisterLibFunc(&cgEventSetFlags, cg, "CGEventSetFlags")
		purego.RegisterLibFunc(&cgEventSetIntegerValueField, cg, "CGEventSetIntegerValueField")
		purego.RegisterLibFunc(&cgEventCreateScrollWheelEvent, cg, "CGEventCreateScrollWheelEvent2")
		purego.RegisterLibFunc(&cgEventPost, cg, "CGEventPost")
		optional(cg, &cgPreflightScreenCaptureAcc, "CGPreflightScreenCaptureAccess")
		optional(cg, &cgRequestScreenCaptureAcc, "CGRequestScreenCaptureAccess")
		optional(cg, &cgRequestPostEventAccess, "CGRequestPostEventAccess")
		purego.RegisterLibFunc(&cfRelease, cf, "CFRelease")
		purego.RegisterLibFunc(&cfDataGetBytePtr, cf, "CFDataGetBytePtr")
		if ax, err := purego.Dlopen(axPath, purego.RTLD_NOW|purego.RTLD_GLOBAL); err == nil {
			optional(ax, &axIsProcessTrusted, "AXIsProcessTrusted")
		}
		if tis, err := purego.Dlopen(tisPath, purego.RTLD_NOW|purego.RTLD_GLOBAL); err == nil {
			optional(tis, &tisCopyCurrentKeyboardLayout, "TISCopyCurrentKeyboardLayoutInputSource")
			optional(tis, &tisCopyCurrentASCIILayout, "TISCopyCurrentASCIICapableKeyboardLayoutInputSource")
			optional(tis, &tisGetInputSourceProperty, "TISGetInputSourceProperty")
			optional(tis, &lmGetKbdType, "LMGetKbdType")
			optional(tis, &isSecureEventInputEnabled, "IsSecureEventInputEnabled")
			optional(tis, &ucKeyTranslate, "UCKeyTranslate")
			if p, err := purego.Dlsym(tis, "kTISPropertyUnicodeKeyLayoutData"); err == nil {
				tisUnicodeLayoutKey = deref(p)
			}
		}
	})
	return cgLoadErr
}

type macBackend struct {
	dir  string
	logf func(string, ...any)

	mu      sync.Mutex
	pos     cgPoint // last pointer position (points)
	pressed string  // button held down (drag events)
	mods    uint64  // modifier flags held by Key
	asked   map[string]bool
	want    atomic.Int32 // the screen chosen in Harness (-1: the main one)
}

func newBackend(dir string, logf func(string, ...any)) backend {
	if err := loadCG(); err != nil {
		logf("CoreGraphics: %v", err)
	}
	b := &macBackend{dir: dir, logf: logf, asked: map[string]bool{}}
	b.want.Store(-1)
	return b
}

func (b *macBackend) Close() {}

// macScreen is one active display: its id, its place in global points and its size in pixels.
type macScreen struct {
	id     uint32
	bounds cgRect
	pw, ph int
}

// screens lists the active displays, the main one first (the order screencapture -D numbers them in), and the
// index of the one to use.
func (b *macBackend) screens() ([]macScreen, []display, int) {
	var buf [16]uint32
	var n uint32
	if cgGetActiveDisplayList == nil || cgGetActiveDisplayList(uint32(len(buf)), &buf[0], &n) != 0 || n == 0 {
		buf[0], n = cgMainDisplayID(), 1
	}
	main := cgMainDisplayID()
	var ms []macScreen
	var ds []display
	ext := 0
	for _, id := range buf[:n] {
		pw, ph, ptw, pth := geometry(id)
		r := cgRect{W: ptw, H: pth}
		if cgDisplayBounds != nil {
			r = cgDisplayBounds(id)
		}
		name := "Built-in display"
		if cgDisplayIsBuiltin == nil || cgDisplayIsBuiltin(id) == 0 {
			ext++
			name = fmt.Sprintf("Display %d", ext)
		}
		ms = append(ms, macScreen{id: id, bounds: r, pw: pw, ph: ph})
		ds = append(ds, display{Name: name, X: int(r.X), Y: int(r.Y), W: pw, H: ph, Main: id == main})
	}
	return ms, ds, pickDisplay(ds, int(b.want.Load()))
}

func (b *macBackend) SetDisplay(i int) { b.want.Store(int32(i)) }

// geometry returns a display in pixels and in points.
func geometry(id uint32) (pw, ph int, ptw, pth float64) {
	ptw, pth = float64(cgDisplayPixelsWide(id)), float64(cgDisplayPixelsHigh(id))
	pw, ph = int(ptw), int(pth)
	if m := cgDisplayCopyDisplayMode(id); m != 0 {
		if w, h := int(cgDisplayModeGetPixelWidth(m)), int(cgDisplayModeGetPixelHeight(m)); w > 0 && h > 0 {
			pw, ph = w, h
		}
		cgDisplayModeRelease(m)
	}
	return
}

func screenAllowed() bool {
	if cgPreflightScreenCaptureAcc == nil {
		return true // before macOS 10.15
	}
	var ok bool
	runOnMain(func() { ok = cgPreflightScreenCaptureAcc() })
	return ok
}

func inputAllowed() bool {
	if axIsProcessTrusted == nil {
		return false
	}
	var ok bool
	runOnMain(func() { ok = axIsProcessTrusted() })
	return ok
}

// askOnce opens the System Settings pane of a missing permission once per run (each time Harness Link is
// started while it is missing), after asking macOS to add the terminal app to that list.
func (b *macBackend) askOnce(what, pane string, request func() bool) {
	if b.asked[what] || b.dir == "" {
		return
	}
	b.asked[what] = true
	if request != nil {
		runOnMain(func() { request() })
	}
	if err := exec.Command("/usr/bin/open", pane).Run(); err != nil {
		b.logf("cannot open System Settings: %v", err)
	}
}

// terminalApp is the app macOS gives the permissions to: the terminal Harness Link was started from.
func terminalApp() string {
	switch os.Getenv("TERM_PROGRAM") {
	case "Apple_Terminal":
		return "Terminal"
	case "iTerm.app":
		return "iTerm"
	case "WarpTerminal":
		return "Warp"
	case "vscode":
		return "Visual Studio Code"
	case "ghostty":
		return "Ghostty"
	case "WezTerm":
		return "WezTerm"
	case "Hyper":
		return "Hyper"
	case "Tabby":
		return "Tabby"
	}
	if os.Getenv("__CFBundleIdentifier") == "com.apple.Terminal" {
		return "Terminal"
	}
	return "your terminal app"
}

func screenOffText() string {
	t := terminalApp()
	return "Screen Recording is off for " + t + ": Claude cannot see the screen. In System Settings > Privacy & " +
		"Security > Screen Recording, turn on " + t + ", quit " + t + " (cmd+Q), open it again and type harness-link."
}

func (b *macBackend) Info() backendInfo {
	inf := backendInfo{Apps: true}
	if cgLoadErr != nil {
		inf.Note, inf.Code = "CoreGraphics is not available: "+cgLoadErr.Error(), "unsupported"
		return inf
	}
	ms, ds, i := b.screens()
	cur := ms[i]
	if cur.pw <= 0 || cur.ph <= 0 || cur.bounds.W <= 0 {
		inf.Note, inf.Code = "No display found.", "no_display"
		return inf
	}
	inf.Displays, inf.Display = ds, i
	inf.Screen = &screenInfo{W: cur.pw, H: cur.ph, Scale: float64(cur.pw) / cur.bounds.W}
	inf.Input = inputAllowed()
	var notes []string
	b.mu.Lock()
	defer b.mu.Unlock()
	scr := screenAllowed()
	t := terminalApp()
	switch {
	case !scr && !inf.Input:
		notes = append(notes, "Screen Recording and Accessibility are off for "+t+": Claude cannot see the screen "+
			"nor use the mouse or keyboard. In System Settings > Privacy & Security, turn on "+t+" under Screen "+
			"Recording and under Accessibility, quit "+t+" (cmd+Q), open it again and type harness-link.")
	case !scr:
		notes = append(notes, screenOffText())
	case !inf.Input:
		notes = append(notes, "Accessibility is off for "+t+": Claude cannot use the mouse or keyboard. In System "+
			"Settings > Privacy & Security > Accessibility, turn on "+t+", quit "+t+" (cmd+Q), open it again and "+
			"type harness-link.")
	}
	if !inf.Input {
		inf.Code = "permission"
		b.askOnce("accessibility", paneAX, cgRequestPostEventAccess)
	}
	if !scr {
		b.askOnce("screen", paneScr, cgRequestScreenCaptureAcc)
	}
	inf.Note = strings.Join(notes, " ")
	return inf
}

func (b *macBackend) Capture() (image.Image, error) {
	// screencapture is given a path that does not exist yet, in a private folder of its own: it can silently
	// write nothing over a file created beforehand (an empty temp file) or a hidden name.
	tmp, err := os.MkdirTemp("", "harness-link-shot-")
	if err != nil {
		return nil, &opError{"failed", err.Error()}
	}
	defer os.RemoveAll(tmp)
	name := filepath.Join(tmp, "screen.jpg")
	// -x no sound, -m main display (-D n: display n, 1 = main), -t jpg
	args := []string{"-x", "-m", "-t", "jpg", name}
	if ms, _, i := b.screens(); len(ms) > 1 {
		args = []string{"-x", "-D", strconv.Itoa(i + 1), "-t", "jpg", name}
	}
	out, err := exec.Command(shotTool, args...).CombinedOutput()
	if err != nil {
		return nil, &opError{"failed", "screencapture: " + strings.TrimSpace(string(out)+" "+err.Error())}
	}
	if msg := strings.TrimSpace(string(out)); msg != "" {
		b.logf("screencapture: %s", msg)
	}
	// Without Screen Recording, screencapture can exit 0 and write nothing.
	if st, err := os.Stat(name); err != nil || st.Size() == 0 {
		if !screenAllowed() {
			return nil, &opError{"permission", screenOffText()}
		}
		return nil, &opError{"failed", "macOS gave no screenshot (screen locked, or Screen Recording off for " +
			terminalApp() + ")"}
	}
	r, err := os.Open(name)
	if err != nil {
		return nil, &opError{"failed", err.Error()}
	}
	defer r.Close()
	img, err := jpeg.Decode(r)
	if err != nil {
		return nil, &opError{"failed", "no screenshot (screen locked or Screen Recording off for " + terminalApp() + "?)"}
	}
	return img, nil
}

// ---- input ----

const (
	evLeftDown, evLeftUp, evRightDown, evRightUp, evMoved = 1, 2, 3, 4, 5
	evLeftDragged, evRightDragged                         = 6, 7
	evOtherDown, evOtherUp, evOtherDragged                = 25, 26, 27
	fieldClickState                                       = 1
	hidTap                                                = 0
	flagShift, flagCtrl, flagAlt, flagCmd                 = 0x20000, 0x40000, 0x80000, 0x100000
)

func post(ev uintptr) error {
	if ev == 0 {
		return &opError{"failed", "cannot create the input event"}
	}
	cgEventPost(hidTap, ev)
	cfRelease(ev)
	return nil
}

// toPoints converts screen pixels (capture space) to the points CoreGraphics expects.
func (b *macBackend) toPoints(x, y int) cgPoint {
	ms, _, i := b.screens()
	s := ms[i]
	return cgPoint{X: s.bounds.X + float64(x)*s.bounds.W/float64(max(s.pw, 1)),
		Y: s.bounds.Y + float64(y)*s.bounds.H/float64(max(s.ph, 1))}
}

func (b *macBackend) Move(x, y int) error {
	p := b.toPoints(x, y)
	b.mu.Lock()
	defer b.mu.Unlock()
	b.pos = p
	typ, btn := uint32(evMoved), uint32(0)
	switch b.pressed {
	case "left":
		typ = evLeftDragged
	case "right":
		typ, btn = evRightDragged, 1
	case "middle":
		typ, btn = evOtherDragged, 2
	}
	return post(cgEventCreateMouseEvent(0, typ, p, btn))
}

func (b *macBackend) Button(button string, down bool, clicks int) error {
	var typ, btn uint32
	switch button {
	case "left":
		typ = map[bool]uint32{true: evLeftDown, false: evLeftUp}[down]
	case "right":
		typ, btn = map[bool]uint32{true: evRightDown, false: evRightUp}[down], 1
	case "middle":
		typ, btn = map[bool]uint32{true: evOtherDown, false: evOtherUp}[down], 2
	default:
		return badRequest("unknown button %q", button)
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	if down {
		b.pressed = button
	} else {
		b.pressed = ""
	}
	ev := cgEventCreateMouseEvent(0, typ, b.pos, btn)
	if ev != 0 {
		cgEventSetIntegerValueField(ev, fieldClickState, int64(max(clicks, 1)))
		if b.mods != 0 {
			cgEventSetFlags(ev, b.mods)
		}
	}
	return post(ev)
}

func (b *macBackend) Scroll(dx, dy int) error {
	// line units; wheel1 > 0 = up, wheel2 > 0 = left; 3 lines per notch like a PC wheel
	return post(cgEventCreateScrollWheelEvent(0, 1, 2, int32(-dy*3), int32(-dx*3), 0))
}

// ANSI virtual key codes of the keys that are not characters (positions do not depend on the layout).
var macNamed = map[string]uint16{
	"enter": 36, "tab": 48, "space": 49, "backspace": 51, "esc": 53, "cmd": 55, "shift": 56, "capslock": 57,
	"alt": 58, "ctrl": 59, "delete": 117, "insert": 114, "home": 115, "end": 119, "pageup": 116,
	"pagedown": 121, "left": 123, "right": 124, "down": 125, "up": 126, "menu": 110, "printscreen": 105,
}

var macF = []uint16{122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111, 105, 107, 113, 106, 64, 79, 80, 90}

// US layout positions, used when the current layout cannot be read.
var macANSI = map[rune]uint16{
	'a': 0, 's': 1, 'd': 2, 'f': 3, 'h': 4, 'g': 5, 'z': 6, 'x': 7, 'c': 8, 'v': 9, 'b': 11, 'q': 12, 'w': 13,
	'e': 14, 'r': 15, 'y': 16, 't': 17, '1': 18, '2': 19, '3': 20, '4': 21, '6': 22, '5': 23, '=': 24, '9': 25,
	'7': 26, '-': 27, '8': 28, '0': 29, ']': 30, 'o': 31, 'u': 32, '[': 33, 'i': 34, 'p': 35, 'l': 37, 'j': 38,
	'\'': 39, 'k': 40, ';': 41, '\\': 42, ',': 43, '/': 44, 'n': 45, 'm': 46, '.': 47, '`': 50,
}

var macFlags = map[string]uint64{"shift": flagShift, "ctrl": flagCtrl, "alt": flagAlt, "cmd": flagCmd}

type macKey struct {
	code  uint16
	shift bool
}

// layoutKeys maps the characters of the current keyboard layout to key codes (UCKeyTranslate, main thread),
// so "cmd+a" presses the key that types "a" on this keyboard (AZERTY, QWERTZ...), not the US position.
func layoutKeys() map[rune]macKey {
	m := map[rune]macKey{}
	if tisCopyCurrentKeyboardLayout == nil || tisGetInputSourceProperty == nil || ucKeyTranslate == nil ||
		lmGetKbdType == nil || tisUnicodeLayoutKey == 0 {
		return m
	}
	runOnMain(func() {
		var data uintptr
		for _, get := range []func() uintptr{tisCopyCurrentKeyboardLayout, tisCopyCurrentASCIILayout} {
			if get == nil {
				continue
			}
			src := get()
			if src == 0 {
				continue
			}
			if d := tisGetInputSourceProperty(src, tisUnicodeLayoutKey); d != 0 {
				data = cfDataGetBytePtr(d)
			}
			defer cfRelease(src)
			if data != 0 {
				break
			}
		}
		if data == 0 {
			return
		}
		kbd := uint32(lmGetKbdType())
		for _, shift := range []bool{false, true} {
			mods := uint32(0)
			if shift {
				mods = 2 // (shiftKey >> 8) & 0xff
			}
			for code := uint16(0); code < 128; code++ {
				var dead uint32
				var n uintptr
				var buf [4]uint16
				// kUCKeyActionDisplay = 3, kUCKeyTranslateNoDeadKeysMask = 1
				if ucKeyTranslate(data, code, 3, mods, kbd, 1, &dead, 4, &n, &buf[0]) != 0 || n != 1 {
					continue
				}
				r := rune(buf[0])
				if r < 0x20 || r == 0x7f {
					continue
				}
				if _, seen := m[r]; !seen {
					m[r] = macKey{code, shift}
				}
			}
		}
	})
	return m
}

func (b *macBackend) keyEvent(code uint16, down bool, flags uint64) error {
	ev := cgEventCreateKeyboardEvent(0, code, down)
	if ev != 0 {
		cgEventSetFlags(ev, flags)
	}
	return post(ev)
}

// unicodeEvent types s (at most 20 UTF-16 units) as one key down / up pair carrying the text.
func unicodeEvent(u []uint16, flags uint64) error {
	for _, down := range []bool{true, false} {
		ev := cgEventCreateKeyboardEvent(0, 0, down)
		if ev == 0 {
			return &opError{"failed", "cannot create the input event"}
		}
		cgEventKeyboardSetUnicodeStr(ev, uintptr(len(u)), &u[0])
		cgEventSetFlags(ev, flags)
		if err := post(ev); err != nil {
			return err
		}
	}
	return nil
}

func (b *macBackend) Key(name string, down bool) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	if f, ok := macFlags[name]; ok {
		if down {
			b.mods |= f
		} else {
			b.mods &^= f
		}
		return b.keyEvent(macNamed[name], down, b.mods)
	}
	if code, ok := macNamed[name]; ok {
		return b.keyEvent(code, down, b.mods)
	}
	if n := functionKey(name); n > 0 {
		if n > len(macF) {
			return badRequest("no key %s on a Mac", name)
		}
		return b.keyEvent(macF[n-1], down, b.mods)
	}
	r := []rune(name)
	if len(r) != 1 {
		return badRequest("unknown key %q", name)
	}
	if k, ok := layoutKeys()[r[0]]; ok {
		flags := b.mods
		if k.shift {
			flags |= flagShift
		}
		return b.keyEvent(k.code, down, flags)
	}
	if code, ok := macANSI[r[0]]; ok && tisUnicodeLayoutKey == 0 {
		return b.keyEvent(code, down, b.mods)
	}
	if !down {
		return nil
	}
	return unicodeEvent(utf16.Encode(r), b.mods) // not on this keyboard: typed as text
}

func (b *macBackend) Text(s string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	var chunk []uint16
	flush := func() error {
		for len(chunk) > 0 {
			n := min(len(chunk), 20)
			if n < len(chunk) && utf16.IsSurrogate(rune(chunk[n-1])) {
				n-- // never split a surrogate pair
			}
			if err := unicodeEvent(chunk[:n], 0); err != nil {
				return err
			}
			chunk = chunk[n:]
			time.Sleep(5 * time.Millisecond)
		}
		return nil
	}
	for _, r := range s {
		var code uint16
		switch r {
		case '\r':
			continue
		case '\n':
			code = 36
		case '\t':
			code = 48
		default:
			chunk = append(chunk, utf16.Encode([]rune{r})...)
			continue
		}
		if err := flush(); err != nil {
			return err
		}
		if err := b.keyEvent(code, true, 0); err != nil {
			return err
		}
		if err := b.keyEvent(code, false, 0); err != nil {
			return err
		}
	}
	return flush()
}

// ---- apps: the .app bundles of the Applications folders, opened with `open -a` ----

func (b *macBackend) Apps() ([]app, error) {
	dirs := []string{"/Applications", "/Applications/Utilities", "/System/Applications", "/System/Applications/Utilities"}
	if h, err := os.UserHomeDir(); err == nil {
		dirs = append(dirs, filepath.Join(h, "Applications"))
	}
	var l []app
	seen := map[string]bool{}
	add := func(p string) {
		id := strings.TrimSuffix(filepath.Base(p), ".app")
		if !seen[strings.ToLower(id)] {
			seen[strings.ToLower(id)] = true
			l = append(l, app{ID: id, Name: id, target: p})
		}
	}
	for _, d := range dirs {
		ents, _ := os.ReadDir(d)
		for _, e := range ents {
			p := filepath.Join(d, e.Name())
			if strings.HasSuffix(e.Name(), ".app") {
				add(p)
			} else if e.IsDir() && !strings.HasPrefix(e.Name(), ".") && e.Name() != "Utilities" {
				sub, _ := os.ReadDir(p) // one level of folders ("Microsoft Office/...")
				for _, s := range sub {
					if strings.HasSuffix(s.Name(), ".app") {
						add(filepath.Join(p, s.Name()))
					}
				}
			}
		}
	}
	return sortApps(l), nil
}

func (b *macBackend) Launch(a app) error {
	if !strings.HasSuffix(a.target, ".app") {
		return errors.New("not an app bundle")
	}
	if out, err := exec.Command("/usr/bin/open", "-a", a.target).CombinedOutput(); err != nil {
		return &opError{"failed", "cannot open " + a.Name + ": " + strings.TrimSpace(string(out))}
	}
	return nil
}

// secureInput tells whether macOS secure keyboard entry is on (a password field has the focus): the live log
// then hides what Claude types.
func secureInput() bool {
	if loadCG() != nil || isSecureEventInputEnabled == nil {
		return false
	}
	return isSecureEventInputEnabled() != 0
}
