# Harness PC agent

Harness PC (`HarnessPC.exe` on Windows, `harness-pc` on macOS / Linux) lets Claude sessions on a Harness Maxxing
server drive a Chromium-based browser (Brave, Chrome, Edge, Vivaldi, Opera, Chromium) on the user's computer, in a
**separate profile**. It only starts / closes that browser and relays its DevTools websocket (bound to 127.0.0.1) to
the server over one outbound TLS websocket. Nothing listens on the network and nothing else is ever executed.
The wire contract is [PROTOCOL.md](PROTOCOL.md).

The server appends a pairing trailer to the generic binary, so a downloaded copy pairs by itself on first run, then
keeps a token in its config file and reconnects forever (backoff 1 s to 60 s). The token being revoked (401/403) or an
`unpair` from the server removes the pairing and stops the agent.

## Build

```sh
./build.sh                # VERSION=0.1.0 by default; needs Go >= 1.26
```

Produces `dist/HarnessPC-windows-{amd64,arm64}.exe`, `dist/harness-pc-{darwin,linux}-{amd64,arm64}` and
`dist/SHA256SUMS` (CGO off, `-trimpath`, empty build id: rebuilding gives the same hashes). Windows binaries are GUI
apps (`-H windowsgui`): no console window; messages are shown in message boxes.

## Tests

```sh
go test ./...                                                     # unit + integration (fake server, fake browser)
HARNESS_PC_SMOKE_BROWSER=/path/to/chrome go test -tags smoke -run Smoke -v   # real browser (manual)
./build.sh && go test -tags idle -run Idle -v                     # idle CPU / RSS of the Linux binary (60 s)
```

## Files

| What | Windows | macOS | Linux |
|---|---|---|---|
| config dir | `%APPDATA%\HarnessPC` | `~/Library/Application Support/HarnessPC` | `$XDG_CONFIG_HOME/harness-pc` (`~/.config/harness-pc`) |
| autostart | HKCU `...\CurrentVersion\Run` value `HarnessPC` | `~/Library/LaunchAgents/com.harnessmaxxing.pc.plist` | `~/.config/autostart/harness-pc.desktop` |

The config dir holds `config.json` (0600, contains the token), `profile-<browser>/`, `harness-pc.log` (1 MB, one
rotation), the single-instance lock and, with autostart, the installed copy of the agent.

Flags: `--status` (configuration without the token), `--version`, `--uninstall`. Environment (tests):
`HARNESS_PC_BROWSER_PATH` (browser executable), `HARNESS_PC_HEADLESS=1`, `HARNESS_PC_CONFIG_DIR`.

## Uninstall

Quit Harness PC (or remove the computer in Harness Maxxing, which stops it), then run `HarnessPC.exe --uninstall` /
`harness-pc --uninstall`: it removes the autostart entry, the configuration, the browser profiles and the installed
copy. Then delete the downloaded file.
