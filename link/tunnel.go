package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand/v2"
	"net/http"
	"os"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"
)

const (
	maxFrame = 16 << 20 // bytes, both directions
	maxQueue = 16       // requests waiting for the worker; more = "busy"
)

var (
	pingEvery   = 30 * time.Second
	pingTimeout = 20 * time.Second
	writeWait   = 30 * time.Second
	dialWait    = 20 * time.Second
	stableAfter = 30 * time.Second
	backoffBase = time.Second
	backoffMax  = 60 * time.Second

	errRevoked  = errors.New("token revoked")
	errUnpaired = errors.New("unpaired by the server")
)

// backoff returns the wait before reconnect attempt n (0-based): 1 s, 2 s, 4 s ... 60 s, + up to 20 % jitter.
func backoff(n int) time.Duration {
	d := backoffMax
	if n < 16 {
		if v := backoffBase << n; v < backoffMax {
			d = v
		}
	}
	return d + time.Duration(rand.Int64N(int64(d)/5+1))
}

// serverClient talks to the configured server only: TLS verified, no redirects, HTTP/1.1.
func serverClient(timeout time.Duration) *http.Client {
	tr := http.DefaultTransport.(*http.Transport).Clone()
	tr.TLSClientConfig = &tls.Config{MinVersion: tls.VersionTLS12}
	tr.ForceAttemptHTTP2 = false
	tr.MaxIdleConns = 1
	return &http.Client{
		Transport: tr,
		Timeout:   timeout,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return errors.New("redirect refused")
		},
	}
}

// ---- pairing ----

type pairError struct{ Code, Message string }

func (e *pairError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	return e.Code
}

