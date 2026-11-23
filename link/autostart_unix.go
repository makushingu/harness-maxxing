//go:build !windows && !darwin

package main

import (
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
	return removeFile(p)
}

func removeLegacyCopy() error { return nil }
