// Harness Link: lets Claude sessions on a Harness Maxxing server see and use this computer
// (screenshots, mouse, keyboard, opening apps). See PROTOCOL.md.
package main

import (
	"context"
	"errors"
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

const usage = `Usage: harness-link [command]
  (no command)          let Claude use this computer while this terminal window is open (Ctrl+C stops),
                        printing what it does; pairs first with the server written into this download
  pair SERVER CODE      pair with SERVER (https://...) using a one-time CODE from Harness, then run
  status                print the saved pairing (without the token) and what this computer allows
  uninstall             remove the pairing, the configuration and the installed copy
  version               print the version
`

func main() {
	code := runMain(func() int { return realMain(os.Args[1:]) })
	exitPause()
	os.Exit(code)
}

func realMain(args []string) int {
	cmd := ""
	if len(args) > 0 {
		cmd = strings.TrimLeft(args[0], "-")
	}
	var manual *Trailer
	switch cmd {
	case "":
	case "version":
		cliOutput("Harness Link " + version + " (" + runtime.GOOS + "/" + runtime.GOARCH + ")\n")
		return 0
	case "help", "h":
		cliOutput(usage)
		return 0
	case "pair":
		if len(args) != 3 {
			cliOutput(usage)
			return 2
		}
		srv, err := validateServer(args[1])
		if err != nil || strings.TrimSpace(args[2]) == "" {
			cliOutput("Harness Link: give an https:// server address and a pairing code.\n")
			return 2
		}
		manual = &Trailer{Server: srv, Code: strings.TrimSpace(args[2])}
	case "status", "uninstall":
	default:
		cliOutput(usage)
		return 2
	}
	dir, err := configDir()
	if err != nil {
		fatal("Cannot find the configuration folder: " + err.Error())
		return 1
	}
	switch cmd {
	case "status":
		cliOutput(statusText(dir))
		return 0
	case "uninstall":
		return doUninstall(dir)
	}

	if err := ensureDir(dir); err != nil {
		fatal("Cannot create " + dir + ": " + err.Error())
		return 1
	}
	unlock, err := lockInstance(filepath.Join(dir, lockName))
	if err != nil {
		fatal("Harness Link is already running in another window on this computer (or an older version started at login: quit it, or log out and back in).")
		return 1
	}
	defer unlock()
	logf, closeLog := openLog(dir)
	defer closeLog()

	tr := manual
	if tr == nil {
		if exe, err := os.Executable(); err == nil {
			if tr, err = readTrailer(exe); err != nil {
				logf("trailer ignored: %v", err)
				tr = nil
			}
		}
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	be := newBackend(dir, logf)
	defer be.Close()
	con := stdoutConsole(logf)
	con.header()
	code := runAgent(ctx, runOpts{dir: dir, trailer: tr, logf: logf, say: con.emit, be: be,
		install: os.Getenv("HARNESS_LINK_NO_INSTALL") != "1"})
	if ctx.Err() != nil {
		con.emit(lErr, "Stopped: Claude can no longer use this computer. Type harness-link to start again.")
	}
	return code
}

type runOpts struct {
	dir     string
	trailer *Trailer
	logf    func(string, ...any)
	say     func(lineKind, string) // live log (defaults to logf)
	be      backend
	install bool // copy the app to its install path, remove the login entry of older versions (off in tests)
}

func runAgent(ctx context.Context, o runOpts) int {
	logf := o.logf
	say := o.say
	if say == nil {
		say = logSay(logf)
	}
	logf("Harness Link %s starting (%s/%s)", version, runtime.GOOS, runtime.GOARCH)
	cfg, err := loadConfig(o.dir)
	if err != nil {
		logf("saved config ignored: %v", err)
		cfg = nil
	}
	if tr := o.trailer; tr != nil && (cfg == nil || cfg.PairedCode != tr.Code || cfg.Server != tr.Server) {
		nc, err := pairWithRetry(ctx, tr, o.be.Info().capsList(), logf)
		switch {
		case err == nil:
			if err := saveConfig(o.dir, nc); err != nil {
				fatal("Cannot save the configuration: " + err.Error())
				return 1
			}
			cfg = nc
			logf("paired with %s (device %s)", nc.Server, nc.DeviceID)
		case cfg != nil:
			logf("new pairing failed (%v); keeping the saved pairing", err)
		default:
			fatal(pairFailText(err))
			return 1
		}
	}
	if cfg == nil {
		fatal("Harness Link is not paired. In Harness Maxxing, open Settings > Devices > Add a device and run the command shown there.")
		return 2
	}
	if o.install {
		if err := removeLegacyAutostart(); err != nil {
			logf("old login entry: %v", err)
		}
		if err := ensureInstalled(); err != nil {
			logf("install: %v", err)
		}
	}

	logf("live log started")
	a := newAgent(cfg, o.be, logf)
	a.say = say
	err = a.run(ctx)
	switch {
	case errors.Is(err, errRevoked), errors.Is(err, errUnpaired):
		logf("%v: removing the pairing", err)
		_ = deleteConfig(o.dir)
		if errors.Is(err, errRevoked) {
			fatal("Disconnected from Harness Maxxing: this computer was removed. Add it again from Settings > Devices to reconnect it.")
			return 3
		}
		say(lErr, "Disconnected: this computer was removed from Harness Maxxing")
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
			return "This pairing code was already used or has expired. Add the device again from Harness Maxxing (Settings > Devices)."
		}
		return "Pairing refused by Harness Maxxing: " + pe.Error()
	}
	return "Cannot reach Harness Maxxing to pair this computer: " + err.Error()
}

func statusText(dir string) string {
	var b strings.Builder
	fmt.Fprintf(&b, "Harness Link %s (%s/%s)\nconfig dir: %s\n", version, runtime.GOOS, runtime.GOARCH, dir)
	cfg, err := loadConfig(dir)
	switch {
	case err != nil:
		fmt.Fprintf(&b, "pairing: unreadable (%v)\n", err)
	case cfg == nil:
		b.WriteString("pairing: not paired\n")
	default:
		fmt.Fprintf(&b, "server: %s\ndevice_id: %s\ntoken: (hidden)\n", cfg.Server, cfg.DeviceID)
	}
	if p, err := installPath(); err == nil {
		fmt.Fprintf(&b, "installed copy: %s\n", p)
	}
	be := newBackend(dir, func(string, ...any) {})
	defer be.Close()
	inf := be.Info()
	fmt.Fprintf(&b, "can: %s\n", strings.Join(inf.capsList(), ", "))
	if inf.Screen != nil {
		fmt.Fprintf(&b, "screen: %dx%d (scale %g)\n", inf.Screen.W, inf.Screen.H, inf.Screen.Scale)
	}
	if inf.Note != "" {
		fmt.Fprintf(&b, "note: %s\n", inf.Note)
	}
	return b.String()
}

func doUninstall(dir string) int {
	var problems []string
	if err := removeInstalled(); err != nil {
		problems = append(problems, "app: "+err.Error())
	}
	if err := deleteConfig(dir); err != nil {
		problems = append(problems, "config: "+err.Error())
	}
	if err := os.RemoveAll(dir); err != nil {
		problems = append(problems, "files: "+err.Error())
	}
	if len(problems) > 0 {
		cliOutput("Harness Link: pairing removed; some files are still in use (quit Harness Link, then retry):\n" +
			strings.Join(problems, "\n") + "\n")
		return 1
	}
	cliOutput("Harness Link removed (pairing, configuration and installed copy).\n")
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
