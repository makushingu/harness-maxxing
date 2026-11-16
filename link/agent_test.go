package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/jpeg"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/coder/websocket"
)

// ---- fake backend: a 1920x1080 screen that records every operation ----

type fakeBackend struct {
	mu     sync.Mutex
	ops    []string
	info   backendInfo
	apps   []app
	opened []string
}

func newFakeBackend() *fakeBackend {
	return &fakeBackend{
		info: backendInfo{Screen: &screenInfo{W: 1920, H: 1080, Scale: 1}, Input: true, Apps: true},
		apps: []app{{ID: "org.example.Editor", Name: "Editor", target: "/x/editor.desktop"}, {ID: "calc", Name: "Calculator"}},
	}
}

func (f *fakeBackend) rec(s string, a ...any) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.ops = append(f.ops, fmt.Sprintf(s, a...))
	return nil
}

func (f *fakeBackend) take() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	o := f.ops
	f.ops = nil
	return o
}

func (f *fakeBackend) Info() backendInfo {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.info
}

func (f *fakeBackend) Capture() (image.Image, error) {
	img := image.NewRGBA(image.Rect(0, 0, 1920, 1080))
	for x := 0; x < 960; x++ {
		for y := 0; y < 1080; y++ {
			img.Set(x, y, color.RGBA{255, 0, 0, 255})
		}
	}
	return img, nil
}
func (f *fakeBackend) Move(x, y int) error { return f.rec("move %d,%d", x, y) }
func (f *fakeBackend) Button(b string, down bool, n int) error {
	return f.rec("%s %v %d", b, map[bool]string{true: "down", false: "up"}[down], n)
}
func (f *fakeBackend) Scroll(dx, dy int) error       { return f.rec("scroll %d,%d", dx, dy) }
func (f *fakeBackend) Key(k string, down bool) error { return f.rec("key %s %v", k, down) }
func (f *fakeBackend) Text(s string) error           { return f.rec("text %q", s) }
func (f *fakeBackend) Apps() ([]app, error)          { return f.apps, nil }
func (f *fakeBackend) Launch(a app) error {
	f.mu.Lock()
	f.opened = append(f.opened, a.ID)
	f.mu.Unlock()
	return nil
}
func (f *fakeBackend) Close() {}

func (f *fakeBackend) SetDisplay(i int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.ops = append(f.ops, fmt.Sprintf("display %d", i))
	f.info.Display = pickDisplay(f.info.Displays, i)
}

// ---- fake server ----

type sconn struct {
	c    *websocket.Conn
	done chan struct{}
}

type fakeServer struct {
	*httptest.Server
	conns    chan *sconn
	revoked  atomic.Bool
	pairBody atomic.Value
}

func newFakeServer(t *testing.T) *fakeServer {
	fs := &fakeServer{conns: make(chan *sconn, 4)}
	mux := http.NewServeMux()
	mux.HandleFunc("POST /api/devices/pair", func(w http.ResponseWriter, r *http.Request) {
		var req map[string]any
		json.NewDecoder(r.Body).Decode(&req)
		fs.pairBody.Store(req)
		if req["code"] != "GOOD" {
			w.WriteHeader(400)
			fmt.Fprint(w, `{"error":"bad_code","message":"unknown code"}`)
			return
		}
		fmt.Fprint(w, `{"device_id":"dev1","token":"tok1"}`)
	})
	mux.HandleFunc("/api/devices/ws", func(w http.ResponseWriter, r *http.Request) {
		if fs.revoked.Load() || r.Header.Get("Authorization") != "Bearer tok1" {
			w.WriteHeader(401)
			return
		}
		c, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		c.SetReadLimit(maxFrame)
		sc := &sconn{c: c, done: make(chan struct{})}
		fs.conns <- sc
		<-sc.done
	})
	fs.Server = httptest.NewServer(mux)
	t.Cleanup(fs.Close)
	return fs
}

func (fs *fakeServer) next(t *testing.T) *sconn {
	t.Helper()
	select {
	case c := <-fs.conns:
		t.Cleanup(func() { c.c.CloseNow(); closeOnce(c.done) })
		return c
	case <-time.After(10 * time.Second):
		t.Fatal("app did not connect")
	}
	return nil
}

