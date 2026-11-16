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
	return filepath.Join(h, "Library", "LaunchAgents", "com.harnessmaxxing.link.plist"), nil
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

func removeLegacyCopy() error { return nil }
