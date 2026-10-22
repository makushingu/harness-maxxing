package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"
)

var browserIDs = []string{"brave", "chrome", "edge", "vivaldi", "opera", "chromium"}

var browserNames = map[string]string{
	"brave": "Brave", "chrome": "Google Chrome", "edge": "Microsoft Edge",
	"vivaldi": "Vivaldi", "opera": "Opera", "chromium": "Chromium",
}

func knownBrowser(id string) bool { _, ok := browserNames[id]; return ok }

func browserName(id string) string {
	if n, ok := browserNames[id]; ok {
		return n
	}
	return "your browser"
}

// searchEnv describes where browsers are looked for; tests replace it with a fake tree.
type searchEnv struct {
	goos    string
	getenv  func(string) string
	home    string
	sysRoot string // prefix for absolute system paths (/Applications, /opt, /usr); "" for real use
}

func realSearchEnv() searchEnv {
	home, _ := os.UserHomeDir()
	return searchEnv{goos: runtime.GOOS, getenv: os.Getenv, home: home}
}

var winPaths = map[string][][]string{
	"brave":    {{"BraveSoftware", "Brave-Browser", "Application", "brave.exe"}},
	"chrome":   {{"Google", "Chrome", "Application", "chrome.exe"}},
	"edge":     {{"Microsoft", "Edge", "Application", "msedge.exe"}},
	"vivaldi":  {{"Vivaldi", "Application", "vivaldi.exe"}},
	"opera":    {{"Programs", "Opera", "launcher.exe"}, {"Opera", "launcher.exe"}},
	"chromium": {{"Chromium", "Application", "chrome.exe"}},
}

var macApps = map[string]string{
	"brave": "Brave Browser", "chrome": "Google Chrome", "edge": "Microsoft Edge",
	"vivaldi": "Vivaldi", "opera": "Opera", "chromium": "Chromium",
}

var linuxPaths = map[string][]string{
	"brave":    {"/opt/brave.com/brave/brave"},
	"chrome":   {"/opt/google/chrome/chrome"},
	"edge":     {"/opt/microsoft/msedge/msedge"},
	"vivaldi":  {"/opt/vivaldi/vivaldi"},
	"opera":    {"/usr/lib/x86_64-linux-gnu/opera/opera", "/usr/lib/opera/opera"},
	"chromium": {"/usr/lib/chromium/chromium", "/usr/lib/chromium-browser/chromium-browser"},
}

var linuxNames = map[string][]string{
	"brave":    {"brave-browser", "brave-browser-stable", "brave"},
	"chrome":   {"google-chrome", "google-chrome-stable"},
	"edge":     {"microsoft-edge", "microsoft-edge-stable"},
	"vivaldi":  {"vivaldi", "vivaldi-stable"},
	"opera":    {"opera"},
	"chromium": {"chromium", "chromium-browser"},
}

// browserCandidates lists the executable paths tried for a browser id, in order.
func browserCandidates(env searchEnv, id string) []string {
	var out []string
	switch env.goos {
	case "windows":
		var roots []string
		for _, k := range []string{"ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA"} {
			if v := env.getenv(k); v != "" && !contains(roots, v) {
				roots = append(roots, v)
			}
		}
		for _, r := range roots {
			for _, rel := range winPaths[id] {
				out = append(out, filepath.Join(append([]string{r}, rel...)...))
			}
		}
	case "darwin":
		app, ok := macApps[id]
		if !ok {
			return nil
		}
		for _, r := range []string{filepath.Join(env.sysRoot, "/Applications"), filepath.Join(env.home, "Applications")} {
			out = append(out, filepath.Join(r, app+".app", "Contents", "MacOS", app))
		}
	default:
		for _, p := range linuxPaths[id] {
			out = append(out, filepath.Join(env.sysRoot, p))
		}
		for _, dir := range filepath.SplitList(env.getenv("PATH")) {
			if dir == "" || !filepath.IsAbs(dir) {
				continue // never resolve relative PATH entries
			}
			for _, n := range linuxNames[id] {
				out = append(out, filepath.Join(dir, n))
			}
		}
	}
	return out
}