func closeOnce(c chan struct{}) {
	select {
	case <-c:
	default:
		close(c)
	}
}

func (c *sconn) send(t *testing.T, v any) {
	t.Helper()
	b, _ := json.Marshal(v)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := c.c.Write(ctx, websocket.MessageText, b); err != nil {
		t.Fatalf("send: %v", err)
	}
}

func (c *sconn) recv(t *testing.T) map[string]any {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	_, b, err := c.c.Read(ctx)
	if err != nil {
		t.Fatalf("recv: %v", err)
	}
	var m map[string]any
	json.Unmarshal(b, &m)
	return m
}

// call sends a request with an id and returns the answer to it.
func (c *sconn) call(t *testing.T, req map[string]any) map[string]any {
	t.Helper()
	id := fmt.Sprintf("r%d", time.Now().UnixNano())
	req["id"] = id
	c.send(t, req)
	m := c.recv(t)
	if m["id"] != id {
		t.Fatalf("reply id %v, want %s (%v)", m["id"], id, m)
	}
	return m
}

func testLog(f string, a ...any) {
	if testing.Verbose() {
		fmt.Fprintf(os.Stderr, "  %s app: "+f+"\n", append([]any{time.Now().Format("05.000")}, a...)...)
	}
}

func startAgent(t *testing.T, dir string, tr *Trailer, be backend) chan int {
	old := backoffBase
	backoffBase = 50 * time.Millisecond
	t.Cleanup(func() { backoffBase = old })
	ctx, cancel := context.WithCancel(context.Background())
	res := make(chan int, 1)
	done := make(chan struct{})
	go func() {
		defer close(done)
		res <- runAgent(ctx, runOpts{dir: dir, trailer: tr, logf: testLog, be: be})
	}()
	t.Cleanup(func() {
		cancel()
		select {
		case <-done:
		case <-time.After(10 * time.Second):
			t.Error("app did not stop")
		}
	})
	return res
}

