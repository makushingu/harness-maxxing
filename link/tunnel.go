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
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"
)

const (
	maxFrame    = 16 << 20 // bytes, both directions
	maxChannels = 16
	chanQueue   = 16 // x maxCommand: at most 16 MB waiting per channel
)

var (
	pingEvery   = 30 * time.Second
	pingTimeout = 20 * time.Second
	writeWait   = 30 * time.Second
	dialWait    = 20 * time.Second
	dropGrace   = 2 * time.Minute // browser kept alive while the control link is down
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

// localClient dials the browser on 127.0.0.1 only, never through a proxy.
var localClient = &http.Client{
	Transport: &http.Transport{Proxy: nil, DisableKeepAlives: true},
	CheckRedirect: func(*http.Request, []*http.Request) error {
		return errors.New("redirect refused")
	},
}

// ---- pairing ----

type pairError struct{ Code, Message string }

func (e *pairError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	return e.Code
}

func pair(ctx context.Context, tr *Trailer) (*Config, error) {
	name, _ := os.Hostname()
	body, _ := json.Marshal(map[string]any{
		"code": tr.Code, "name": name, "os": runtime.GOOS, "arch": runtime.GOARCH,
		"browsers": detectBrowsers(), "version": version,
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, tr.Server+"/api/pc/pair", bytes.NewReader(body))
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
	return &Config{Server: tr.Server, DeviceID: r.DeviceID, Token: r.Token, Browser: tr.Browser,
		Autostart: tr.Autostart, PairedCode: tr.Code}, nil
}

// pairWithRetry retries network / 5xx failures a few times; a 4xx answer is final.
func pairWithRetry(ctx context.Context, tr *Trailer, logf func(string, ...any)) (*Config, error) {
	var err error
	for n := 0; n < 6; n++ {
		var c *Config
		if c, err = pair(ctx, tr); err == nil {
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

type msg struct {
	T        string          `json:"t"`
	ID       json.RawMessage `json:"id,omitempty"`
	Ch       json.RawMessage `json:"ch,omitempty"`
	D        *string         `json:"d,omitempty"`
	Browser  string          `json:"browser,omitempty"`
	Headless bool            `json:"headless,omitempty"`
}

type agent struct {
	cfg      *Config
	browsers *browserManager
	logf     func(string, ...any)
	onFirst  func() // called once after the first successful connection

	connMu    sync.Mutex
	conn      *websocket.Conn
	dropTimer *time.Timer

	chMu     sync.Mutex
	channels map[string]*channel

	ops       chan msg
	firstOnce sync.Once
}

func newAgent(cfg *Config, dir string, logf func(string, ...any)) *agent {
	a := &agent{cfg: cfg, logf: logf, channels: map[string]*channel{}, ops: make(chan msg, 16)}
	a.browsers = &browserManager{dir: dir, logf: logf, last: cfg.Browser}
	a.browsers.onExit = func(string) {
		a.endAll(true)
		a.send(map[string]any{"t": "exited"})
	}
	return a
}

// run keeps the control channel up until the token is revoked, the server unpairs, or ctx ends.
func (a *agent) run(ctx context.Context) error {
	go a.opsWorker(ctx)
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
		t := time.NewTimer(d)
		select {
		case <-ctx.Done():
			t.Stop()
			return ctx.Err()
		case <-t.C:
		}
	}
}

func (a *agent) session(ctx context.Context) (err error) {
	defer func() {
		if r := recover(); r != nil {
			a.logf("panic in session: %v", r)
			err = fmt.Errorf("panic: %v", r)
		}
	}()
	dctx, cancel := context.WithTimeout(ctx, dialWait)
	conn, resp, err := websocket.Dial(dctx, a.cfg.Server+"/api/pc/ws", &websocket.DialOptions{
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
	if a.dropTimer != nil {
		a.dropTimer.Stop()
		a.dropTimer = nil
	}
	a.connMu.Unlock()
	defer a.disconnected(conn)

	name, _ := os.Hostname()
	if err := a.write(conn, map[string]any{
		"t": "hello", "v": version, "os": runtime.GOOS, "arch": runtime.GOARCH, "name": name,
		"browsers": detectBrowsers(), "running": a.browsers.Running(),
	}); err != nil {
		return err
	}
	a.logf("connected to %s", a.cfg.Server)
	a.firstOnce.Do(func() {
		if a.onFirst != nil {
			go safely(a.logf, "first-connect", a.onFirst)
		}
	})

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
		var m msg
		if err := json.Unmarshal(data, &m); err != nil {
			a.logf("bad frame ignored: %v", err)
			continue
		}
		if a.handle(m) {
			conn.CloseNow()
			return errUnpaired
		}
	}
}

func (a *agent) disconnected(conn *websocket.Conn) {
	conn.CloseNow()
	a.endAll(false)
	a.connMu.Lock()
	defer a.connMu.Unlock()
	if a.conn == conn {
		a.conn = nil
	}
	if a.browsers.Running() && a.dropTimer == nil {
		a.dropTimer = time.AfterFunc(dropGrace, func() {
			a.connMu.Lock()
			still := a.conn == nil
			a.dropTimer = nil
			a.connMu.Unlock()
			if still {
				a.logf("control link down for %s: closing the browser", dropGrace)
				a.browsers.Close()
			}
		})
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

// send writes to the current control connection (dropped if there is none).
func (a *agent) send(v any) error {
	a.connMu.Lock()
	c := a.conn
	a.connMu.Unlock()
	if c == nil {
		return errors.New("not connected")
	}
	return a.write(c, v)
}

// handle dispatches one server frame; it returns true on unpair.
func (a *agent) handle(m msg) bool {
	switch m.T {
	case "launch", "close", "wipe":
		select {
		case a.ops <- m:
		default:
			a.send(map[string]any{"t": replyName(m.T), "id": m.ID, "ok": false, "error": "busy"})
		}
	case "open":
		a.open(m.Ch)
	case "data":
		if m.D != nil {
			a.toBrowser(m.Ch, *m.D)
		}
	case "end":
		if c := a.takeChannel(string(m.Ch)); c != nil {
			c.finish(false)
		}
	case "unpair":
		return true
	default:
		a.logf("unknown frame %q ignored", m.T)
	}
	return false
}

func replyName(t string) string {
	return map[string]string{"launch": "launched", "close": "closed", "wipe": "wiped"}[t]
}

// opsWorker runs launch / close / wipe one at a time, in arrival order.
func (a *agent) opsWorker(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case m := <-a.ops:
			safely(a.logf, "op "+m.T, func() { a.doOp(ctx, m) })
		}
	}
}

func (a *agent) doOp(ctx context.Context, m msg) {
	reply := map[string]any{"t": replyName(m.T), "id": m.ID, "ok": true}
	var err error
	switch m.T {
	case "launch":
		id := m.Browser
		if id == "" {
			id = a.cfg.Browser
		}
		if id == "" {
			if l := detectBrowsers(); len(l) > 0 {
				id = l[0]
			}
		}
		lctx, cancel := context.WithTimeout(ctx, launchTimeout+5*time.Second)
		err = a.browsers.Launch(lctx, id, m.Headless || envHeadless())
		cancel()
	case "close":
		a.endAll(false)
		a.browsers.Close()
	case "wipe":
		a.endAll(false)
		err = a.browsers.Wipe("")
	}
	if err != nil {
		a.logf("%s failed: %v", m.T, err)
		reply["ok"] = false
		reply["error"] = err.Error()
	}
	a.send(reply)
}

// ---- channels (one browser DevTools websocket each) ----

type channel struct {
	a      *agent
	key    string
	ch     json.RawMessage
	in     chan string
	ctx    context.Context
	cancel context.CancelFunc
	once   sync.Once
	mu     sync.Mutex
	conn   *websocket.Conn
}

func (a *agent) open(ch json.RawMessage) {
	key := string(ch)
	fail := func(e string) { a.send(map[string]any{"t": "opened", "ch": ch, "ok": false, "error": e}) }
	if len(ch) == 0 || len(ch) > 128 {
		fail("bad channel id")
		return
	}
	a.chMu.Lock()
	if _, dup := a.channels[key]; dup {
		a.chMu.Unlock()
		fail("channel already open")
		return
	}
	if len(a.channels) >= maxChannels {
		a.chMu.Unlock()
		fail("too many channels")
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	c := &channel{a: a, key: key, ch: ch, in: make(chan string, chanQueue), ctx: ctx, cancel: cancel}
	a.channels[key] = c
	a.chMu.Unlock()
	go safely(a.logf, "channel", c.run)
}

func (a *agent) takeChannel(key string) *channel {
	a.chMu.Lock()
	defer a.chMu.Unlock()
	c := a.channels[key]
	delete(a.channels, key)
	return c
}

// dropChannel removes c from the table if it is still there (a reused id may belong to a newer channel).
func (a *agent) dropChannel(c *channel) bool {
	a.chMu.Lock()
	defer a.chMu.Unlock()
	if a.channels[c.key] != c {
		return false
	}
	delete(a.channels, c.key)
	return true
}

func (a *agent) endAll(notify bool) {
	a.chMu.Lock()
	l := make([]*channel, 0, len(a.channels))
	for k, c := range a.channels {
		l = append(l, c)
		delete(a.channels, k)
	}
	a.chMu.Unlock()
	for _, c := range l {
		c.finish(notify)
	}
}

func (a *agent) toBrowser(ch json.RawMessage, d string) {
	a.chMu.Lock()
	c := a.channels[string(ch)]
	a.chMu.Unlock()
	if c == nil {
		return
	}
	if reason, call := checkCommand(d); reason != "" {
		a.logf("refused: %s", reason)
		if b := refusal(call, reason); b != nil {
			a.send(map[string]any{"t": "data", "ch": c.ch, "d": string(b)})
		}
		return
	}
	t := time.NewTimer(10 * time.Second)
	defer t.Stop()
	select {
	case c.in <- d:
	case <-c.ctx.Done():
	case <-t.C:
		a.logf("channel %s: browser too slow, closed", c.key)
		if a.dropChannel(c) {
			c.finish(true)
		}
	}
}

// finish closes the channel once; notify sends {"t":"end"} to the server.
func (c *channel) finish(notify bool) {
	c.once.Do(func() {
		c.cancel()
		c.mu.Lock()
		conn := c.conn
		c.mu.Unlock()
		if conn != nil {
			go conn.Close(websocket.StatusNormalClosure, "")
		}
		if notify {
			c.a.send(map[string]any{"t": "end", "ch": c.ch})
		}
	})
}

func (c *channel) run() {
	a := c.a
	u, ok := a.browsers.WSURL()
	if ok && !strings.HasPrefix(u, "ws://127.0.0.1:") { // cannot happen: built by devtoolsURL
		ok = false
	}
	if !ok {
		a.dropChannel(c)
		c.finish(false)
		a.send(map[string]any{"t": "opened", "ch": c.ch, "ok": false, "error": "browser not launched"})
		return
	}
	dctx, cancel := context.WithTimeout(c.ctx, 10*time.Second)
	conn, _, err := websocket.Dial(dctx, u, &websocket.DialOptions{HTTPClient: localClient})
	cancel()
	if err != nil {
		a.dropChannel(c)
		c.finish(false)
		a.send(map[string]any{"t": "opened", "ch": c.ch, "ok": false, "error": "cannot reach the browser"})
		return
	}
	conn.SetReadLimit(maxFrame)
	c.mu.Lock()
	c.conn = conn
	c.mu.Unlock()
	if c.ctx.Err() != nil { // ended while dialing
		conn.CloseNow()
		return
	}
	a.send(map[string]any{"t": "opened", "ch": c.ch, "ok": true})

	go safely(a.logf, "channel-writer", func() {
		for {
			select {
			case <-c.ctx.Done():
				return
			case d := <-c.in:
				wctx, cancel := context.WithTimeout(c.ctx, writeWait)
				err := conn.Write(wctx, websocket.MessageText, []byte(d))
				cancel()
				if err != nil {
					if a.dropChannel(c) {
						c.finish(true)
					}
					return
				}
			}
		}
	})
	for {
		typ, data, err := conn.Read(c.ctx)
		if err != nil {
			if a.dropChannel(c) {
				c.finish(true)
			}
			return
		}
		if typ != websocket.MessageText {
			continue
		}
		if err := a.send(map[string]any{"t": "data", "ch": c.ch, "d": string(data)}); err != nil {
			a.logf("channel %s: relay failed: %v", c.key, err)
			if a.dropChannel(c) {
				c.finish(true)
			}
			return
		}
	}
}
