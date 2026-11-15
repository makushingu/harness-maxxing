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
// Windows %LOCALAPPDATA%\HarnessLink\HarnessLink.exe, macOS / Linux ~/.local/bin/harness-link.
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
		return filepath.Join(base, "HarnessLink", "HarnessLink.exe"), nil
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

// ensureAutostart copies the running binary to installPath (unless it is that copy)
// and registers the copy to start at login.
func ensureAutostart() error {
	self, err := selfPath()
	if err != nil {
		return err
	}
	target, err := installPath()
	if err != nil {
		return err
	}
	if !samePath(self, target) {
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		if err := copyExe(self, target); err != nil {
			return err
		}
	}
	return registerAutostart(target)
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

// removeAutostart unregisters the login entry and deletes the installed copy (Windows: not while it runs).
func removeAutostart() error {
	err := unregisterAutostart()
	target, e := installPath()
	if e != nil {
		return err
	}
	if self, e := selfPath(); e == nil && samePath(self, target) && runtime.GOOS == "windows" {
		return err // a running .exe cannot be deleted; RemoveAll of the dir reports it
	}
	if e := os.Remove(target); e != nil && !errors.Is(e, os.ErrNotExist) && err == nil {
		err = e
	}
	return err
}

// desktopEntry is the Linux ~/.config/autostart file.
func desktopEntry(exe string) string {
	r := strings.NewReplacer(`\`, `\\\\`, `"`, `\\"`, "`", "\\\\`", "$", `\\$`)
	return "[Desktop Entry]\nType=Application\nName=Harness Link\nComment=Lets Harness Maxxing see and use this computer\n" +
		"Exec=\"" + r.Replace(exe) + "\"\nTerminal=false\nNoDisplay=true\nX-GNOME-Autostart-enabled=true\n"
}

// launchAgentPlist is the macOS ~/Library/LaunchAgents file.
func launchAgentPlist(exe string) string {
	r := strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", `"`, "&quot;", "'", "&apos;")
	return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.harnessmaxxing.link</string>
  <key>ProgramArguments</key><array><string>` + r.Replace(exe) + `</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
  <key>ProcessType</key><string>Interactive</string>
</dict>
</plist>
`
}
