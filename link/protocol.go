package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"image"
	"image/jpeg"
	"math"
	"strings"
	"time"
	"unicode/utf8"

	"golang.org/x/image/draw"
)

// request is any server -> app frame (PROTOCOL.md). Unused fields stay zero.
type request struct {
	T  string          `json:"t"`
	ID json.RawMessage `json:"id,omitempty"`

	// access: accepted in Harness Maxxing, and what Claude may do
	OK   *bool  `json:"ok"`
	Mode string `json:"mode"`
	// display: the screen to use (index in hello.screens); watch: someone watches the live view
	I  *int `json:"i"`
	On bool `json:"on"`
	// shot: a picture of the live view (not one of Claude's), not shown in the live log
	Live bool `json:"live"`

	// shot
	MaxW    int       `json:"max_w"`
	Quality int       `json:"quality"`
	Crop    *cropRect `json:"crop"` // zoom: part of the screen, in the capture space sw x sh

	// input
	A      string   `json:"a"`
	X      *float64 `json:"x"`
	Y      *float64 `json:"y"`
	X2     *float64 `json:"x2"`
	Y2     *float64 `json:"y2"`
	SW     float64  `json:"sw"`
	SH     float64  `json:"sh"`
	Button string   `json:"button"`
	Double bool     `json:"double"`
	DX     float64  `json:"dx"`
	DY     float64  `json:"dy"`
	Text   string   `json:"text"`
	Keys   string   `json:"keys"`
	MS     int      `json:"ms"`

	// open
	App string `json:"app"`

	// state
	Busy *bool  `json:"busy"`
	By   string `json:"by"`
}

type cropRect struct{ X, Y, W, H float64 }

// opError is answered as {"t":"err","id","code","message"}.
type opError struct{ Code, Message string }

func (e *opError) Error() string { return e.Code + ": " + e.Message }

func badRequest(f string, a ...any) error { return &opError{"bad_request", fmt.Sprintf(f, a...)} }

func errReply(id json.RawMessage, err error) map[string]any {
	var oe *opError
	if !errors.As(err, &oe) {
		oe = &opError{"failed", err.Error()}
	}
	return map[string]any{"t": "err", "id": id, "code": oe.Code, "message": oe.Message}
}

const (
	maxText      = 20000 // bytes of text per "type"
	maxCombos    = 32    // key combos per "key"
	longPressMS  = 600
	defaultDrag  = 300
	maxGestureMS = 10000
	maxScroll    = 100 // wheel notches per request
)

// serve answers one request (run by the worker, one at a time).
func (a *agent) serve(r request) map[string]any {
	done := func(kv ...any) map[string]any {
		m := map[string]any{"t": "ok", "id": r.ID}
		for i := 0; i+1 < len(kv); i += 2 {
			m[kv[i].(string)] = kv[i+1]
		}
		return m
	}
	d := ""
	if !r.Live {
		d = describe(r)
	}
	if d != "" && r.T == "input" && r.A == "type" && secureInput() {
		d = fmt.Sprintf("Type %d characters in a password field (hidden)", utf8.RuneCountInString(r.Text))
	}
	ok := func(kv ...any) map[string]any {
		if d != "" {
			a.say(lAction, d)
		}
		return done(kv...)
	}
	var err error
	switch r.T {
	case "shot":
		var s *shotResult
		if s, err = doShot(a.be, r.MaxW, r.Quality, r.Crop, r.SW, r.SH); err == nil {
			return ok("jpeg", base64.StdEncoding.EncodeToString(s.JPEG), "w", s.W, "h", s.H,
				"sw_screen", s.SW, "sh_screen", s.SH)
		}
	case "input":
		if err = doInput(a.be, r); err == nil {
			return ok()
		}
	case "apps":
		var l []app
		if l, err = listApps(a.be); err == nil {
			out := make([]map[string]string, 0, len(l))
			for _, x := range l {
				out = append(out, map[string]string{"id": x.ID, "name": x.Name})
			}
			return ok("apps", out)
		}
	case "open":
		if err = openApp(a.be, r.App); err == nil {
			return ok()
		}
	case "tree", "tap_node", "set_text":
		err = &opError{"unsupported", "the element tree is not available on computers in this version: use screenshots"}
	default:
		err = &opError{"unsupported", "unknown request"}
	}
	if err != nil {
		a.logf("%s %s failed: %v", r.T, r.A, err)
		msg := err.Error()
		var oe *opError
		if errors.As(err, &oe) {
			msg = oe.Message
		}
		if d == "" {
			d = r.T
		}
		a.say(lActionFail, d+": "+shortErr(errors.New(msg)))
	}
	return errReply(r.ID, err)
}

// ---- shot ----

type shotResult struct {
	JPEG         []byte
	W, H, SW, SH int
}

