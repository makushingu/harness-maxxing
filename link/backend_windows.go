//go:build windows

package main

import (
	"image"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"unicode/utf16"
	"unsafe"

	"golang.org/x/sys/windows"
)

// Windows: GDI capture of the primary monitor (BitBlt + GetDIBits) and SendInput, through lazy DLLs (no cgo).
// The process is per-monitor DPI aware, so sizes and coordinates are physical pixels.

var (
	user32 = windows.NewLazySystemDLL("user32.dll")
	gdi32  = windows.NewLazySystemDLL("gdi32.dll")
	shcore = windows.NewLazySystemDLL("shcore.dll")

	pSetProcessDpiAwarenessContext = user32.NewProc("SetProcessDpiAwarenessContext")
	pSetProcessDPIAware            = user32.NewProc("SetProcessDPIAware")
	pSetProcessDpiAwareness        = shcore.NewProc("SetProcessDpiAwareness")
	pGetDpiForSystem               = user32.NewProc("GetDpiForSystem")
	pGetSystemMetrics              = user32.NewProc("GetSystemMetrics")
	pGetDC                         = user32.NewProc("GetDC")
	pReleaseDC                     = user32.NewProc("ReleaseDC")
	pSendInput                     = user32.NewProc("SendInput")
	pVkKeyScanW                    = user32.NewProc("VkKeyScanW")
	pMapVirtualKeyW                = user32.NewProc("MapVirtualKeyW")
	pCreateCompatibleDC            = gdi32.NewProc("CreateCompatibleDC")
	pCreateCompatibleBitmap        = gdi32.NewProc("CreateCompatibleBitmap")
	pSelectObject                  = gdi32.NewProc("SelectObject")
	pBitBlt                        = gdi32.NewProc("BitBlt")
	pGetDIBits                     = gdi32.NewProc("GetDIBits")
	pDeleteObject                  = gdi32.NewProc("DeleteObject")
	pDeleteDC                      = gdi32.NewProc("DeleteDC")
)

var dpiOnce sync.Once

// setDPIAware makes the process per-monitor DPI aware (v2, else v1, else system aware).
func setDPIAware() {
	dpiOnce.Do(func() {
		if pSetProcessDpiAwarenessContext.Find() == nil {
			const perMonitorV2 = ^uintptr(3) // DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = (HANDLE)-4
			if r, _, _ := pSetProcessDpiAwarenessContext.Call(perMonitorV2); r != 0 {
				return
			}
		}
		if pSetProcessDpiAwareness.Find() == nil {
			if r, _, _ := pSetProcessDpiAwareness.Call(2); r == 0 { // PROCESS_PER_MONITOR_DPI_AWARE, S_OK
				return
			}
		}
		if pSetProcessDPIAware.Find() == nil {
			pSetProcessDPIAware.Call()
		}
	})
}

type winBackend struct {
	logf func(string, ...any)
	mu   sync.Mutex
}

func newBackend(dir string, logf func(string, ...any)) backend {
	setDPIAware()
	return &winBackend{logf: logf}
}

func (b *winBackend) Close() {}

func screenSize() (int, int) {
	w, _, _ := pGetSystemMetrics.Call(0) // SM_CXSCREEN: primary monitor
	h, _, _ := pGetSystemMetrics.Call(1) // SM_CYSCREEN
	return int(int32(w)), int(int32(h))
}

func (b *winBackend) Info() backendInfo {
	inf := backendInfo{Apps: true}
	w, h := screenSize()
	if w <= 0 || h <= 0 {
		inf.Note, inf.Code = "No screen found (is a user signed in?).", "no_display"
		return inf
	}
	scale := 1.0
	if pGetDpiForSystem.Find() == nil {
		if d, _, _ := pGetDpiForSystem.Call(); d > 0 {
			scale = float64(d) / 96
		}
	}
	inf.Screen = &screenInfo{W: w, H: h, Scale: scale}
	inf.Input = true
	return inf
}