func contains(l []string, s string) bool {
	for _, x := range l {
		if x == s {
			return true
		}
	}
	return false
}

func isExecutable(goos, p string) bool {
	st, err := os.Stat(p)
	if err != nil || st.IsDir() || !st.Mode().IsRegular() {
		return false
	}
	return goos == "windows" || st.Mode().Perm()&0o111 != 0
}

func findBrowserIn(env searchEnv, id string) (string, error) {
	if !knownBrowser(id) {
		return "", fmt.Errorf("unknown browser %q", id)
	}
	for _, c := range browserCandidates(env, id) {
		if isExecutable(env.goos, c) {
			return c, nil
		}
	}
	return "", fmt.Errorf("%s is not installed", browserName(id))
}

func detectBrowsersIn(env searchEnv) []string {
	out := []string{}
	for _, id := range browserIDs {
		if _, err := findBrowserIn(env, id); err == nil {
			out = append(out, id)
		}
	}
	return out
}

// findBrowser resolves the executable to start (HARNESS_PC_BROWSER_PATH wins).
func findBrowser(id string) (string, error) {
	if !knownBrowser(id) {
		return "", fmt.Errorf("unknown browser %q", id)
	}
	if p := os.Getenv("HARNESS_PC_BROWSER_PATH"); p != "" {
		abs, err := filepath.Abs(p)
		if err != nil || !isExecutable(runtime.GOOS, abs) {
			return "", errors.New("HARNESS_PC_BROWSER_PATH is not an executable file")
		}
		return abs, nil
	}
	return findBrowserIn(realSearchEnv(), id)
}

func detectBrowsers() []string {
	if p := os.Getenv("HARNESS_PC_BROWSER_PATH"); p != "" && isExecutable(runtime.GOOS, p) {
		return append([]string{}, browserIDs...)
	}
	return detectBrowsersIn(realSearchEnv())
}

func envHeadless() bool { return os.Getenv("HARNESS_PC_HEADLESS") == "1" }

// browserArgs builds the command line of the browser (protocol: launch).
func browserArgs(port int, profile string, headless bool) []string {
	a := []string{
		fmt.Sprintf("--remote-debugging-port=%d", port),
		"--remote-debugging-address=127.0.0.1",
		"--user-data-dir=" + profile,
		"--no-first-run",
		"--no-default-browser-check",
	}
	if headless {
		a = append(a, "--headless=new")
	}
	// one tab to work in: a headless browser (and some restored sessions) start with none
	return append(a, "about:blank")
}

var (
	launchTimeout = 20 * time.Second
	killGrace     = 5 * time.Second
)

type running struct {
	id      string
	proc    *proc
	port    int
	wsURL   string
	closing bool // guarded by browserManager.mu
}

// browserManager owns at most one browser process.
type browserManager struct {
	dir    string
	logf   func(string, ...any)
	onExit func(id string) // the browser exited without being asked to

	mu   sync.Mutex
	cur  *running
	last string // last browser id launched
}

func (m *browserManager) Running() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.cur != nil
}

// WSURL returns the DevTools websocket URL of the running browser.
func (m *browserManager) WSURL() (string, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.cur == nil || m.cur.wsURL == "" {
		return "", false
	}
	return m.cur.wsURL, true
}

func profileDir(dir, id string) string { return filepath.Join(dir, "profile-"+id) }

func freePort() (int, error) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return 0, err
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port, nil
}

