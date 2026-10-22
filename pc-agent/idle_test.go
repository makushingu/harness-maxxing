//go:build idle && linux

// Manual idle-cost measurement (not part of `go test`): runs dist/harness-pc-linux-amd64 against the fake
// server for HARNESS_PC_IDLE_SECONDS (default 60) and reports CPU time and RSS.
//
//	./build.sh && go test -tags idle -run Idle -v
package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestIdleCost(t *testing.T) {
	bin, _ := filepath.Abs("dist/harness-pc-linux-amd64")
	secs := 60
	if s, err := strconv.Atoi(os.Getenv("HARNESS_PC_IDLE_SECONDS")); err == nil {
		secs = s
	}
	fs := newFakeServer(t)
	dir := t.TempDir()
	saveConfig(dir, &Config{Server: fs.URL, DeviceID: "dev1", Token: "tok1", Browser: "chrome"})
	cmd := exec.Command(bin)
	cmd.Env = append(os.Environ(), "HARNESS_PC_CONFIG_DIR="+dir)
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { cmd.Process.Kill(); cmd.Wait() }()
	c := fs.next(t)
	c.expect(t, "hello")
	go func() { // answer pings (coder/websocket answers them inside Read)
		for {
			if _, _, err := c.c.Read(t.Context()); err != nil {
				return
			}
		}
	}()
	cpu0 := cpuTicks(t, cmd.Process.Pid)
	time.Sleep(time.Duration(secs) * time.Second)
	cpu1 := cpuTicks(t, cmd.Process.Pid)
	status, _ := os.ReadFile(fmt.Sprintf("/proc/%d/status", cmd.Process.Pid))
	var rss, threads string
	for _, l := range strings.Split(string(status), "\n") {
		if strings.HasPrefix(l, "VmRSS:") {
			rss = strings.TrimSpace(l[6:])
		}
		if strings.HasPrefix(l, "Threads:") {
			threads = strings.TrimSpace(l[8:])
		}
	}
	ps, _ := exec.Command("ps", "-o", "pid,%cpu,rss,cputime", "-p", strconv.Itoa(cmd.Process.Pid)).Output()
	t.Logf("idle %d s: CPU %d ms (%.3f%%), RSS %s, threads %s\nps:\n%s", secs, (cpu1-cpu0)*10,
		float64(cpu1-cpu0)*10/float64(secs*1000)*100, rss, threads, ps)
}

func cpuTicks(t *testing.T, pid int) int {
	b, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	if err != nil {
		t.Fatal(err)
	}
	f := strings.Fields(string(b)[strings.LastIndex(string(b), ")")+2:])
	u, _ := strconv.Atoi(f[11])
	s, _ := strconv.Atoi(f[12])
	return u + s // clock ticks (100 Hz)
}
