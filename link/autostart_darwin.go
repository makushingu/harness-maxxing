//go:build darwin

package main

import (
	"errors"
	"os"
	"path/filepath"
)

func plistPath() (string, error) {
	h, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(h, "Library", "LaunchAgents", "com.harnessmaxxing.pc.plist"), nil
}

// registerAutostart writes the LaunchAgent; launchd loads it at the next login (nothing is executed now).
func registerAutostart(exe string) error {
	p, err := plistPath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	return writeFileAtomic(p, []byte(launchAgentPlist(exe)), 0o644)
}

func unregisterAutostart() error {
	p, err := plistPath()
	if err != nil {
		return err
	}
	if err := os.Remove(p); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}