func TestProtocol(t *testing.T) {
	fs := newFakeServer(t)
	be := newFakeBackend()
	dir := filepath.Join(t.TempDir(), "cfg")
	res := startAgent(t, dir, &Trailer{Server: fs.URL, Code: "GOOD"}, be)

	c := fs.next(t)
	hello := c.recv(t)
	if hello["t"] != "hello" || hello["v"] != version || hello["kind"] != "desktop" ||
		fmt.Sprint(hello["caps"]) != "[screen input apps]" || fmt.Sprint(hello["screen"]) != "map[h:1080 scale:1 w:1920]" {
		t.Fatalf("hello %v", hello)
	}
	if pb := fs.pairBody.Load().(map[string]any); pb["code"] != "GOOD" || fmt.Sprint(pb["caps"]) != "[screen input apps]" || pb["os"] == "" {
		t.Fatalf("pair body %v", pb)
	}
	cfg, err := loadConfig(dir)
	if err != nil || cfg == nil || cfg.Token != "tok1" || cfg.PairedCode != "GOOD" || cfg.DeviceID != "dev1" {
		t.Fatalf("config %+v %v", cfg, err)
	}

	// shot: downscaled to max_w, aspect kept, real size reported
	m := c.call(t, map[string]any{"t": "shot", "max_w": 1280, "quality": 60})
	if m["t"] != "ok" || m["w"] != 1280.0 || m["h"] != 720.0 || m["sw_screen"] != 1920.0 || m["sh_screen"] != 1080.0 {
		t.Fatalf("shot %v", m["t"])
	}
	raw, _ := base64.StdEncoding.DecodeString(m["jpeg"].(string))
	img, err := jpeg.Decode(bytes.NewReader(raw))
	if err != nil || img.Bounds().Dx() != 1280 || img.Bounds().Dy() != 720 {
		t.Fatalf("jpeg %v %v", err, img)
	}
	if r, g, _, _ := img.At(100, 100).RGBA(); r>>8 < 200 || g>>8 > 60 {
		t.Fatalf("left half should be red: %v", img.At(100, 100))
	}

	// zoom: a crop given in capture space, cut from the full-size capture (the red half / the black half)
	m = c.call(t, map[string]any{"t": "shot", "max_w": 1280, "crop": map[string]any{"x": 600, "y": 0, "w": 80, "h": 45}, "sw": 1280, "sh": 720})
	if m["t"] != "ok" || m["w"] != 120.0 || m["h"] != 68.0 || m["sw_screen"] != 1920.0 {
		t.Fatalf("crop %v %v %v %v", m["t"], m["w"], m["h"], m["message"])
	}
	raw, _ = base64.StdEncoding.DecodeString(m["jpeg"].(string))
	img, _ = jpeg.Decode(bytes.NewReader(raw))
	if r, _, _, _ := img.At(5, 30).RGBA(); r>>8 < 200 {
		t.Fatalf("crop left should be red")
	}
	if r, _, _, _ := img.At(115, 30).RGBA(); r>>8 > 60 {
		t.Fatalf("crop right should be black")
	}
	if m := c.call(t, map[string]any{"t": "shot", "crop": map[string]any{"x": 5000, "y": 0, "w": 10, "h": 10}, "sw": 1280, "sh": 720}); m["code"] != "bad_request" {
		t.Fatalf("crop outside %v", m)
	}

	// input, coordinates in capture space (1280x720) scaled to the 1920x1080 screen
	cases := []struct {
		req  map[string]any
		want string
	}{
		{map[string]any{"a": "click", "x": 640, "y": 360, "sw": 1280, "sh": 720}, "move 960,540|left down 1|left up 1"},
		{map[string]any{"a": "click", "x": 10, "y": 10, "sw": 1280, "sh": 720, "button": "right"}, "move 15,15|right down 1|right up 1"},
		{map[string]any{"a": "click", "x": 2000, "y": -5, "sw": 1280, "sh": 720, "double": true},
			"move 1919,0|left down 1|left up 1|left down 2|left up 2"},
		{map[string]any{"a": "move", "x": 100, "y": 200}, "move 100,200"},
		{map[string]any{"a": "scroll", "x": 0, "y": 0, "sw": 1280, "sh": 720, "dy": 3, "dx": -0.2}, "move 0,0|scroll -1,3"},
		{map[string]any{"a": "type", "text": "héllo\n"}, `text "héllo\n"`},
		{map[string]any{"a": "key", "keys": "ctrl+s"}, "key ctrl true|key s true|key s false|key ctrl false"},
		{map[string]any{"a": "key", "keys": "Cmd+Space enter"}, "key cmd true|key space true|key space false|key cmd false|key enter true|key enter false"},
	}
	for _, tc := range cases {
		req := map[string]any{"t": "input"}
		for k, v := range tc.req {
			req[k] = v
		}
		if m := c.call(t, req); m["t"] != "ok" {
			t.Fatalf("%v -> %v", tc.req, m)
		}
		if got := strings.Join(be.take(), "|"); got != tc.want {
			t.Errorf("%v:\n got %s\nwant %s", tc.req, got, tc.want)
		}
	}
	start := time.Now()
	c.call(t, map[string]any{"t": "input", "a": "long_press", "x": 1, "y": 1})
	if d := time.Since(start); d < 550*time.Millisecond {
		t.Errorf("long press lasted %v", d)
	}
	if got := strings.Join(be.take(), "|"); got != "move 1,1|left down 1|left up 1" {
		t.Errorf("long press: %s", got)
	}
	c.call(t, map[string]any{"t": "input", "a": "drag", "x": 0, "y": 0, "x2": 640, "y2": 0, "sw": 1280, "sh": 720, "ms": 160})
	ops := be.take()
	if len(ops) != 13 || ops[0] != "move 0,0" || ops[1] != "left down 1" || ops[11] != "move 960,0" || ops[12] != "left up 1" {
		t.Errorf("drag: %v", ops)
	}

	// errors
	for _, tc := range []struct {
		req  map[string]any
		code string
	}{
		{map[string]any{"t": "input", "a": "click"}, "bad_request"},
		{map[string]any{"t": "input", "a": "key", "keys": "ctrl+nope"}, "bad_request"},
		{map[string]any{"t": "input", "a": "fly"}, "bad_request"},
		{map[string]any{"t": "input", "a": "click", "x": 1, "y": 1, "button": "side"}, "bad_request"},
		{map[string]any{"t": "tree"}, "unsupported"},
		{map[string]any{"t": "tap_node", "node": "n1"}, "unsupported"},
		{map[string]any{"t": "run", "cmd": "rm -rf /"}, "unsupported"},
		{map[string]any{"t": "open", "app": "/bin/sh"}, "not_found"},
	} {
		m := c.call(t, tc.req)
		if m["t"] != "err" || m["code"] != tc.code || m["message"] == "" {
			t.Errorf("%v -> %v, want err %s", tc.req, m, tc.code)
		}
	}
	if ops := be.take(); len(ops) != 0 {
		t.Errorf("refused requests did something: %v", ops)
	}

	// apps / open
	m = c.call(t, map[string]any{"t": "apps"})
	if fmt.Sprint(m["apps"]) != "[map[id:org.example.Editor name:Editor] map[id:calc name:Calculator]]" {
		t.Fatalf("apps %v", m)
	}
	if m := c.call(t, map[string]any{"t": "open", "app": "editor"}); m["t"] != "ok" || fmt.Sprint(be.opened) != "[org.example.Editor]" {
		t.Fatalf("open by name %v %v", m, be.opened)
	}

	// state is only logged; a permission lost is reported by a new hello and the requests' error code
	c.send(t, map[string]any{"t": "state", "busy": true, "by": "claude"})
	be.mu.Lock()
	be.info = backendInfo{Apps: true, Note: "Screen Recording is off", Code: "permission"}
	be.mu.Unlock()
	m = c.call(t, map[string]any{"t": "shot"})
	if m["code"] != "permission" || m["message"] != "Screen Recording is off" {
		t.Fatalf("shot without permission %v", m)
	}

	// reconnect: a new hello, with the new caps
	c.c.Close(websocket.StatusGoingAway, "")
	closeOnce(c.done)
	c = fs.next(t)
	h2 := c.recv(t)
	if h2["t"] != "hello" || fmt.Sprint(h2["caps"]) != "[apps]" || h2["note"] != "Screen Recording is off" || h2["screen"] != nil {
		t.Fatalf("hello after reconnect %v", h2)
	}

	// unpair: config removed, app stops with 0
	c.send(t, map[string]any{"t": "unpair"})
	select {
	case code := <-res:
		if code != 0 {
			t.Fatalf("exit %d", code)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("unpair did not stop the app")
	}
	if cfg, _ := loadConfig(dir); cfg != nil {
		t.Fatal("config kept after unpair")
	}
}

func TestRevokedAndBadCode(t *testing.T) {
	fs := newFakeServer(t)
	dir := filepath.Join(t.TempDir(), "cfg")
	saveConfig(dir, &Config{Server: fs.URL, DeviceID: "dev1", Token: "tok1"})
	fs.revoked.Store(true)
	res := startAgent(t, dir, nil, newFakeBackend())
	select {
	case code := <-res:
		if code != 3 {
			t.Fatalf("exit %d", code)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("revoked token did not stop the app")
	}
	if cfg, _ := loadConfig(dir); cfg != nil {
		t.Fatal("config kept after revocation")
	}

	dir2 := filepath.Join(t.TempDir(), "cfg2")
	res = startAgent(t, dir2, &Trailer{Server: fs.URL, Code: "USED"}, newFakeBackend())
	if code := <-res; code != 1 {
		t.Fatalf("bad code exit %d", code)
	}
}

func TestBusyQueue(t *testing.T) {
	be := newFakeBackend()
	a := newAgent(&Config{}, be, testLog)
	var sent []map[string]any
	// no connection: handle() still queues; fill the queue beyond its size
	for i := 0; i < maxQueue; i++ {
		a.handle(request{T: "shot", ID: json.RawMessage(fmt.Sprint(i))})
	}
	if len(a.reqs) != maxQueue {
		t.Fatalf("queue %d", len(a.reqs))
	}
	a.handle(request{T: "shot", ID: json.RawMessage("99")}) // dropped with a busy reply (not connected here)
	if len(a.reqs) != maxQueue || sent != nil {
		t.Fatal("queue overflow")
	}
	if a.handle(request{T: "unpair"}) != true {
		t.Fatal("unpair")
	}
}
