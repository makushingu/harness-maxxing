//go:build !windows

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"github.com/coder/websocket"
)

// ---- fake browser: the test binary re-executed with HARNESS_PC_FAKE_BROWSER=1 ----

func TestMain(m *testing.M) {
	if os.Getenv("HARNESS_PC_FAKE_CHILD") == "1" {
		select {} // a "renderer" that never exits by itself
	}
	if os.Getenv("HARNESS_PC_FAKE_BROWSER") == "1" {
		fakeBrowser()
		os.Exit(0)
	}
	os.Exit(m.Run())
}

func fakeBrowser() {
	var port, prof string
	for _, a := range os.Args[1:] {
		if v, ok := strings.CutPrefix(a, "--remote-debugging-port="); ok {
			port = v
		}
		if v, ok := strings.CutPrefix(a, "--user-data-dir="); ok {
			prof = v
		}
	}
	os.WriteFile(filepath.Join(prof, "args.txt"), []byte(strings.Join(os.Args[1:], "\n")), 0o600)
	os.WriteFile(filepath.Join(prof, "pid"), []byte(strconv.Itoa(os.Getpid())), 0o600)
	self, _ := os.Executable()
	child := exec.Command(self)
	child.Env = append(os.Environ(), "HARNESS_PC_FAKE_CHILD=1")
	child.Start()
	os.WriteFile(filepath.Join(prof, "child.pid"), []byte(strconv.Itoa(child.Process.Pid)), 0o600)
	time.Sleep(200 * time.Millisecond) // like a real browser, DevTools is not up at once
	mux := http.NewServeMux()
	mux.HandleFunc("/json/version", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, `{"Browser":"Fake/1.0","webSocketDebuggerUrl":"ws://127.0.0.1:%s/devtools/browser/fake-1"}`, port)
	})
	mux.HandleFunc("/devtools/browser/fake-1", func(w http.ResponseWriter, r *http.Request) {
		c, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		c.SetReadLimit(maxFrame)
		for {
			typ, b, err := c.Read(r.Context())
			if err != nil {
				return
			}
			if strings.Contains(string(b), "close-me") {
				c.Close(websocket.StatusNormalClosure, "")
				return
			}
			c.Write(r.Context(), typ, b)
		}
	})
	http.ListenAndServe("127.0.0.1:"+port, mux)
}

// ---- fake server ----

type sconn struct {
	c    *websocket.Conn
	done chan struct{}
}

type fakeServer struct {
	*httptest.Server
	conns    chan *sconn
	unavail  atomic.Bool
	revoked  atomic.Bool
	lastAuth atomic.Value
}

