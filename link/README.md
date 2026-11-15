# Harness Link (desktop)

Harness Link (`HarnessLink.exe` on Windows, `harness-link` on macOS / Linux) lets Claude sessions on a Harness
Maxxing server see and use this computer: screenshots, mouse, keyboard, opening an installed app. It keeps one
outbound TLS websocket to the server; nothing listens on the network. It never runs a shell command, reads files
for the server or opens URLs: see the boundary in [PROTOCOL.md](PROTOCOL.md), the wire contract (shared with the
Android app).

The server appends a pairing trailer to the generic binary, so the downloaded copy pairs by itself on first run,
installs itself (copy + start at login), then reconnects forever (backoff 1 s to 60 s). Removing the device in
Harness (401/403 or `unpair`) deletes the pairing and stops the app.

```
harness-link                 pair (trailer) or run with the saved pairing
harness-link pair SERVER CODE   pair by hand, then run
harness-link status | uninstall | version
```

## What works where
| | screenshots | mouse / keyboard | apps |
|---|---|---|---|
| Linux X11 | X11 `GetImage` (pure Go, `jezek/xgb`) | XTEST; characters missing from the layout are typed through a spare keycode | `.desktop` files |
| Linux Wayland | not yet (hello `note`) | not yet | `.desktop` files |
| Windows 10/11 | GDI `BitBlt`, primary monitor, per-monitor DPI aware | `SendInput` (Unicode text) | Start Menu shortcuts |
| macOS 10.15+ | `screencapture -x -m` | CoreGraphics events (`purego`, no cgo), shortcuts follow the keyboard layout | `.app` bundles, `open -a` |

macOS asks for two permissions, for the binary itself when it runs at login (for the Terminal when started from
it): **Accessibility** (input) and **Screen Recording** (without it screenshots only show the desktop background).
The first time one is missing the app registers itself and opens the right System Settings pane, once; the hello
`note` tells the user until it is on. Screen Recording takes effect after a restart of the app.

## Build

```sh
./build.sh                # VERSION=0.1.0 by default; needs Go >= 1.26, network for go-winres the first time
```

Produces `dist/HarnessLink-windows-{amd64,arm64}.exe`, `dist/harness-link-{darwin,linux}-{amd64,arm64}` and
`dist/SHA256SUMS` (CGO off, `-trimpath`, empty build id: rebuilding gives the same hashes). Windows binaries are GUI
apps (`-H windowsgui`, manifest per-monitor DPI aware): no console window; messages are shown in message boxes,
and the CLI commands print to the console they are started from. The macOS arm64 binaries carry Go's ad hoc
signature; the server's trailer is appended after it (the kernel only checks the mapped pages).

## Tests

```sh
go test ./...                               # unit + protocol against an in-process fake server and fake screen
go test -tags xvfb -run X11 -v              # real X11: starts Xvfb :77 + xterm (apt install xvfb xterm)
./build.sh && go test -tags idle -run Idle -v   # idle CPU / RSS of the Linux binary (60 s)
```

## Try it against a server

```sh
./build.sh
go run ./tools/stamp dist/harness-link-linux-amd64 /tmp/harness-link https://ui.example.com AB12CD34
HARNESS_LINK_CONFIG_DIR=/tmp/hl HARNESS_LINK_NO_AUTOSTART=1 /tmp/harness-link
# or, without a trailer:
HARNESS_LINK_CONFIG_DIR=/tmp/hl HARNESS_LINK_NO_AUTOSTART=1 dist/harness-link-linux-amd64 pair https://ui.example.com AB12CD34
```

The code comes from Settings -> Devices -> Add a device. On Linux, run it inside the graphical session
(`DISPLAY` set), or against a virtual one: `Xvfb :77 -screen 0 1280x800x24 & DISPLAY=:77 ...`.
