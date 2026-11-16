//go:build windows

package main

import (
	"os"
	"unsafe"

	"golang.org/x/sys/windows"
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

func cliOutput(s string) { os.Stdout.WriteString(s) }

// fatal reports the reason the app stops.
func fatal(s string) { os.Stderr.WriteString("Harness Link: " + s + "\r\n") }

// exitPause keeps a console window the app opened itself (double-click in Explorer) until Enter is pressed,
// so its last lines can be read. In PowerShell or cmd the console belongs to the shell: nothing to wait for.
func exitPause() {
	proc := windows.NewLazySystemDLL("kernel32.dll").NewProc("GetConsoleProcessList")
	var ids [4]uint32
	n, _, _ := proc.Call(uintptr(unsafe.Pointer(&ids[0])), uintptr(len(ids)))
	if n != 1 {
		return
	}
	os.Stdout.WriteString("\r\nPress Enter to close this window.")
	var b [1]byte
	_, _ = os.Stdin.Read(b[:])
}

// enableANSI turns on the virtual terminal mode of the console (Windows 10 and later), which draws colours and
// moves the cursor; false on an older console, where the live log stays plain text.
func enableANSI(f *os.File) bool {
	h := windows.Handle(f.Fd())
	var mode uint32
	if err := windows.GetConsoleMode(h, &mode); err != nil {
		return false
	}
	if mode&windows.ENABLE_VIRTUAL_TERMINAL_PROCESSING != 0 {
		return true
	}
	return windows.SetConsoleMode(h, mode|windows.ENABLE_VIRTUAL_TERMINAL_PROCESSING) == nil
}

// termWidth is the width of the console window, 80 when unknown.
func termWidth() int {
	var info windows.ConsoleScreenBufferInfo
	if windows.GetConsoleScreenBufferInfo(windows.Handle(os.Stdout.Fd()), &info) != nil {
		return 80
	}
	if w := int(info.Window.Right-info.Window.Left) + 1; w > 0 {
		return w
	}
	return 80
}
