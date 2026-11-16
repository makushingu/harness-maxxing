//go:build windows

package main

import (
	"errors"
	"os"
	"path/filepath"

	"golang.org/x/sys/windows/registry"
)

const runKey = `Software\Microsoft\Windows\CurrentVersion\Run`

func unregisterAutostart() error {
	k, err := registry.OpenKey(registry.CURRENT_USER, runKey, registry.SET_VALUE)
	if err != nil {
		return nil
	}
	defer k.Close()
	if err := k.DeleteValue("HarnessLink"); err != nil && !errors.Is(err, registry.ErrNotExist) {
		return err
	}
	return nil
}

// removeLegacyCopy deletes HarnessLink.exe, the name older versions were installed under.
func removeLegacyCopy() error {
	base := os.Getenv("LOCALAPPDATA")
	if base == "" {
		return nil
	}
	old := filepath.Join(base, "HarnessLink", "HarnessLink.exe")
	if self, err := selfPath(); err == nil && samePath(self, old) {
		return nil
	}
	if err := os.Remove(old); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}