type bitmapInfoHeader struct {
	Size          uint32
	Width, Height int32
	Planes        uint16
	BitCount      uint16
	Compression   uint32
	SizeImage     uint32
	XPelsPerMeter int32
	YPelsPerMeter int32
	ClrUsed       uint32
	ClrImportant  uint32
}

type bitmapInfo struct {
	Header bitmapInfoHeader
	Colors [4]uint32
}

func (b *winBackend) Capture() (image.Image, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	w, h := screenSize()
	if w <= 0 || h <= 0 {
		return nil, &opError{"no_display", "no screen"}
	}
	src, _, _ := pGetDC.Call(0)
	if src == 0 {
		return nil, &opError{"failed", "GetDC failed"}
	}
	defer pReleaseDC.Call(0, src)
	mem, _, _ := pCreateCompatibleDC.Call(src)
	if mem == 0 {
		return nil, &opError{"failed", "CreateCompatibleDC failed"}
	}
	defer pDeleteDC.Call(mem)
	bmp, _, _ := pCreateCompatibleBitmap.Call(src, uintptr(w), uintptr(h))
	if bmp == 0 {
		return nil, &opError{"failed", "CreateCompatibleBitmap failed"}
	}
	defer pDeleteObject.Call(bmp)
	old, _, _ := pSelectObject.Call(mem, bmp)
	const srcCopy, captureBlt = 0x00CC0020, 0x40000000
	ok, _, _ := pBitBlt.Call(mem, 0, 0, uintptr(w), uintptr(h), src, 0, 0, srcCopy|captureBlt)
	pSelectObject.Call(mem, old) // GetDIBits wants the bitmap out of any DC
	if ok == 0 {
		return nil, &opError{"protected", "the screen cannot be captured now (locked or secure desktop?)"}
	}
	bi := bitmapInfo{Header: bitmapInfoHeader{Width: int32(w), Height: -int32(h), Planes: 1, BitCount: 32}}
	bi.Header.Size = uint32(unsafe.Sizeof(bi.Header))
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	n, _, _ := pGetDIBits.Call(mem, bmp, 0, uintptr(h), uintptr(unsafe.Pointer(&img.Pix[0])), uintptr(unsafe.Pointer(&bi)), 0)
	if int(n) != h {
		return nil, &opError{"failed", "GetDIBits failed"}
	}
	p := img.Pix
	for i := 0; i+3 < len(p); i += 4 { // BGRA -> RGBA, opaque
		p[i], p[i+2], p[i+3] = p[i+2], p[i], 0xff
	}
	return img, nil
}

// ---- SendInput ----

const (
	inputMouse    = 0
	inputKeyboard = 1

	mouseMove       = 0x0001
	mouseLeftDown   = 0x0002
	mouseLeftUp     = 0x0004
	mouseRightDown  = 0x0008
	mouseRightUp    = 0x0010
	mouseMiddleDown = 0x0020
	mouseMiddleUp   = 0x0040
	mouseWheel      = 0x0800
	mouseHWheel     = 0x1000
	mouseAbsolute   = 0x8000

	keyExtended = 0x0001
	keyUp       = 0x0002
	keyUnicode  = 0x0004
)

// mouseInput / keybdInput are the MOUSEINPUT / KEYBDINPUT members of INPUT (64-bit layout: INPUT = 40 bytes).
type mouseInput struct {
	DX, DY    int32
	MouseData uint32
	Flags     uint32
	Time      uint32
	Extra     uintptr
}

type keybdInput struct {
	VK, Scan uint16
	Flags    uint32
	Time     uint32
	Extra    uintptr
	_        [8]byte // pad to the size of the union (MOUSEINPUT)
}

type winInput struct {
	Type uint32
	_    uint32    // the union is 8-byte aligned on 64-bit
	Data [4]uint64 // MOUSEINPUT | KEYBDINPUT
}

func mouseIn(m mouseInput) winInput {
	in := winInput{Type: inputMouse}
	*(*mouseInput)(unsafe.Pointer(&in.Data)) = m
	return in
}