func pair(ctx context.Context, tr *Trailer, caps []string) (*Config, error) {
	if caps == nil {
		caps = []string{}
	}
	body, _ := json.Marshal(map[string]any{
		"code": tr.Code, "name": deviceName(), "os": runtime.GOOS, "arch": runtime.GOARCH,
		"version": version, "caps": caps,
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, tr.Server+"/api/devices/pair", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := serverClient(20 * time.Second).Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if resp.StatusCode >= 400 && resp.StatusCode < 500 {
		var e struct{ Error, Message string }
		_ = json.Unmarshal(b, &e)
		if e.Error == "" {
			e.Error = fmt.Sprintf("http_%d", resp.StatusCode)
		}
		return nil, &pairError{Code: e.Error, Message: e.Message}
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("pairing: server answered %d", resp.StatusCode)
	}
	var r struct {
		DeviceID string `json:"device_id"`
		Token    string `json:"token"`
	}
	if err := json.Unmarshal(b, &r); err != nil || r.Token == "" {
		return nil, errors.New("pairing: bad answer from the server")
	}
	return &Config{Server: tr.Server, DeviceID: r.DeviceID, Token: r.Token, PairedCode: tr.Code}, nil
}

// pairWithRetry retries network / 5xx failures a few times; a 4xx answer is final.
func pairWithRetry(ctx context.Context, tr *Trailer, caps []string, logf func(string, ...any)) (*Config, error) {
	var err error
	for n := 0; n < 6; n++ {
		var c *Config
		if c, err = pair(ctx, tr, caps); err == nil {
			return c, nil
		}
		var pe *pairError
		if errors.As(err, &pe) {
			return nil, err
		}
		logf("pairing failed: %v", err)
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(backoff(n)):
		}
	}
	return nil, err
}

// ---- control channel ----

type agent struct {
	cfg  *Config
	be   backend
	logf func(string, ...any)
	say  func(lineKind, string) // live log in the terminal (defaults to logf)

	online  bool   // the live log tells only the changes of the connection
	busyBy  string // who has the device, from the last "state" frame
	access  string // "" (not told yet), "wait", "view" or "control", from the last "access" frame
	watched bool   // someone watches the live view, from the last "watch" frame

	connMu    sync.Mutex
	conn      *websocket.Conn
	lastHello string

	reqs chan request
}

func newAgent(cfg *Config, be backend, logf func(string, ...any)) *agent {
	return &agent{cfg: cfg, be: be, logf: logf, say: logSay(logf), reqs: make(chan request, maxQueue)}
}

// deviceName is the name shown in Harness (the host name).
func deviceName() string {
	n, _ := os.Hostname()
	n = strings.TrimSuffix(strings.TrimSuffix(n, ".local"), ".lan")
	if n == "" {
		n = runtime.GOOS
	}
	return n
}

// run keeps the control channel up until the token is revoked, the server unpairs, or ctx ends.
func (a *agent) run(ctx context.Context) error {
	go a.worker(ctx)
	for n := 0; ; {
		start := time.Now()
		err := a.session(ctx)
		if errors.Is(err, errRevoked) || errors.Is(err, errUnpaired) {
			return err
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if time.Since(start) > stableAfter {
			n = 0
		}
		d := backoff(n)
		n++
		a.logf("control link down (%v); retry in %s", err, d.Round(100*time.Millisecond))
		if a.online || n == 1 {
			a.say(lWarn, "Cannot reach Harness Maxxing ("+shortErr(err)+"), retrying...")
		}
		a.online = false
		t := time.NewTimer(d)
		select {
		case <-ctx.Done():
			t.Stop()
			return ctx.Err()
		case <-t.C:
		}
	}
}

// hello is the first frame of every connection; it is sent again whenever it changes
// (screen resized, a permission granted...).
func (a *agent) hello() map[string]any {
	inf := a.be.Info()
	h := map[string]any{"t": "hello", "v": version, "os": runtime.GOOS, "arch": runtime.GOARCH,
		"name": deviceName(), "kind": "desktop", "caps": inf.capsList()}
	if inf.Screen != nil {
		h["screen"] = map[string]any{"w": inf.Screen.W, "h": inf.Screen.H, "scale": inf.Screen.Scale}
	}
	if len(inf.Displays) > 0 {
		l := make([]map[string]any, 0, len(inf.Displays))
		for i, d := range inf.Displays {
			l = append(l, map[string]any{"i": i, "name": d.Name, "w": d.W, "h": d.H, "main": d.Main})
		}
		h["screens"], h["display"] = l, inf.Display
	}
	if inf.Note != "" {
		h["note"] = inf.Note
	}
	return h
}

func (a *agent) sendHello(conn *websocket.Conn, force bool) error {
	h := a.hello()
	b, _ := json.Marshal(h)
	a.connMu.Lock()
	same := string(b) == a.lastHello
	a.lastHello = string(b)
	a.connMu.Unlock()
	if same && !force {
		return nil
	}
	if note, _ := h["note"].(string); note != "" {
		a.say(lWarn, note)
	}
	return a.write(conn, h)
}

func (a *agent) session(ctx context.Context) (err error) {
	defer func() {
		if r := recover(); r != nil {
			a.logf("panic in session: %v", r)
			err = fmt.Errorf("panic: %v", r)
		}
	}()
	dctx, cancel := context.WithTimeout(ctx, dialWait)
	conn, resp, err := websocket.Dial(dctx, a.cfg.Server+"/api/devices/ws", &websocket.DialOptions{
		HTTPClient: serverClient(0),
		HTTPHeader: http.Header{"Authorization": {"Bearer " + a.cfg.Token}},
	})
	cancel()
	if err != nil {
		if resp != nil && (resp.StatusCode == 401 || resp.StatusCode == 403) {
			return errRevoked
		}
		return err
	}
	conn.SetReadLimit(maxFrame)
	sctx, scancel := context.WithCancel(ctx)
	defer scancel()

	a.connMu.Lock()
	a.conn = conn
	a.connMu.Unlock()
	defer a.disconnected(conn)

	if err := a.sendHello(conn, true); err != nil {
		return err
	}
	a.logf("connected to %s", a.cfg.Server)
	if !a.online {
		a.say(lOK, fmt.Sprintf("Connected to %s as %s", hostOf(a.cfg.Server), deviceName()))
	}
	a.online = true

	go safely(a.logf, "ping", func() {
		t := time.NewTicker(pingEvery)
		defer t.Stop()
		for {
			select {
			case <-sctx.Done():
				return
			case <-t.C:
				pctx, c := context.WithTimeout(sctx, pingTimeout)
				err := conn.Ping(pctx)
				c()
				if err != nil && sctx.Err() == nil {
					a.logf("ping failed: %v", err)
					conn.CloseNow()
					return
				}
				_ = a.sendHello(conn, false)
			}
		}
	})

	for {
		typ, data, err := conn.Read(sctx)
		if err != nil {
			return err
		}
		if typ != websocket.MessageText {
			continue
		}
		var r request
		if err := json.Unmarshal(data, &r); err != nil {
			a.logf("bad frame ignored: %v", err)
			continue
		}
		if a.handle(r) {
			conn.CloseNow()
			return errUnpaired
		}
	}
}

func (a *agent) disconnected(conn *websocket.Conn) {
	conn.CloseNow()
	a.connMu.Lock()
	defer a.connMu.Unlock()
	if a.conn == conn {
		a.conn = nil
		a.lastHello = ""
	}
}

func (a *agent) write(conn *websocket.Conn, v any) error {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return err
	}
	b := bytes.TrimSuffix(buf.Bytes(), []byte("\n"))
	if len(b) > maxFrame {
		return errors.New("frame too large")
	}
	ctx, cancel := context.WithTimeout(context.Background(), writeWait)
	defer cancel()
	if err := conn.Write(ctx, websocket.MessageText, b); err != nil {
		conn.CloseNow() // force a reconnect
		return err
	}
	return nil
}

func (a *agent) current() *websocket.Conn {
	a.connMu.Lock()
	defer a.connMu.Unlock()
	return a.conn
}

// send writes to the current control connection (dropped if there is none).
func (a *agent) send(v any) error {
	c := a.current()
	if c == nil {
		return errors.New("not connected")
	}
	return a.write(c, v)
}

// handle dispatches one server frame; it returns true on unpair.
func (a *agent) handle(r request) bool {
	switch r.T {
	case "unpair":
		return true
	case "display":
		i := -1
		if r.I != nil {
			i = *r.I
		}
		a.be.SetDisplay(i)
		inf := a.be.Info()
		a.logf("display: %d -> %d", i, inf.Display)
		if len(inf.Displays) > 1 && inf.Display < len(inf.Displays) {
			d := inf.Displays[inf.Display]
			a.say(lInfo, fmt.Sprintf("Screen: %s (%dx%d)", d.Name, d.W, d.H))
		}
		a.helloAgain()
	case "watch":
		if r.On != a.watched {
			a.watched = r.On
			if r.On {
				a.say(lClaude, "Live view: your screen is shown in Harness Maxxing")
			} else {
				a.say(lInfo, "Live view closed")
			}
		}
	case "access":
		now := "wait"
		if r.OK != nil && *r.OK {
			now = "view"
			if r.Mode == "control" {
				now = "control"
			}
		}
		a.logf("access: %s", now)
		if now != a.access {
			a.say(accessLine(a.access, now))
			a.access = now
		}
	case "state":
		a.logf("state: busy=%v by=%s", r.Busy != nil && *r.Busy, r.By)
		by := r.By
		if r.Busy == nil || !*r.Busy {
			by = ""
		}
		if by != a.busyBy {
			switch by {
			case "claude":
				a.say(lClaude, "Claude is using this computer")
			case "human":
				a.say(lWarn, "Someone took over in Harness Maxxing: Claude waits")
			default:
				a.say(lInfo, "Claude is not using this computer right now")
			}
			a.busyBy = by
		}
	case "shot", "input", "apps", "open", "tree", "tap_node", "set_text":
		if len(r.ID) == 0 {
			a.logf("%s without id ignored", r.T)
			return false
		}
		select {
		case a.reqs <- r:
		default:
			a.send(errReply(r.ID, &opError{"busy", "too many requests waiting"}))
		}
	default:
		a.logf("unknown frame %q", r.T)
		if len(r.ID) > 0 {
			a.send(errReply(r.ID, &opError{"unsupported", "unknown request " + strconv.Quote(r.T)}))
		}
	}
	return false
}

// worker runs the requests one at a time, in arrival order (input must not interleave).
func (a *agent) worker(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case r := <-a.reqs:
			var reply map[string]any
			safely(a.logf, "request "+r.T, func() { reply = a.serve(r) })
			if reply == nil {
				reply = errReply(r.ID, &opError{"failed", "internal error"})
			}
			if err := a.send(reply); err != nil {
				a.logf("reply to %s lost: %v", r.T, err)
			}
		}
	}
}

// accessLine is what the live log says when the access of this computer changes.
func accessLine(before, now string) (lineKind, string) {
	switch now {
	case "wait":
		return lWarn, "Waiting for your OK: accept this computer in Harness Maxxing (Settings > Devices)"
	case "view":
		if before == "control" {
			return lInfo, "Now View only: Claude looks at the screen but does not click or type"
		}
		if before == "wait" {
			return lOK, "Accepted (View only): Claude can look at the screen, not click or type"
		}
		return lOK, "Ready (View only): Claude can look at the screen, not click or type"
	}
	if before == "view" {
		return lInfo, "Now Control: Claude can click, type and open apps"
	}
	if before == "wait" {
		return lOK, "Accepted (Control): Claude can look, click, type and open apps"
	}
	return lOK, "Ready (Control): Claude can look, click, type and open apps"
}

// helloAgain sends the hello frame now if it changed (the screen in use changed).
func (a *agent) helloAgain() {
	if c := a.current(); c != nil {
		_ = a.sendHello(c, false)
	}
}