func doShot(be backend, maxW, quality int, crop *cropRect, sw, sh float64) (*shotResult, error) {
	if err := need(be, capScreen); err != nil {
		return nil, err
	}
	img, err := be.Capture()
	if err != nil {
		return nil, err
	}
	b := img.Bounds()
	var src image.Image = img
	if crop != nil {
		r, err := cropToScreen(*crop, sw, sh, b)
		if err != nil {
			return nil, err
		}
		si, ok := img.(interface {
			SubImage(image.Rectangle) image.Image
		})
		if !ok {
			return nil, &opError{"failed", "cannot crop this capture"}
		}
		src = si.SubImage(r)
	}
	out := downscale(src, maxW)
	if quality <= 0 {
		quality = 70
	}
	quality = min(max(quality, 20), 95)
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, out, &jpeg.Options{Quality: quality}); err != nil {
		return nil, err
	}
	ob := out.Bounds()
	return &shotResult{JPEG: buf.Bytes(), W: ob.Dx(), H: ob.Dy(), SW: b.Dx(), SH: b.Dy()}, nil
}

// cropToScreen converts a crop given in a capture of size sw x sh to a rectangle of the full-size capture b.
func cropToScreen(c cropRect, sw, sh float64, b image.Rectangle) (image.Rectangle, error) {
	for _, v := range []float64{c.X, c.Y, c.W, c.H} {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return image.Rectangle{}, badRequest("bad crop")
		}
	}
	if c.W <= 0 || c.H <= 0 {
		return image.Rectangle{}, badRequest("crop w and h must be positive")
	}
	fx, fy := 1.0, 1.0
	if sw > 0 {
		fx = float64(b.Dx()) / sw
	}
	if sh > 0 {
		fy = float64(b.Dy()) / sh
	}
	r := image.Rect(int(math.Floor(c.X*fx)), int(math.Floor(c.Y*fy)),
		int(math.Ceil((c.X+c.W)*fx)), int(math.Ceil((c.Y+c.H)*fy))).Add(b.Min).Intersect(b)
	if r.Dx() < 1 || r.Dy() < 1 {
		return image.Rectangle{}, badRequest("crop is outside the screen")
	}
	return r, nil
}

// downscale returns img reduced to maxW pixels wide (aspect kept); never enlarges. maxW <= 0 = full size.
func downscale(img image.Image, maxW int) image.Image {
	b := img.Bounds()
	w, h := b.Dx(), b.Dy()
	if maxW <= 0 || maxW >= w || w == 0 {
		return img
	}
	maxW = max(maxW, 16)
	nh := max(int(math.Round(float64(h)*float64(maxW)/float64(w))), 1)
	dst := image.NewRGBA(image.Rect(0, 0, maxW, nh))
	draw.BiLinear.Scale(dst, dst.Bounds(), img, b, draw.Src, nil)
	return dst
}

// ---- input ----

// toScreen converts a coordinate given in a capture of size capSize to the real screen (size real),
// clamped to the screen. capSize <= 0 means the coordinate is already in screen pixels.
func toScreen(v, capSize float64, real int) int {
	if capSize > 0 {
		v = v * float64(real) / capSize
	}
	p := int(math.Round(v))
	return min(max(p, 0), max(real-1, 0))
}

func need(be backend, c string) error {
	inf := be.Info()
	if inf.has(c) {
		return nil
	}
	code, msg := inf.Code, inf.Note
	if code == "" {
		code = "unsupported"
	}
	if msg == "" {
		msg = c + " is not available on this computer"
	}
	return &opError{code, msg}
}