func keyIn(k keybdInput) winInput {
	in := winInput{Type: inputKeyboard}
	*(*keybdInput)(unsafe.Pointer(&in.Data)) = k
	return in
}

func sendInputs(l []winInput) error {
	for len(l) > 0 {
		n := min(len(l), 64)
		r, _, err := pSendInput.Call(uintptr(n), uintptr(unsafe.Pointer(&l[0])), unsafe.Sizeof(l[0]))
		if int(r) != n {
			return &opError{"blocked", "input was blocked by Windows (locked screen, or a window running as administrator): " + err.Error()}
		}
		l = l[n:]
	}
	return nil
}

func (b *winBackend) Move(x, y int) error {
	w, h := screenSize()
	if w <= 1 || h <= 1 {
		return &opError{"no_display", "no screen"}
	}
	nx := int32((int64(x)*65535 + int64(w-1)/2) / int64(w-1))
	ny := int32((int64(y)*65535 + int64(h-1)/2) / int64(h-1))
	return sendInputs([]winInput{mouseIn(mouseInput{DX: nx, DY: ny, Flags: mouseMove | mouseAbsolute})})
}

func (b *winBackend) Button(button string, down bool, _ int) error {
	var f uint32
	switch button {
	case "left":
		f = map[bool]uint32{true: mouseLeftDown, false: mouseLeftUp}[down]
	case "right":
		f = map[bool]uint32{true: mouseRightDown, false: mouseRightUp}[down]
	case "middle":
		f = map[bool]uint32{true: mouseMiddleDown, false: mouseMiddleUp}[down]
	default:
		return badRequest("unknown button %q", button)
	}
	return sendInputs([]winInput{mouseIn(mouseInput{Flags: f})})
}

func (b *winBackend) Scroll(dx, dy int) error {
	var l []winInput
	if dy != 0 { // positive wheel data = away from the user = up
		l = append(l, mouseIn(mouseInput{Flags: mouseWheel, MouseData: uint32(int32(-dy * 120))}))
	}
	if dx != 0 {
		l = append(l, mouseIn(mouseInput{Flags: mouseHWheel, MouseData: uint32(int32(dx * 120))}))
	}
	return sendInputs(l)
}

var winVK = map[string]uint16{
	"ctrl": 0xA2, "shift": 0xA0, "alt": 0xA4, "cmd": 0x5B,
	"enter": 0x0D, "tab": 0x09, "esc": 0x1B, "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
	"home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
	"left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
	"space": 0x20, "capslock": 0x14, "printscreen": 0x2C, "menu": 0x5D,
}

var winExtended = map[uint16]bool{0x2E: true, 0x2D: true, 0x24: true, 0x23: true, 0x21: true, 0x22: true,
	0x25: true, 0x26: true, 0x27: true, 0x28: true, 0x2C: true, 0x5B: true, 0x5D: true}

func vkFor(name string) (uint16, bool) {
	if vk, ok := winVK[name]; ok {
		return vk, true
	}
	if n := functionKey(name); n > 0 {
		return uint16(0x70 + n - 1), true
	}
	r := []rune(name)
	if len(r) != 1 {
		return 0, false
	}
	c := r[0]
	switch {
	case c >= 'a' && c <= 'z':
		return uint16(c - 'a' + 'A'), true
	case c >= '0' && c <= '9':
		return uint16(c), true
	case c < 0x10000:
		v, _, _ := pVkKeyScanW.Call(uintptr(c))
		if int16(v) != -1 {
			return uint16(v) & 0xff, true
		}
	}
	return 0, false
}

func vkInput(vk uint16, down bool) winInput {
	f := uint32(0)
	if !down {
		f |= keyUp
	}
	if winExtended[vk] {
		f |= keyExtended
	}
	scan, _, _ := pMapVirtualKeyW.Call(uintptr(vk), 0) // MAPVK_VK_TO_VSC
	return keyIn(keybdInput{VK: vk, Scan: uint16(scan), Flags: f})
}