func newFakeServer(t *testing.T) *fakeServer {
	fs := &fakeServer{conns: make(chan *sconn, 4)}
	mux := http.NewServeMux()
	mux.HandleFunc("POST /api/pc/pair", func(w http.ResponseWriter, r *http.Request) {
		var req map[string]any
		json.NewDecoder(r.Body).Decode(&req)
		if req["code"] != "GOOD" {
			w.WriteHeader(400)
			fmt.Fprint(w, `{"error":"bad_code","message":"unknown code"}`)
			return
		}
		fmt.Fprint(w, `{"device_id":"dev1","token":"tok1"}`)
	})
	mux.HandleFunc("/api/pc/ws", func(w http.ResponseWriter, r *http.Request) {
		fs.lastAuth.Store(r.Header.Get("Authorization"))
		if fs.revoked.Load() || r.Header.Get("Authorization") != "Bearer tok1" {
			w.WriteHeader(401)
			return
		}
		if fs.unavail.Load() {
			w.WriteHeader(503)
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
		t.Fatal("agent did not connect")
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
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer cancel()
	_, b, err := c.c.Read(ctx)
	if err != nil {
		t.Fatalf("recv: %v", err)
	}
	var m map[string]any
	json.Unmarshal(b, &m)
	return m
}

func (c *sconn) expect(t *testing.T, typ string) map[string]any {
	t.Helper()
	m := c.recv(t)
	if m["t"] != typ {
		t.Fatalf("got %v, want t=%s", m, typ)
	}
	return m
}

func testLog(f string, a ...any) {
	if testing.Verbose() {
		fmt.Fprintf(os.Stderr, "  %s agent: "+f+"\n", append([]any{time.Now().Format("05.000")}, a...)...)
	}
}

func setupFakeBrowser(t *testing.T) {
	self, _ := os.Executable()
	t.Setenv("HARNESS_PC_BROWSER_PATH", self)
	t.Setenv("HARNESS_PC_FAKE_BROWSER", "1")
	t.Setenv("HARNESS_PC_HEADLESS", "")
	old := backoffBase
	backoffBase = 50 * time.Millisecond
	t.Cleanup(func() { backoffBase = old })
}

func startAgent(t *testing.T, dir string, tr *Trailer) (chan int, context.CancelFunc) {
	ctx, cancel := context.WithCancel(context.Background())
	res := make(chan int, 1)
	done := make(chan struct{})
	go func() {
		defer close(done)
		res <- runAgent(ctx, runOpts{dir: dir, trailer: tr, logf: testLog})
	}()
	t.Cleanup(func() {
		cancel()
		select {
		case <-done:
		case <-time.After(15 * time.Second):
			t.Error("agent did not stop")
		}
	})
	return res, cancel
}

func readPid(t *testing.T, p string) int {
	b, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	n, _ := strconv.Atoi(string(b))
	return n
}

func waitDead(t *testing.T, pid int, what string) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if syscall.Kill(pid, 0) == syscall.ESRCH {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("%s (pid %d) still alive", what, pid)
}

func TestIntegration(t *testing.T) {
	setupFakeBrowser(t)
	fs := newFakeServer(t)
	dir := filepath.Join(t.TempDir(), "cfg")
	res, _ := startAgent(t, dir, &Trailer{Server: fs.URL, Code: "GOOD", Browser: "chrome"})

	c := fs.next(t)
	hello := c.expect(t, "hello")
	if hello["running"] != false || !strings.Contains(fmt.Sprint(hello["browsers"]), "chrome") || hello["v"] != version {
		t.Fatalf("hello %v", hello)
	}
	cfg, err := loadConfig(dir)
	if err != nil || cfg == nil || cfg.Token != "tok1" || cfg.PairedCode != "GOOD" || cfg.DeviceID != "dev1" {
		t.Fatalf("config %+v %v", cfg, err)
	}
	if st, _ := os.Stat(filepath.Join(dir, configName)); st.Mode().Perm() != 0o600 {
		t.Fatalf("config mode %v", st.Mode())
	}

	// open before launch fails cleanly
	c.send(t, map[string]any{"t": "open", "ch": "early"})
	if m := c.expect(t, "opened"); m["ok"] != false {
		t.Fatalf("open before launch: %v", m)
	}

	c.send(t, map[string]any{"t": "launch", "id": 1, "browser": "chrome"})
	if m := c.expect(t, "launched"); m["ok"] != true || m["id"] != float64(1) {
		t.Fatalf("launch: %v", m)
	}
	c.send(t, map[string]any{"t": "launch", "id": "again", "browser": "chrome"})
	if m := c.expect(t, "launched"); m["ok"] != true || m["id"] != "again" {
		t.Fatalf("second launch: %v", m)
	}
	prof := filepath.Join(dir, "profile-chrome")
	args, _ := os.ReadFile(filepath.Join(prof, "args.txt"))
	for _, want := range []string{"--remote-debugging-address=127.0.0.1", "--user-data-dir=" + prof, "--no-first-run", "--no-default-browser-check"} {
		if !strings.Contains(string(args), want) {
			t.Fatalf("browser args miss %s:\n%s", want, args)
		}
	}
	if strings.Contains(string(args), "--headless") {
		t.Fatal("headless not asked")
	}
	childPid := readPid(t, filepath.Join(prof, "child.pid"))

	// a channel relays frames both ways
	c.send(t, map[string]any{"t": "open", "ch": "c1"})
	if m := c.expect(t, "opened"); m["ok"] != true || m["ch"] != "c1" {
		t.Fatalf("open: %v", m)
	}
	frame := `{"id":1,"method":"Browser.getVersion","params":{"x":"<&>é"}}`
	c.send(t, map[string]any{"t": "data", "ch": "c1", "d": frame})
	if m := c.expect(t, "data"); m["d"] != frame || m["ch"] != "c1" {
		t.Fatalf("relay: %v", m)
	}
	big := `{"id":2,"method":"Runtime.evaluate","params":{"expression":"` + strings.Repeat("x", 900<<10) + `"}}`
	c.send(t, map[string]any{"t": "data", "ch": "c1", "d": big})
	if m := c.expect(t, "data"); m["d"] != big {
		t.Fatal("big frame not relayed")
	}
	// the DevTools filter answers in the browser's place
	c.send(t, map[string]any{"t": "data", "ch": "c1", "d": `{"id":3,"method":"Page.navigate","params":{"url":"file:///etc/passwd"}}`})
	if m := c.expect(t, "data"); !strings.Contains(m["d"].(string), `"id":3`) || !strings.Contains(m["d"].(string), "-32000") {
		t.Fatalf("file: url not refused: %v", m)
	}
	// server ends it, the id can be reused
	c.send(t, map[string]any{"t": "end", "ch": "c1"})
	c.send(t, map[string]any{"t": "bogus"}) // ignored
	c.send(t, map[string]any{"t": "open", "ch": "c1"})
	if m := c.expect(t, "opened"); m["ok"] != true {
		t.Fatalf("reopen: %v", m)
	}
	// the browser side closes a channel -> end
	c.send(t, map[string]any{"t": "data", "ch": "c1", "d": `{"id":4,"method":"Runtime.evaluate","params":{"expression":"close-me"}}`})
	if m := c.expect(t, "end"); m["ch"] != "c1" {
		t.Fatalf("end: %v", m)
	}
	// channel limit
	for i := 0; i < maxChannels; i++ {
		c.send(t, map[string]any{"t": "open", "ch": i})
		if m := c.expect(t, "opened"); m["ok"] != true {
			t.Fatalf("open %d: %v", i, m)
		}
	}
	c.send(t, map[string]any{"t": "open", "ch": 99})
	if m := c.expect(t, "opened"); m["ok"] != false || m["error"] != "too many channels" {
		t.Fatalf("limit: %v", m)
	}

	// close kills the whole tree
	c.send(t, map[string]any{"t": "close", "id": 3})
	if m := c.expect(t, "closed"); m["ok"] != true {
		t.Fatalf("close: %v", m)
	}
	waitDead(t, childPid, "browser child")
	c.send(t, map[string]any{"t": "open", "ch": "late"})
	if m := c.expect(t, "opened"); m["ok"] != false {
		t.Fatalf("open after close: %v", m)
	}

	// the user closes the browser -> exited
	c.send(t, map[string]any{"t": "launch", "id": 4, "headless": true})
	if m := c.expect(t, "launched"); m["ok"] != true {
		t.Fatalf("relaunch: %v", m)
	}
	args, _ = os.ReadFile(filepath.Join(prof, "args.txt"))
	if !strings.Contains(string(args), "--headless=new") {
		t.Fatal("headless asked but not passed")
	}
	syscall.Kill(readPid(t, filepath.Join(prof, "pid")), syscall.SIGTERM)
	c.expect(t, "exited")

	// wipe deletes the profile
	c.send(t, map[string]any{"t": "wipe", "id": 5})
	if m := c.expect(t, "wiped"); m["ok"] != true {
		t.Fatalf("wipe: %v", m)
	}
	if _, err := os.Stat(prof); !os.IsNotExist(err) {
		t.Fatal("profile still there")
	}

	// the link drops -> the agent reconnects and says hello again
	c.c.CloseNow()
	closeOnce(c.done)
	c = fs.next(t)
	c.expect(t, "hello")

	c.send(t, map[string]any{"t": "unpair"})
	select {
	case code := <-res:
		if code != 0 {
			t.Fatalf("exit code %d", code)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("agent did not exit on unpair")
	}
	if _, err := os.Stat(filepath.Join(dir, configName)); !os.IsNotExist(err) {
		t.Fatal("config not deleted on unpair")
	}
}

func TestDropGraceClosesBrowser(t *testing.T) {
	setupFakeBrowser(t)
	old := dropGrace
	dropGrace = 300 * time.Millisecond
	t.Cleanup(func() { dropGrace = old })
	fs := newFakeServer(t)
	dir := t.TempDir()
	saveConfig(dir, &Config{Server: fs.URL, DeviceID: "dev1", Token: "tok1", Browser: "brave", PairedCode: "GOOD"})
	startAgent(t, dir, &Trailer{Server: fs.URL, Code: "GOOD"}) // same code: no new pairing
	c := fs.next(t)
	c.expect(t, "hello")
	c.send(t, map[string]any{"t": "launch", "id": 1})
	if m := c.expect(t, "launched"); m["ok"] != true {
		t.Fatalf("launch: %v", m)
	}
	pid := readPid(t, filepath.Join(dir, "profile-brave", "pid"))
	fs.unavail.Store(true)
	c.c.CloseNow()
	closeOnce(c.done)
	waitDead(t, pid, "browser after the grace period")
	fs.unavail.Store(false)
	c = fs.next(t)
	if h := c.expect(t, "hello"); h["running"] != false {
		t.Fatalf("hello after drop: %v", h)
	}
}

func TestRevokedTokenStops(t *testing.T) {
	setupFakeBrowser(t)
	fs := newFakeServer(t)
	fs.revoked.Store(true)
	dir := t.TempDir()
	saveConfig(dir, &Config{Server: fs.URL, DeviceID: "dev1", Token: "tok1"})
	res, _ := startAgent(t, dir, nil)
	select {
	case code := <-res:
		if code != 3 {
			t.Fatalf("exit code %d", code)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("agent kept retrying a revoked token")
	}
	if _, err := os.Stat(filepath.Join(dir, configName)); !os.IsNotExist(err) {
		t.Fatal("config not deleted")
	}
}

func TestBadCodeAndNoConfig(t *testing.T) {
	setupFakeBrowser(t)
	fs := newFakeServer(t)
	res, _ := startAgent(t, t.TempDir(), &Trailer{Server: fs.URL, Code: "USED"})
	if code := <-res; code != 1 {
		t.Fatalf("bad code exit %d", code)
	}
	res, _ = startAgent(t, t.TempDir(), nil)
	if code := <-res; code != 2 {
		t.Fatalf("no config exit %d", code)
	}
}

func TestSingleInstanceLock(t *testing.T) {
	p := filepath.Join(t.TempDir(), lockName)
	unlock, err := lockInstance(p)
	if err != nil {
		t.Fatal(err)
	}
	// flock is per open file description: a second open in the same process conflicts too
	if _, err := lockInstance(p); err == nil {
		t.Fatal("second lock succeeded")
	}
	unlock()
	u2, err := lockInstance(p)
	if err != nil {
		t.Fatal(err)
	}
	u2()
}
