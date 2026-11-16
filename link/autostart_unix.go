//go:build !windows && !darwin

package main

import (
	"errors"
	"os"
	"path/filepath"
)

func desktopPath() (string, error) {
	base := os.Getenv("XDG_CONFIG_HOME")
	if base == "" {
		h, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		base = filepath.Join(h, ".config")
	}
	return filepath.Join(base, "autostart", "harness-link.desktop"), nil
}

func unregisterAutostart() error {
	p, err := desktopPath()
	if err != nil {
		return err
	}
	if err := os.Remove(p); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

func removeLegacyCopy() error { return nil }
