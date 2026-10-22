//go:build !windows

package main

import (
	"os/exec"
	"syscall"
	"time"
)

// proc is a browser started in its own process group.
type proc struct {
	pid  int
	done chan struct{}
}

func startBrowser(path string, args []string) (*proc, error) {
	cmd := exec.Command(path, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	dieWithAgent(cmd.SysProcAttr)
	// stdin/stdout/stderr stay nil = /dev/null: the browser's own logs are not kept.
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	p := &proc{pid: cmd.Process.Pid, done: make(chan struct{})}
	go func() {
		_ = cmd.Wait()
		// The leader is gone: end whatever it left in its group (renderers, GPU process...).
		_ = syscall.Kill(-p.pid, syscall.SIGKILL)
		close(p.done)
	}()
	return p, nil
}

// kill ends the whole process group: SIGTERM, then SIGKILL after grace.
func (p *proc) kill(grace time.Duration) {
	_ = syscall.Kill(-p.pid, syscall.SIGTERM)
	select {
	case <-p.done:
		return
	case <-time.After(grace):
	}
	_ = syscall.Kill(-p.pid, syscall.SIGKILL)
	select {
	case <-p.done:
	case <-time.After(grace):
	}
}

func (p *proc) release() {}
