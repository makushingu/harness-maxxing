# Harness Link (desktop)

Harness Link (`harness-link`, `harness-link.exe` on Windows) lets Claude sessions on a Harness
Maxxing server see and use this computer: screenshots, mouse, keyboard, opening an installed app. It keeps one
outbound TLS websocket to the server; nothing listens on the network. It never runs a shell command, reads files
for the server or opens URLs: see the boundary in [PROTOCOL.md](PROTOCOL.md), the wire contract (shared with the
Android app).

The server appends a pairing trailer to the generic binary, so the downloaded copy pairs by itself on first run. It
runs **in the foreground of the terminal that started it** and nowhere else: nothing starts at login, nothing stays
in the background. While it runs it prints a live log (connection, who has the device, one line per action: screenshot,
click x,y, typed text cut to 80 characters (hidden on macOS while a password field has the focus: secure keyboard entry), keys, opened app, refusals with their cause) and reconnects
(backoff 1 s to 60 s); Ctrl+C or closing the window stops it. Older versions registered a login entry: every start
removes it. Removing the device in Harness (401/403 or `unpair`) deletes the pairing and stops the app.

```
harness-link                 pair (trailer) or run with the saved pairing, in the foreground (Ctrl+C stops)
harness-link pair SERVER CODE   pair by hand, then run
harness-link status | uninstall | version
```

## What works where
| | screenshots | mouse / keyboard | apps |
|---|---|---|---|
| Linux X11 | X11 `GetImage` (pure Go, `jezek/xgb`) | XTEST; characters missing from the layout are typed through a spare keycode | `.desktop` files |
| Linux Wayland | not yet (hello `note`) | not yet | `.desktop` files |
| Windows 10/11 | GDI `BitBlt`, the chosen monitor (`display`), per-monitor DPI aware | `SendInput` (Unicode text) | Start Menu shortcuts |
| macOS 10.15+ | `screencapture -x` (`-D n` for the chosen screen) | CoreGraphics events (`purego`, no cgo), shortcuts follow the keyboard layout | `.app` bundles, `open -a` |

macOS gives its two permissions to the *responsible* process, which is the terminal app (Terminal, iTerm, Warp...,
named from `TERM_PROGRAM`): **Accessibility** (input) and **Screen Recording** (without it `screencapture` writes
nothing, answered as a `permission` error). A bare binary never shows in those lists, hence the foreground-only
design: the permissions stay with the terminal across updates of the app. Each start with one missing opens the right
System Settings pane; the live log and the hello `note` say what to turn on, then to quit the terminal (cmd+Q),
reopen it and type `harness-link` (macOS applies Screen Recording to a new process only).

## Build

```sh
./build.sh                # VERSION=0.1.0 by default; needs Go >= 1.26, network for go-winres the first time
```

Produces `dist/harness-link-windows-{amd64,arm64}.exe`, `dist/harness-link-{darwin,linux}-{amd64,arm64}` and
`dist/SHA256SUMS` (CGO off, `-trimpath`, empty build id: rebuilding gives the same hashes). Windows binaries are
console apps (manifest per-monitor DPI aware): they run in the PowerShell / cmd window that starts them; a
double-click opens a console of its own, which waits for Enter before closing. The macOS arm64 binaries carry Go's ad hoc
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
HARNESS_LINK_CONFIG_DIR=/tmp/hl HARNESS_LINK_NO_INSTALL=1 /tmp/harness-link
# or, without a trailer:
HARNESS_LINK_CONFIG_DIR=/tmp/hl HARNESS_LINK_NO_INSTALL=1 dist/harness-link-linux-amd64 pair https://ui.example.com AB12CD34
```

The code comes from Settings -> Devices -> Add a device. On Linux, run it inside the graphical session
(`DISPLAY` set), or against a virtual one: `Xvfb :77 -screen 0 1280x800x24 & DISPLAY=:77 ...`.

## Publish a version (maintainers)

Servers download the apps from a GitHub release `link-v<version>` of this repository, as listed in
`server/maxxing/link.json` (`{version, url, files: {name: sha256}}`; a file is used only when its sha256 matches).

1. `VERSION=<version> ./build.sh` here, and `android/build.sh` with the release signing key in the environment.
2. Create the release `link-v<version>` with the 6 files of `dist/`, `harness-link.apk` and `SHA256SUMS`.
3. Put the version and the sha256 of each file in `server/maxxing/link.json`, then release Harness Maxxing as usual.
