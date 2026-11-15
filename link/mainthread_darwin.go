//go:build darwin

package main

import (
	"runtime"
	"sync/atomic"
)

// macOS keyboard-layout and permission calls must run on the main thread: the main goroutine stays on it
// and runs what runOnMain sends while the app works in other goroutines.

func init() { runtime.LockOSThread() }

var (
	mainQueue = make(chan func())
	mainLoop  atomic.Bool
)

func runMain(f func() int) int {
	mainLoop.Store(true)
	defer mainLoop.Store(false)
	done := make(chan int, 1)
	go func() { done <- f() }()
	for {
		select {
		case code := <-done:
			return code
		case fn := <-mainQueue:
			fn()
		}
	}
}

// runOnMain runs fn on the main thread and waits for it.
// Without the loop (tests), fn runs on the calling goroutine.
func runOnMain(fn func()) {
	if !mainLoop.Load() {
		fn()
		return
	}
	ok := make(chan struct{})
	mainQueue <- func() {
		defer close(ok)
		fn()
	}
	<-ok
}
