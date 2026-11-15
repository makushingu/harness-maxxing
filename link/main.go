// Harness PC: lets Claude sessions on a Harness Maxxing server drive an isolated browser on this computer.
// See PROTOCOL.md.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"syscall"
)

var version = "dev" // set with -ldflags "-X main.version=..."

func main() { os.Exit(realMain(os.Args[1:])) }

func realMain(args []string) int {
	fs := flag.NewFlagSet("harness-pc", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	uninstall := fs.Bool("uninstall", false, "remove autostart, config and the installed copy")
	status := fs.Bool("status", false, "print the saved configuration (without the token)")
	showVersion := fs.Bool("version", false, "print the version")
	if err := fs.Parse(args); err != nil {
		cliOutput("Usage: harness-pc [--status | --uninstall | --version]\n")
		return 2
	}
	if *showVersion {
		cliOutput("Harness PC " + version + " (" + runtime.GOOS + "/" + runtime.GOARCH + ")\n")
		return 0
	}
	dir, err := configDir()
	if err != nil {
		fatal("Cannot find the configuration folder: " + err.Error())
		return 1
	}
	if *status {
		cliOutput(statusText(dir))
		return 0
	}
	if *uninstall {
		return doUninstall(dir)
	}

	if err := ensureDir(dir); err != nil {
		fatal("Cannot create " + dir + ": " + err.Error())
		return 1
	}
	unlock, err := lockInstance(filepath.Join(dir, lockName))
	if err != nil {
		fatal("Harness PC is already running on this computer.")
		return 1
	}
	defer unlock()
	logf, closeLog := openLog(dir)
	defer closeLog()

	var tr *Trailer
	if exe, err := os.Executable(); err == nil {
		if tr, err = readTrailer(exe); err != nil {
			logf("trailer ignored: %v", err)
			tr = nil
		}
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	return runAgent(ctx, runOpts{dir: dir, trailer: tr, logf: logf, autostart: true})
}

type runOpts struct {
	dir       string
	trailer   *Trailer
	logf      func(string, ...any)
	autostart bool // install / remove autostart entries (off in tests)
}

func runAgent(ctx context.Context, o runOpts) int {
	logf := o.logf
	logf("Harness PC %s starting (%s/%s)", version, runtime.GOOS, runtime.GOARCH)
	cfg, err := loadConfig(o.dir)
	if err != nil {
		logf("saved config ignored: %v", err)
		cfg = nil
	}
	fresh := false
	if tr := o.trailer; tr != nil && (cfg == nil || cfg.PairedCode != tr.Code) {
		nc, err := pairWithRetry(ctx, tr, logf)
		switch {
		case err == nil:
			if err := saveConfig(o.dir, nc); err != nil {
				fatal("Cannot save the configuration: " + err.Error())
				return 1
			}
			cfg, fresh = nc, true
			logf("paired with %s (device %s)", nc.Server, nc.DeviceID)
		case cfg != nil:
			logf("new pairing failed (%v); keeping the saved pairing", err)
		default:
			fatal(pairFailText(err))
			return 1
		}
	}
	if cfg == nil {
		fatal("Harness PC is not paired. Download it from Harness Maxxing and run the downloaded copy: it pairs by itself.")
		return 2
	}
	if o.autostart {
		if cfg.Autostart {
			if err := ensureAutostart(o.dir); err != nil {
				logf("autostart: %v", err)
			}
		} else {
			_ = removeAutostart(o.dir)
		}
	}

	a := newAgent(cfg, o.dir, logf)
	if fresh {
		a.onFirst = func() {
			b := cfg.Browser
			if b == "" {
				if l := detectBrowsers(); len(l) > 0 {
					b = l[0]
				}
			}
			notify("Harness PC is linked. Confirm \"It is my PC\" in Harness Maxxing (Settings > MCP); Claude can then use " +
				browserName(b) + " (separate profile). You can close this window.")
		}
	}
	err = a.run(ctx)
	a.endAll(false)
	a.browsers.Close()
	switch {
	case errors.Is(err, errRevoked), errors.Is(err, errUnpaired):
		logf("%v: removing the pairing", err)
		_ = deleteConfig(o.dir)
		if o.autostart {
			_ = removeAutostart(o.dir)
		}
		if errors.Is(err, errRevoked) {
			fatal("Disconnected from Harness Maxxing: this computer was removed. Download Harness PC again to reconnect it.")
			return 3
		}
		return 0
	default:
		logf("stopped: %v", err)
		return 0
	}
}

func pairFailText(err error) string {
	var pe *pairError
	if errors.As(err, &pe) {
		switch pe.Code {
		case "bad_code", "expired":
			return "This Harness PC download was already used or has expired. Download it again from Harness Maxxing."
		}
		return "Pairing refused by Harness Maxxing: " + pe.Error()
	}
	return "Cannot reach Harness Maxxing to pair this computer: " + err.Error()
}

func statusText(dir string) string {
	var b strings.Builder
	fmt.Fprintf(&b, "Harness PC %s\nconfig dir: %s\n", version, dir)
	cfg, err := loadConfig(dir)
	switch {
	case err != nil:
		fmt.Fprintf(&b, "config: unreadable (%v)\n", err)
	case cfg == nil:
		b.WriteString("config: not paired\n")
	default:
		fmt.Fprintf(&b, "server: %s\ndevice_id: %s\nbrowser: %s\nautostart: %v\ntoken: (hidden)\n",
			cfg.Server, cfg.DeviceID, cfg.Browser, cfg.Autostart)
	}
	fmt.Fprintf(&b, "browsers found: %s\n", strings.Join(detectBrowsers(), ", "))
	return b.String()
}

func doUninstall(dir string) int {
	var problems []string
	if err := removeAutostart(dir); err != nil {
		problems = append(problems, "autostart: "+err.Error())
	}
	if err := deleteConfig(dir); err != nil {
		problems = append(problems, "config: "+err.Error())
	}
	if err := os.RemoveAll(dir); err != nil {
		problems = append(problems, "files: "+err.Error())
	}
	if len(problems) > 0 {
		cliOutput("Harness PC: pairing and autostart removed; some files are still in use (quit Harness PC and the browser, then retry):\n" +
			strings.Join(problems, "\n") + "\n")
		return 1
	}
	cliOutput("Harness PC removed (autostart, configuration, profiles and installed copy).\n")
	return 0
}

// ---- logging ----

type rotWriter struct {
	mu   sync.Mutex
	path string
	max  int64
	f    *os.File
	size int64
}

func (w *rotWriter) open() error {
	f, err := os.OpenFile(w.path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		return err
	}
	st, _ := f.Stat()
	w.f, w.size = f, 0
	if st != nil {
		w.size = st.Size()
	}
	return nil
}

func (w *rotWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.f == nil {
		return len(p), nil
	}
	if w.size+int64(len(p)) > w.max {
		w.f.Close()
		_ = os.Remove(w.path + ".1")
		_ = os.Rename(w.path, w.path+".1")
		if err := w.open(); err != nil {
			w.f = nil
			return len(p), nil
		}
	}
	n, err := w.f.Write(p)
	w.size += int64(n)
	return n, err
}

func (w *rotWriter) Close() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.f != nil {
		return w.f.Close()
	}
	return nil
}

func openLog(dir string) (func(string, ...any), func()) {
	w := &rotWriter{path: filepath.Join(dir, logName), max: 1 << 20}
	var out io.Writer = w
	if err := w.open(); err != nil {
		out = io.Discard
	}
	if runtime.GOOS != "windows" {
		out = io.MultiWriter(out, os.Stderr)
	}
	l := log.New(out, "", log.LstdFlags)
	return func(f string, a ...any) { l.Printf(f, a...) }, func() { w.Close() }
}

// safely runs fn and turns a panic into a log line, so one bad goroutine does not stop the agent.
func safely(logf func(string, ...any), name string, fn func()) {
	defer func() {
		if r := recover(); r != nil {
			buf := make([]byte, 4096)
			buf = buf[:runtime.Stack(buf, false)]
			logf("panic in %s: %v\n%s", name, r, buf)
		}
	}()
	fn()
}