// Launch starts the browser, or does nothing if it already runs.
func (m *browserManager) Launch(ctx context.Context, id string, headless bool) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.cur != nil && m.cur.id == id {
		return nil
	}
	if m.cur != nil {
		m.closeLocked()
	}
	path, err := findBrowser(id)
	if err != nil {
		return err
	}
	prof := profileDir(m.dir, id)
	if err := ensureDir(prof); err != nil {
		return fmt.Errorf("profile: %w", err)
	}
	port, err := freePort()
	if err != nil {
		return err
	}
	p, err := startBrowser(path, browserArgs(port, prof, headless))
	if err != nil {
		return fmt.Errorf("start %s: %w", browserName(id), err)
	}
	r := &running{id: id, proc: p, port: port}
	m.cur, m.last = r, id
	m.logf("browser %s started (pid %d, port %d, headless %v)", id, p.pid, port, headless)
	go safely(m.logf, "browser-wait", func() {
		<-p.done
		p.release()
		m.mu.Lock()
		self := !r.closing
		if m.cur == r {
			m.cur = nil
		}
		m.mu.Unlock()
		m.logf("browser %s exited (by itself: %v)", id, self)
		if self && m.onExit != nil {
			m.onExit(id)
		}
	})

	ws, err := waitDevTools(ctx, port, p.done)
	if err != nil {
		m.closeLocked()
		return err
	}
	r.wsURL = ws
	return nil
}

// waitDevTools polls /json/version (bounded by launchTimeout) and returns the browser websocket URL.
func waitDevTools(ctx context.Context, port int, exited <-chan struct{}) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, launchTimeout)
	defer cancel()
	client := &http.Client{
		Transport: &http.Transport{Proxy: nil, DisableKeepAlives: true},
		Timeout:   2 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return errors.New("redirect refused")
		},
	}
	u := fmt.Sprintf("http://127.0.0.1:%d/json/version", port)
	t := time.NewTicker(150 * time.Millisecond)
	defer t.Stop()
	for {
		if ws, err := fetchWS(ctx, client, u, port); err == nil {
			return ws, nil
		}
		select {
		case <-ctx.Done():
			return "", errors.New("the browser did not open its DevTools port within 20 s")
		case <-exited:
			return "", errors.New("the browser exited during start (is another copy using the same profile?)")
		case <-t.C:
		}
	}
}

func fetchWS(ctx context.Context, c *http.Client, u string, port int) (string, error) {
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	resp, err := c.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("status %d", resp.StatusCode)
	}
	var v struct {
		WS string `json:"webSocketDebuggerUrl"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 64<<10)).Decode(&v); err != nil {
		return "", err
	}
	return devtoolsURL(v.WS, port)
}

// devtoolsURL keeps only the path of webSocketDebuggerUrl and pins the host to 127.0.0.1:port.
func devtoolsURL(raw string, port int) (string, error) {
	pu, err := url.Parse(raw)
	if err != nil {
		return "", err
	}
	if !strings.HasPrefix(pu.Path, "/devtools/browser/") || strings.Contains(pu.Path, "..") {
		return "", errors.New("unexpected webSocketDebuggerUrl")
	}
	return (&url.URL{Scheme: "ws", Host: fmt.Sprintf("127.0.0.1:%d", port), Path: pu.Path}).String(), nil
}

func (m *browserManager) Close() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.closeLocked()
}

func (m *browserManager) closeLocked() {
	r := m.cur
	if r == nil {
		return
	}
	r.closing = true
	m.cur = nil
	r.proc.kill(killGrace)
	m.logf("browser %s closed", r.id)
}

// Wipe closes the browser then deletes its profile.
func (m *browserManager) Wipe(id string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if id == "" && m.cur != nil {
		id = m.cur.id
	}
	if id == "" {
		id = m.last
	}
	m.closeLocked()
	if !knownBrowser(id) {
		return nil
	}
	var err error
	for i := 0; i < 10; i++ { // Windows may hold files a little after the exit
		if err = os.RemoveAll(profileDir(m.dir, id)); err == nil {
			return nil
		}
		time.Sleep(300 * time.Millisecond)
	}
	return err
}
