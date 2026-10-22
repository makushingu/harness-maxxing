package main

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func touchExe(t *testing.T, p string) {
	t.Helper()
	os.MkdirAll(filepath.Dir(p), 0o755)
	if err := os.WriteFile(p, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatal(err)
	}
}

func TestBrowserDetectionWindows(t *testing.T) {
	root := t.TempDir()
	vars := map[string]string{
		"ProgramFiles":      filepath.Join(root, "PF"),
		"ProgramFiles(x86)": filepath.Join(root, "PF86"),
		"LOCALAPPDATA":      filepath.Join(root, "Local"),
	}
	env := searchEnv{goos: "windows", getenv: func(k string) string { return vars[k] }}
	touchExe(t, filepath.Join(root, "PF86", "Microsoft", "Edge", "Application", "msedge.exe"))
	touchExe(t, filepath.Join(root, "Local", "BraveSoftware", "Brave-Browser", "Application", "brave.exe"))
	touchExe(t, filepath.Join(root, "Local", "Programs", "Opera", "launcher.exe"))
	touchExe(t, filepath.Join(root, "PF", "Google", "Chrome", "Application", "chrome.exe"))
	os.MkdirAll(filepath.Join(root, "PF", "Vivaldi", "Application", "vivaldi.exe"), 0o755) // a dir, not a file
	got := detectBrowsersIn(env)
	if want := []string{"brave", "chrome", "edge", "opera"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
	p, err := findBrowserIn(env, "brave")
	if err != nil || p != filepath.Join(root, "Local", "BraveSoftware", "Brave-Browser", "Application", "brave.exe") {
		t.Fatalf("brave: %s %v", p, err)
	}
	if _, err := findBrowserIn(env, "vivaldi"); err == nil {
		t.Fatal("vivaldi dir accepted")
	}
	if _, err := findBrowserIn(env, "notepad"); err == nil {
		t.Fatal("unknown id accepted")
	}
}

func TestBrowserDetectionMac(t *testing.T) {
	root, home := t.TempDir(), t.TempDir()
	env := searchEnv{goos: "darwin", getenv: func(string) string { return "" }, home: home, sysRoot: root}
	touchExe(t, filepath.Join(root, "Applications", "Google Chrome.app", "Contents", "MacOS", "Google Chrome"))
	touchExe(t, filepath.Join(home, "Applications", "Vivaldi.app", "Contents", "MacOS", "Vivaldi"))
	if got := detectBrowsersIn(env); !reflect.DeepEqual(got, []string{"chrome", "vivaldi"}) {
		t.Fatalf("got %v", got)
	}
}

func TestBrowserDetectionLinux(t *testing.T) {
	root, bin := t.TempDir(), t.TempDir()
	env := searchEnv{goos: "linux", getenv: func(k string) string {
		if k == "PATH" {
			return "relative/dir:" + bin
		}
		return ""
	}, sysRoot: root}
	touchExe(t, filepath.Join(root, "opt", "brave.com", "brave", "brave"))
	touchExe(t, filepath.Join(bin, "chromium-browser"))
	touchExe(t, filepath.Join(bin, "google-chrome-stable"))
	os.WriteFile(filepath.Join(bin, "microsoft-edge"), []byte("x"), 0o644) // not executable
	if got := detectBrowsersIn(env); !reflect.DeepEqual(got, []string{"brave", "chrome", "chromium"}) {
		t.Fatalf("got %v", got)
	}
}

func TestDevtoolsURL(t *testing.T) {
	u, err := devtoolsURL("ws://localhost:9222/devtools/browser/abc-123", 4242)
	if err != nil || u != "ws://127.0.0.1:4242/devtools/browser/abc-123" {
		t.Fatalf("%s %v", u, err)
	}
	for _, bad := range []string{"ws://evil.com/x", "ws://127.0.0.1:1/devtools/page/1", "ws://h/devtools/browser/../../x", ""} {
		if _, err := devtoolsURL(bad, 1); err == nil {
			t.Errorf("accepted %q", bad)
		}
	}
}
