# Harness PC agent - protocol (v1)

The PC agent ("Harness PC", `HarnessPC.exe` / `harness-pc`) lets Claude sessions on a Harness Maxxing server drive an
**isolated** Chromium-based browser (Brave, Chrome, Edge, Vivaldi, Opera, Chromium) on the user's computer. It only
launches / closes that browser with its own profile and relays the browser's DevTools websocket to the server over
one outbound TLS websocket. Nothing listens on the network; the DevTools port is bound to 127.0.0.1.

## Embedded config (download = already paired)
The server appends a trailer to the generic binary: `<json utf-8><uint32 big-endian len(json)>HMPCCFG1`.
JSON: `{"server": "https://ui.example.com", "code": "AB12CD34", "browser": "brave", "autostart": true}`.
The agent reads its own executable's tail at start. No trailer + no saved config -> prints/shows usage and exits.
`server` must be `https://`, except `http://127.0.0.1|localhost[:port]` (tests).

## Pairing (once)
`POST {server}/api/pc/pair` JSON `{"code", "name": hostname, "os": "windows|darwin|linux", "arch", "browsers": [ids],
"version"}` -> 200 `{"device_id", "token"}` | 4xx `{"error", "message"}` (`bad_code`, `expired`).
The agent then saves `{"server", "device_id", "token", "browser", "autostart"}` to its config file (0600; Windows:
in %APPDATA%) and never uses the code again. A saved config wins over the trailer unless the trailer's code is new
(different from `paired_code` saved) -> pair again (re-download = re-pair).

## Control channel
`GET {server}/api/pc/ws` upgraded to a websocket, header `Authorization: Bearer <token>`; 401/403 -> token revoked:
stop retrying, delete the config, exit (Windows: message box "Disconnected from Harness Maxxing").
Reconnect on any other failure with backoff 1 s, 2 s, 4 s … capped at 60 s (+ jitter), forever. Websocket ping every
30 s; no other periodic work (idle CPU ~0).

All frames are JSON text. `id` = request id chosen by the server, echoed in the reply.

agent -> server, right after connecting:
`{"t":"hello","v":"<agent version>","os","arch","name","browsers":["brave","chrome",…],"running":bool}`

server -> agent | agent reply
- `{"t":"launch","id","browser","headless":false}` -> `{"t":"launched","id","ok":true}` | `{"ok":false,"error"}`.
  Already running -> ok at once. Starts the browser with `--remote-debugging-port=<free port>
  --remote-debugging-address=127.0.0.1 --user-data-dir=<config dir>/profile-<browser> --no-first-run
  --no-default-browser-check` (+ `--headless=new` if asked or HARNESS_PC_HEADLESS=1), waits up to 20 s for
  `http://127.0.0.1:<port>/json/version` and keeps its `webSocketDebuggerUrl` path.
- `{"t":"close","id"}` -> `{"t":"closed","id","ok":true}`: browser process tree killed (Windows `taskkill /T /F`,
  unix process group), channels ended.
- A new pairing waits for the user's confirmation in Harness: the server accepts the socket but relays nothing until
  then; refused (or not confirmed within 15 min) -> `{"t":"unpair"}`.
- `{"t":"wipe","id"}` -> `{"t":"wiped","id","ok"}`: close, then delete `profile-<browser>`.
- `{"t":"open","ch"}` -> `{"t":"opened","ch","ok"}`: dial the browser's websocket (the `webSocketDebuggerUrl` only);
  error if not launched.
- `{"t":"data","ch","d":"<text frame>"}` both directions: relay CDP frames verbatim.
- `{"t":"end","ch"}` both directions: close that channel.
- `{"t":"unpair"}` -> delete config, close browser, exit.
agent -> server, unsolicited: `{"t":"exited"}` when the browser exits by itself (user closed it).
Unknown `t` -> ignored (logged). The agent never executes anything else: no shell, no file access, no other URL.

DevTools filter (cdpfilter.go): every command from the server is checked before it reaches the browser - the agent
is the boundary even against a compromised server. Refused (answered with a DevTools error `-32000`): commands over
1 MB; download folders (`Browser.setDownloadBehavior`, `Page.setDownloadBehavior`), files given to pages
(`DOM.setFileInputFiles`, `Input.dispatchDragEvent` with `data.files`), permissions, `Browser.executeBrowserCommand`,
`Network.loadNetworkResource`, `Target.exposeDevToolsProtocol`, `Target.setRemoteLocations`, the Extensions, PWA,
Tethering, FileSystem domains; any `params.url` that is not http, https, data or about:blank (no `file:`, `chrome:`,
`view-source:`...).

## Files
config dir: Windows `%APPDATA%\HarnessPC`, macOS `~/Library/Application Support/HarnessPC`, Linux
`$XDG_CONFIG_HOME/harness-pc` (`~/.config/harness-pc`). `config.json`, `profile-<browser>/`, `harness-pc.log`
(1 MB, one rotation). Single instance: lock file in the config dir.
Autostart (if `autostart`): the agent copies itself to the config dir and registers it - Windows HKCU
`Software\Microsoft\Windows\CurrentVersion\Run` value `HarnessPC`; macOS `~/Library/LaunchAgents/com.harnessmaxxing.pc.plist`;
Linux `~/.config/autostart/harness-pc.desktop`. `--uninstall` removes autostart, config and copy.

## Browser ids and where they are looked for
brave, chrome, edge, vivaldi, opera, chromium (standard install paths per OS, + PATH on Linux). Env
`HARNESS_PC_BROWSER_PATH` overrides the executable (tests).
