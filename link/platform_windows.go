//go:build windows

package main

import (
	"os"
	"sync"

	"golang.org/x/sys/windows"
)

const (
	mbIconError       = 0x10
	mbIconInformation = 0x40
	mbSetForeground   = 0x10000
	mbTopmost         = 0x40000
)

func lockInstance(path string) (func(), error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	ol := new(windows.Overlapped)
	if err := windows.LockFileEx(windows.Handle(f.Fd()),
		windows.LOCKFILE_EXCLUSIVE_LOCK|windows.LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, ol); err != nil {
		f.Close()
		return nil, err
	}
	return func() { f.Close() }, nil
}

func messageBox(text string, flags uint32) {
	t, _ := windows.UTF16PtrFromString(text)
	c, _ := windows.UTF16PtrFromString("Harness PC")
	windows.MessageBox(0, t, c, flags|mbSetForeground|mbTopmost)
}

var (
	consoleOnce sync.Once
	consoleOK   bool
)

// attachConsole reuses the console of the parent (cmd.exe / PowerShell) for CLI flags:
// the binary is built as a GUI app, so it has no console of its own.
func attachConsole() bool {
	consoleOnce.Do(func() {
		proc := windows.NewLazySystemDLL("kernel32.dll").NewProc("AttachConsole")
		const attachParent = ^uintptr(0) // ATTACH_PARENT_PROCESS
		if r, _, _ := proc.Call(attachParent); r == 0 {
			return
		}
		f, err := os.OpenFile("CONOUT$", os.O_WRONLY, 0)
		if err != nil {
			return
		}
		os.Stdout, os.Stderr, consoleOK = f, f, true
	})
	return consoleOK
}

func cliOutput(s string) {
	if attachConsole() {
		os.Stdout.WriteString("\r\n" + s)
		return
	}
	messageBox(s, mbIconInformation)
}

// notify shows an information box without blocking the agent.
func notify(s string) { go messageBox(s, mbIconInformation) }

// fatal shows the reason the agent stops (blocks until closed).
func fatal(s string) { messageBox(s, mbIconError) }