func (b *winBackend) Key(name string, down bool) error {
	if vk, ok := vkFor(name); ok {
		return sendInputs([]winInput{vkInput(vk, down)})
	}
	// a character missing from the keyboard layout: typed as Unicode (no combo possible)
	r := []rune(name)
	if len(r) != 1 {
		return badRequest("unknown key %q", name)
	}
	var l []winInput
	for _, u := range utf16.Encode(r) {
		f := uint32(keyUnicode)
		if !down {
			f |= keyUp
		}
		l = append(l, keyIn(keybdInput{Scan: u, Flags: f}))
	}
	return sendInputs(l)
}

func (b *winBackend) Text(s string) error {
	var l []winInput
	for _, r := range s {
		switch r {
		case '\r':
			continue
		case '\n':
			l = append(l, vkInput(0x0D, true), vkInput(0x0D, false))
			continue
		case '\t':
			l = append(l, vkInput(0x09, true), vkInput(0x09, false))
			continue
		}
		for _, u := range utf16.Encode([]rune{r}) {
			l = append(l, keyIn(keybdInput{Scan: u, Flags: keyUnicode}), keyIn(keybdInput{Scan: u, Flags: keyUnicode | keyUp}))
		}
	}
	return sendInputs(l)
}

// ---- apps: Start Menu shortcuts + a few built-in tools ----

func startMenuDirs() []string {
	var l []string
	for _, env := range []string{"APPDATA", "ProgramData"} {
		if base := os.Getenv(env); base != "" {
			l = append(l, filepath.Join(base, "Microsoft", "Windows", "Start Menu", "Programs"))
		}
	}
	return l
}

func (b *winBackend) Apps() ([]app, error) {
	var l []app
	seen := map[string]bool{}
	for _, d := range startMenuDirs() {
		_ = filepath.WalkDir(d, func(p string, de os.DirEntry, err error) error {
			if err != nil || de.IsDir() || !strings.EqualFold(filepath.Ext(p), ".lnk") {
				return nil
			}
			name := strings.TrimSuffix(de.Name(), filepath.Ext(de.Name()))
			if strings.Contains(strings.ToLower(name), "uninstall") {
				return nil
			}
			rel, _ := filepath.Rel(d, p)
			id := filepath.ToSlash(strings.TrimSuffix(rel, filepath.Ext(rel)))
			if !seen[strings.ToLower(id)] {
				seen[strings.ToLower(id)] = true
				l = append(l, app{ID: id, Name: name, target: p})
			}
			return nil
		})
	}
	sys := os.Getenv("SystemRoot")
	if sys == "" {
		sys = `C:\Windows`
	}
	for _, x := range []struct{ id, name, exe string }{
		{"notepad", "Notepad", `System32\notepad.exe`}, {"calc", "Calculator", `System32\calc.exe`},
		{"mspaint", "Paint", `System32\mspaint.exe`}, {"explorer", "File Explorer", `explorer.exe`},
	} {
		p := filepath.Join(sys, x.exe)
		if _, err := os.Stat(p); err == nil && !seen[x.id] {
			l = append(l, app{ID: x.id, Name: x.name, target: p})
		}
	}
	return sortApps(l), nil
}

func (b *winBackend) Launch(a app) error {
	verb, _ := windows.UTF16PtrFromString("open")
	file, err := windows.UTF16PtrFromString(a.target)
	if err != nil {
		return &opError{"failed", err.Error()}
	}
	const swShowNormal = 1
	if err := windows.ShellExecute(0, verb, file, nil, nil, swShowNormal); err != nil {
		return &opError{"failed", "cannot start " + a.Name + ": " + err.Error()}
	}
	return nil
}

// Compile-time checks of the INPUT layout (40 bytes, union of 32 bytes on 64-bit Windows).
var (
	_ [40 - unsafe.Sizeof(winInput{})]byte
	_ [unsafe.Sizeof(winInput{}) - 40]byte
	_ [unsafe.Sizeof(mouseInput{}) - 32]byte
	_ [unsafe.Sizeof(keybdInput{}) - 32]byte
)
