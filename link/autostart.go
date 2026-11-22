package main

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

// installPath is where the app lives once installed (where the install script puts it too):
// Windows %LOCALAPPDATA%\HarnessLink\harness-link.exe, macOS / Linux ~/.local/bin/harness-link.
// HARNESS_LINK_INSTALL_PATH overrides it (tests).
func installPath() (string, error) {
	if p := os.Getenv("HARNESS_LINK_INSTALL_PATH"); p != "" {
		return filepath.Abs(p)
	}
	if runtime.GOOS == "windows" {
		base := os.Getenv("LOCALAPPDATA")
		if base == "" {
			return "", errors.New("LOCALAPPDATA is not set")
		}
		return filepath.Join(base, "HarnessLink", "harness-link.exe"), nil
	}
	h, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(h, ".local", "bin", "harness-link"), nil
}

func selfPath() (string, error) {
	p, err := os.Executable()
	if err != nil {
		return "", err
	}
	if r, err := filepath.EvalSymlinks(p); err == nil {
		p = r
	}
	return filepath.Abs(p)
}

func samePath(a, b string) bool {
	a, b = filepath.Clean(a), filepath.Clean(b)
	if runtime.GOOS == "windows" || runtime.GOOS == "darwin" {
		return strings.EqualFold(a, b)
	}
	return a == b
}

// ensureInstalled copies the running binary to installPath unless it is that copy, so `harness-link` works
// from a terminal next time. Nothing starts at login: Harness Link runs only while a terminal runs it.
func ensureInstalled() error {
	self, err := selfPath()
	if err != nil {
		return err
	}
	target, err := installPath()
	if err != nil {
		return err
	}
	if samePath(self, target) {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		return err
	}
	return copyExe(self, target)
}

func copyExe(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	tmp, err := os.CreateTemp(filepath.Dir(dst), ".exe-*")
	if err != nil {
		return err
	}
	name := tmp.Name()
	if _, err := io.Copy(tmp, in); err != nil {
		tmp.Close()
		os.Remove(name)
		return err
	}
	if err := tmp.Close(); err != nil {
		os.Remove(name)
		return err
	}
	_ = os.Chmod(name, 0o700)
	if err := os.Rename(name, dst); err != nil {
		os.Remove(name)
		return err
	}
	return nil
}

// removeFile deletes p; a file already gone is not an error.
func removeFile(p string) error {
	if err := os.Remove(p); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

// removeLegacyAutostart deletes the login entry older versions registered (LaunchAgent, HKCU Run,
// ~/.config/autostart) and, on Windows, the old HarnessLink.exe copy.
func removeLegacyAutostart() error {
	err := unregisterAutostart()
	if e := removeLegacyCopy(); e != nil && err == nil {
		err = e
	}
	return err
}

// removeInstalled removes the login entry of older versions and deletes the installed copy
// (Windows: not while it runs).
func removeInstalled() error {
	err := removeLegacyAutostart()
	target, e := installPath()
	if e != nil {
		return err
	}
	if self, e := selfPath(); e == nil && samePath(self, target) && runtime.GOOS == "windows" {
		return err // a running .exe cannot be deleted; RemoveAll of the dir reports it
	}
	if e := removeFile(target); e != nil && err == nil {
		err = e
	}
	return err
}
