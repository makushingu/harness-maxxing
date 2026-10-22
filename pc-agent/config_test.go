package main

import (
	"encoding/binary"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func makeTrailer(t *testing.T, v any) []byte {
	t.Helper()
	j, _ := json.Marshal(v)
	b := append([]byte("MZ...binary..."), j...)
	b = binary.BigEndian.AppendUint32(b, uint32(len(j)))
	return append(b, trailerMagic...)
}

func TestTrailerParsing(t *testing.T) {
	good := makeTrailer(t, map[string]any{"server": "https://ui.example.com/", "code": "AB12CD34", "browser": "brave", "autostart": true})
	tr, err := parseTrailer(good)
	if err != nil || tr == nil {
		t.Fatalf("parse: %v %v", tr, err)
	}
	if tr.Server != "https://ui.example.com" || tr.Code != "AB12CD34" || tr.Browser != "brave" || !tr.Autostart {
		t.Fatalf("bad trailer %+v", tr)
	}
	// From a file, like the agent reads its own executable.
	p := filepath.Join(t.TempDir(), "bin")
	os.WriteFile(p, good, 0o700)
	if tr2, err := readTrailer(p); err != nil || tr2 == nil || *tr2 != *tr {
		t.Fatalf("readTrailer: %+v %v", tr2, err)
	}
	if tr, err := parseTrailer([]byte("plain binary without trailer")); tr != nil || err != nil {
		t.Fatalf("no trailer: %v %v", tr, err)
	}
	os.WriteFile(p, []byte("x"), 0o700)
	if tr, err := readTrailer(p); tr != nil || err != nil {
		t.Fatalf("tiny file: %v %v", tr, err)
	}
	bad := map[string][]byte{
		"http remote": makeTrailer(t, map[string]any{"server": "http://ui.example.com", "code": "X"}),
		"no code":     makeTrailer(t, map[string]any{"server": "https://ui.example.com"}),
		"bad browser": makeTrailer(t, map[string]any{"server": "https://a.b", "code": "X", "browser": "calc"}),
		"ftp":         makeTrailer(t, map[string]any{"server": "ftp://a.b", "code": "X"}),
		"userinfo":    makeTrailer(t, map[string]any{"server": "https://u:p@a.b", "code": "X"}),
		"length lies": append(binary.BigEndian.AppendUint32([]byte("{}"), 999), trailerMagic...),
		"length zero": append(binary.BigEndian.AppendUint32([]byte("{}"), 0), trailerMagic...),
		"bad json":    append(binary.BigEndian.AppendUint32([]byte("{x"), 2), trailerMagic...),
		"huge length": append(binary.BigEndian.AppendUint32(make([]byte, 10), 1<<30), trailerMagic...),
	}
	for name, b := range bad {
		if tr, err := parseTrailer(b); err == nil {
			t.Errorf("%s: accepted %+v", name, tr)
		}
	}
	for _, s := range []string{"http://127.0.0.1:8787", "http://localhost", "https://x.y/sub"} {
		if _, err := validateServer(s); err != nil {
			t.Errorf("%s refused: %v", s, err)
		}
	}
}

func TestConfigSaveLoadPerms(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "cfg")
	c := &Config{Server: "https://ui.example.com", DeviceID: "d1", Token: "secret", Browser: "chrome", Autostart: true, PairedCode: "AB"}
	if err := saveConfig(dir, c); err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" {
		st, _ := os.Stat(filepath.Join(dir, configName))
		if st.Mode().Perm() != 0o600 {
			t.Fatalf("config mode %v", st.Mode().Perm())
		}
		dst, _ := os.Stat(dir)
		if dst.Mode().Perm() != 0o700 {
			t.Fatalf("dir mode %v", dst.Mode().Perm())
		}
		// a loosened file is tightened back on load
		os.Chmod(filepath.Join(dir, configName), 0o644)
	}
	got, err := loadConfig(dir)
	if err != nil || got == nil || *got != *c {
		t.Fatalf("load: %+v %v", got, err)
	}
	if runtime.GOOS != "windows" {
		st, _ := os.Stat(filepath.Join(dir, configName))
		if st.Mode().Perm() != 0o600 {
			t.Fatalf("mode not fixed: %v", st.Mode().Perm())
		}
	}
	if s := statusText(dir); !strings.Contains(s, "token: (hidden)") || strings.Contains(s, "secret") {
		t.Fatalf("status leaks or misses token line: %s", s)
	}
	if err := deleteConfig(dir); err != nil {
		t.Fatal(err)
	}
	if got, err := loadConfig(dir); got != nil || err != nil {
		t.Fatalf("after delete: %v %v", got, err)
	}
}

func TestBackoff(t *testing.T) {
	want := []time.Duration{1, 2, 4, 8, 16, 32, 60, 60, 60}
	for n, w := range want {
		w *= time.Second
		for i := 0; i < 50; i++ {
			d := backoff(n)
			if d < w || d > w+w/5 {
				t.Fatalf("backoff(%d) = %v, want [%v, %v]", n, d, w, w+w/5)
			}
		}
	}
	if d := backoff(1000); d < 60*time.Second || d > 72*time.Second {
		t.Fatalf("backoff(1000) = %v", d)
	}
}

func TestLogRotation(t *testing.T) {
	dir := t.TempDir()
	w := &rotWriter{path: filepath.Join(dir, logName), max: 100}
	if err := w.open(); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 30; i++ {
		w.Write([]byte("0123456789\n"))
	}
	w.Close()
	a, _ := os.Stat(filepath.Join(dir, logName))
	b, err := os.Stat(filepath.Join(dir, logName+".1"))
	if err != nil || a.Size() > 100 || b.Size() > 100 {
		t.Fatalf("rotation: %v %v %v", a, b, err)
	}
}

func TestAutostartFiles(t *testing.T) {
	d := desktopEntry(`/home/a b/"x"$y/harness-pc`)
	if !strings.Contains(d, `Exec="/home/a b/\\"x\\"\\$y/harness-pc"`) {
		t.Fatalf("desktop entry: %s", d)
	}
	p := launchAgentPlist(`/Users/a&b/HarnessPC/harness-pc`)
	if !strings.Contains(p, "<string>/Users/a&amp;b/HarnessPC/harness-pc</string>") {
		t.Fatalf("plist: %s", p)
	}
}
