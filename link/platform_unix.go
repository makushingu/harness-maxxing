//go:build !windows

package main

import (
	"fmt"
	"os"
	"syscall"

	"golang.org/x/sys/unix"
)

// lockInstance takes an exclusive, non-blocking lock (released by the OS if the process dies).
func lockInstance(path string) (func(), error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		return nil, err
	}
	return func() { f.Close() }, nil
}

func cliOutput(s string) { fmt.Fprint(os.Stdout, s) }

// fatal reports the reason the agent stops.
func fatal(s string) { fmt.Fprintln(os.Stderr, "Harness Link: "+s) }

func exitPause() {}

// enableANSI reports whether the terminal understands colours and cursor moves (always, on Unix).
func enableANSI(*os.File) bool { return true }

// termWidth is the width of the terminal on stdout, 80 when unknown.
func termWidth() int {
	ws, err := unix.IoctlGetWinsize(int(os.Stdout.Fd()), unix.TIOCGWINSZ)
	if err != nil || ws.Col == 0 {
		return 80
	}
	return int(ws.Col)
}
