//go:build !windows

package main

import (
	"fmt"
	"os"
	"syscall"
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

// notify tells the user something (stdout on macOS / Linux).
func notify(s string) { fmt.Fprintln(os.Stdout, "Harness PC: "+s) }

// fatal reports the reason the agent stops.
func fatal(s string) { fmt.Fprintln(os.Stderr, "Harness PC: "+s) }
