//go:build smoke && !windows

// Manual smoke test against a real Chromium (not part of `go test`):
//
//	HARNESS_PC_SMOKE_BROWSER=/path/to/chrome-headless-shell go test -tags smoke -run Smoke -v
//
// When running as root, a wrapper adds --no-sandbox (Chromium refuses root otherwise); the agent never adds it.
package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestSmokeRealBrowser(t *testing.T) {
	b := os.Getenv("HARNESS_PC_SMOKE_BROWSER")
	if b == "" {
		t.Skip("set HARNESS_PC_SMOKE_BROWSER")
	}
	exe := b
	if os.Geteuid() == 0 {
		exe = filepath.Join(t.TempDir(), "browser.sh")
		os.WriteFile(exe, []byte("#!/bin/sh\nexec '"+b+"' --no-sandbox \"$@\"\n"), 0o755)
	}
	t.Setenv("HARNESS_PC_BROWSER_PATH", exe)
	t.Setenv("HARNESS_PC_HEADLESS", "1")
	fs := newFakeServer(t)
	dir := t.TempDir()
	startAgent(t, dir, &Trailer{Server: fs.URL, Code: "GOOD", Browser: "chromium"})
	c := fs.next(t)
	c.expect(t, "hello")
	c.send(t, map[string]any{"t": "launch", "id": 1})
	if m := c.expect(t, "launched"); m["ok"] != true {
		t.Fatalf("launch: %v", m)
	}
	c.send(t, map[string]any{"t": "open", "ch": "s"})
	if m := c.expect(t, "opened"); m["ok"] != true {
		t.Fatalf("open: %v", m)
	}
	cdp := func(id int, method string, params map[string]any) map[string]any {
		f, _ := json.Marshal(map[string]any{"id": id, "method": method, "params": params})
		c.send(t, map[string]any{"t": "data", "ch": "s", "d": string(f)})
		for {
			m := c.expect(t, "data")
			var r map[string]any
			json.Unmarshal([]byte(m["d"].(string)), &r)
			if r["id"] == float64(id) {
				return r
			}
		}
	}
	v := cdp(1, "Browser.getVersion", nil)
	t.Logf("Browser.getVersion: %v", v["result"].(map[string]any)["product"])
	tg := cdp(2, "Target.createTarget", map[string]any{"url": "data:text/html,<title>hm-pc</title>"})
	if tg["result"] == nil {
		t.Fatalf("createTarget: %v", tg)
	}
	tl := cdp(3, "Target.getTargets", nil)
	if !strings.Contains(string(must(json.Marshal(tl))), "hm-pc") && !strings.Contains(string(must(json.Marshal(tl))), "data:text/html") {
		t.Fatalf("target not found: %v", tl)
	}
	c.send(t, map[string]any{"t": "close", "id": 2})
	if m := c.expect(t, "closed"); m["ok"] != true {
		t.Fatalf("close: %v", m)
	}
	out, _ := exec.Command("pgrep", "-f", "--", "--user-data-dir="+filepath.Join(dir, "profile-chromium")).Output()
	if len(strings.TrimSpace(string(out))) > 0 {
		t.Fatalf("browser processes left: %s", out)
	}
	t.Log("launch, CDP relay, close: OK; no process left")
}

func must(b []byte, _ error) []byte { return b }
