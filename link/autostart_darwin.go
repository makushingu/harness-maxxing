//go:build darwin

package main

import (
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
	return removeFile(p)
}

func removeLegacyCopy() error { return nil }