func doInput(be backend, r request) error {
	if err := need(be, capInput); err != nil {
		return err
	}
	scr := be.Info().Screen
	if scr == nil {
		return &opError{"unsupported", "no screen"}
	}
	point := func(x, y *float64) (int, int, error) {
		if x == nil || y == nil {
			return 0, 0, badRequest("x and y are required")
		}
		if math.IsNaN(*x) || math.IsNaN(*y) || math.IsInf(*x, 0) || math.IsInf(*y, 0) {
			return 0, 0, badRequest("bad coordinates")
		}
		return toScreen(*x, r.SW, scr.W), toScreen(*y, r.SH, scr.H), nil
	}
	button := r.Button
	switch button {
	case "":
		button = "left"
	case "left", "right", "middle":
	default:
		return badRequest("unknown button %q", button)
	}
	pause := func(ms int) { time.Sleep(time.Duration(ms) * time.Millisecond) }

	switch r.A {
	case "click":
		x, y, err := point(r.X, r.Y)
		if err != nil {
			return err
		}
		if err := be.Move(x, y); err != nil {
			return err
		}
		pause(20)
		n := 1
		if r.Double {
			n = 2
		}
		for i := 1; i <= n; i++ {
			if err := be.Button(button, true, i); err != nil {
				return err
			}
			pause(30)
			if err := be.Button(button, false, i); err != nil {
				return err
			}
			if i < n {
				pause(60)
			}
		}
	case "long_press":
		x, y, err := point(r.X, r.Y)
		if err != nil {
			return err
		}
		ms := r.MS
		if ms <= 0 {
			ms = longPressMS
		}
		if err := be.Move(x, y); err != nil {
			return err
		}
		pause(20)
		if err := be.Button(button, true, 1); err != nil {
			return err
		}
		pause(min(ms, maxGestureMS))
		return be.Button(button, false, 1)
	case "move":
		x, y, err := point(r.X, r.Y)
		if err != nil {
			return err
		}
		return be.Move(x, y)
	case "drag":
		x1, y1, err := point(r.X, r.Y)
		if err != nil {
			return err
		}
		x2, y2, err := point(r.X2, r.Y2)
		if err != nil {
			return err
		}
		ms := r.MS
		if ms <= 0 {
			ms = defaultDrag
		}
		ms = min(max(ms, 50), maxGestureMS)
		if err := be.Move(x1, y1); err != nil {
			return err
		}
		pause(30)
		if err := be.Button(button, true, 1); err != nil {
			return err
		}
		pause(50)
		var moveErr error
		for _, p := range dragPath(x1, y1, x2, y2, ms) {
			if moveErr = be.Move(p[0], p[1]); moveErr != nil {
				break
			}
			pause(16)
		}
		pause(50)
		if err := be.Button(button, false, 1); err != nil {
			return err
		}
		return moveErr
	case "scroll":
		if r.X != nil || r.Y != nil {
			x, y, err := point(r.X, r.Y)
			if err != nil {
				return err
			}
			if err := be.Move(x, y); err != nil {
				return err
			}
			pause(20)
		}
		dx, dy := notches(r.DX), notches(r.DY)
		if dx == 0 && dy == 0 {
			return badRequest("dx or dy is required")
		}
		return be.Scroll(dx, dy)
	case "type":
		if r.Text == "" {
			return badRequest("text is required")
		}
		if len(r.Text) > maxText || !utf8.ValidString(r.Text) {
			return badRequest("text too long or not UTF-8")
		}
		return be.Text(r.Text)
	case "key":
		seq, err := parseKeys(r.Keys)
		if err != nil {
			return err
		}
		for i, combo := range seq {
			if i > 0 {
				pause(40)
			}
			if err := pressCombo(be, combo); err != nil {
				return err
			}
		}
	default:
		return badRequest("unknown action %q", r.A)
	}
	return nil
}

// dragPath returns the intermediate pointer positions of a drag lasting about ms (one every 16 ms), ending at x2, y2.
func dragPath(x1, y1, x2, y2, ms int) [][2]int {
	steps := max(ms/16, 2)
	out := make([][2]int, 0, steps)
	for i := 1; i <= steps; i++ {
		f := float64(i) / float64(steps)
		out = append(out, [2]int{
			int(math.Round(float64(x1) + f*float64(x2-x1))),
			int(math.Round(float64(y1) + f*float64(y2-y1))),
		})
	}
	return out
}

// notches rounds a scroll amount to whole wheel steps (a non-zero amount is at least one step).
func notches(v float64) int {
	if math.IsNaN(v) || v == 0 {
		return 0
	}
	n := int(math.Round(v))
	if n == 0 {
		n = int(math.Copysign(1, v))
	}
	return min(max(n, -maxScroll), maxScroll)
}

// pressCombo presses the modifiers, then the key, then releases everything in reverse order.
func pressCombo(be backend, combo []string) error {
	var held []string
	defer func() {
		for i := len(held) - 1; i >= 0; i-- {
			_ = be.Key(held[i], false)
			time.Sleep(5 * time.Millisecond)
		}
	}()
	for _, k := range combo {
		if err := be.Key(k, true); err != nil {
			return err
		}
		held = append(held, k)
		time.Sleep(10 * time.Millisecond)
	}
	return nil
}

// ---- apps ----

type app struct {
	ID, Name string
	target   string // what the backend launches (desktop file, .lnk, .app path)
}

const maxApps = 1000

func listApps(be backend) ([]app, error) {
	if err := need(be, capApps); err != nil {
		return nil, err
	}
	l, err := be.Apps()
	if len(l) > maxApps {
		l = l[:maxApps]
	}
	return l, err
}

// openApp starts one of the listed apps, found by id (or by name, ignoring case). Nothing else can be started.
func openApp(be backend, want string) error {
	want = strings.TrimSpace(want)
	if want == "" {
		return badRequest("app is required")
	}
	l, err := listApps(be)
	if err != nil {
		return err
	}
	for _, x := range l {
		if x.ID == want {
			return be.Launch(x)
		}
	}
	for _, x := range l {
		if strings.EqualFold(x.Name, want) || strings.EqualFold(x.ID, want) {
			return be.Launch(x)
		}
	}
	return &opError{"not_found", "no app " + want + " on this computer (see apps)"}
}
