# Harness Link - protocol (v2)

Harness Link lets Claude sessions on a Harness Maxxing server see and use a device of the user: a computer
(Linux, macOS, Windows: this folder) or an Android phone (same protocol). The device opens **one outbound TLS
websocket** to the server; nothing listens on the network.

**The boundary.** The app only takes screenshots, moves / clicks the pointer, presses keys, types text, lists the
installed apps and opens one of them. It never runs a shell command, never reads or writes files for the server,
never opens a URL, never starts a program that is not in its own app list. This holds even against a compromised
server: there is simply no message for anything else.

## Pairing
Desktop: the server appends a trailer to the generic binary it serves:
`<json utf-8><uint32 big-endian len(json)>HMLINK01`, JSON `{"server": "https://ui.example.com", "code": "AB12CD34"}`.
The app reads its own executable's tail at start (`tools/stamp` does the same as the server, for tests). Also:
`harness-link pair https://ui.example.com AB12CD34`. Android: `harnesslink://pair?s=<server>&c=<code>` or typed.
`server` must be `https://`, except `http://127.0.0.1|localhost[:port]` (tests).

`POST {server}/api/devices/pair` JSON
`{"code", "name": host name, "os": "linux|darwin|windows|android", "arch", "version", "caps": [...]}`
-> 200 `{"device_id", "token"}` | 4xx `{"error", "message"}` (`bad_code`, `expired`; 4xx = final, network / 5xx
errors are retried 6 times).
The app saves `{"server", "device_id", "token", "paired_code"}` (desktop: `config.json`, mode 0600, in the config
dir) and never uses the code again. A trailer with another code or server than the saved one pairs again
(a new download = a new pairing).

## Channel
`GET {server}/api/devices/ws` upgraded to a websocket, header `Authorization: Bearer <token>`.
401/403 -> token revoked: delete the config, stop (desktop exit code 3, with a message).
Any other failure -> reconnect with backoff 1 s, 2 s, 4 s ... 60 s (+ up to 20 % jitter), forever (reset after
30 s connected). Websocket ping every 30 s. Frames are JSON text, at most 16 MB each way.
`id` (any JSON value) is chosen by the server and echoed in the reply.

### device -> server
- Right after connecting:
  `{"t":"hello","v":"0.1.0","os":"linux","arch":"amd64","name":"studio","kind":"desktop",
    "caps":["screen","input","apps"],"screen":{"w":2560,"h":1440,"scale":1},"note":"..."}`
  - desktop, optional: `"screens":[{"i":0,"name":"Display 1","w":1920,"h":1080,"main":true},...]` and
    `"display":0` (the one `screen` describes and requests use).
  - `caps`: subset of `screen`, `input`, `apps`, `tree` (Android only). Missing = requests of that kind fail.
  - `screen`: full size of a capture in **pixels** and the system scale (pixels per point: 2 on Retina,
    1.5 at 150 %). Absent when there is no usable screen.
  - `note` (optional): why something is missing, for the user ("Wayland session: ...", "Accessibility is off
    ..."). Show it in Harness.
  - **`hello` is sent again whenever it changes** (checked every 30 s: screen resized, a permission granted):
    the server treats a later hello as an update of the same device.
- Android only, unsolicited: `{"t":"paused","on":bool}`; while paused every request fails with `paused`.

### server -> device; reply `{"t":"ok","id",...}` or `{"t":"err","id","code","message"}`
Requests are run one at a time, in order (input never interleaves). At most 16 may wait; more -> `busy`.

- `{"t":"shot","id","max_w":1280,"quality":70}` ->
  `{"t":"ok","id","jpeg":"<base64>","w":1280,"h":720,"sw_screen":2560,"sh_screen":1440}`.
  The image is reduced to `max_w` pixels wide, aspect kept, never enlarged (`max_w` 0 or absent = full size);
  `quality` 20-95 (default 70). `w`,`h` = the JPEG; `sw_screen`,`sh_screen` = the full screen in pixels.
  Zoom: `"crop":{"x","y","w","h"}` with `sw`,`sh` (same space as input coordinates) -> only that part of the
  screen, cut from the full-size capture then reduced to `max_w`; outside the screen -> `bad_request`.
  Desktop: the screen chosen by `display` (the main one by default).
- `{"t":"input","id","a":<action>, ...}` -> `{"t":"ok","id"}`. Coordinates `x`,`y` (`x2`,`y2`) are in the
  space of a capture of size `sw` x `sh` (send back the `w`,`h` of the screenshot the coordinates come from);
  the device scales them to the real screen and clamps them. `sw`/`sh` absent = full-size pixels.
  - `click`: `x`,`y`, `button` `left` (default) | `right` | `middle`, `double` bool.
  - `long_press`: `x`,`y`, hold `ms` (default 600, at most 10000), `button`.
  - `move`: `x`,`y`.
  - `drag`: from `x`,`y` to `x2`,`y2` in `ms` (default 300, 50-10000), `button` held.
  - `scroll`: `dx`, `dy` in **wheel notches** (rounded, a non-zero value is at least 1, at most 100), `dy` > 0 =
    down, `dx` > 0 = right; `x`,`y` optional (pointer moved there first). Android: one notch = about a tenth of
    the screen.
  - `type`: `text` (UTF-8, at most 20000 bytes; `\n` = Enter, `\t` = Tab), typed as is, whatever the keyboard
    layout.
  - `key`: `keys` = a combo `"ctrl+s"`, `"cmd+space"`, `"alt+tab"`, `"shift+f10"`, `"enter"`, or several separated
    by spaces (`"ctrl+a delete"`, at most 32). Names (case-insensitive): modifiers `ctrl`, `shift`, `alt`
    (`option`), `cmd` (`command`, `win`, `super`, `meta`: Command on macOS, Windows / Super key elsewhere); keys
    `enter` (`return`), `tab`, `esc`, `backspace`, `delete`, `insert`, `home`, `end`, `pageup`, `pagedown`, `left`,
    `up`, `right`, `down`, `space`, `capslock`, `printscreen`, `menu`, `f1`-`f24`, or one character (`a`, `/`, `é`;
    `plus` or a trailing `++` for `+`). Modifiers first, then at most one key. Android also: `back`, `home`,
    `recents`.
- `{"t":"apps","id"}` -> `{"t":"ok","id","apps":[{"id","name"}]}` (sorted by name, at most 1000).
  Desktop: Linux `.desktop` files of the XDG folders (id = desktop file id), macOS `.app` bundles of the
  Applications folders (id = bundle name), Windows Start Menu shortcuts (id = path in the Start Menu without
  `.lnk`) + Notepad, Calculator, Paint, File Explorer.
- `{"t":"open","id","app":"<id or name>"}` -> `ok`: starts that app (exact id first, then id or name ignoring case);
  anything else -> `not_found`. Linux: its `Exec` line (field codes removed), detached; macOS: `open -a`;
  Windows: `ShellExecute` of the shortcut.
- `{"t":"tree","id"}` -> Android: `{"t":"ok","id","nodes":[{"id","role","text","desc","b":[x,y,w,h],"click",
  "edit","focus"}],"sw","sh"}`; `{"t":"tap_node","id","node"}`, `{"t":"set_text","id","node","text"}`.
  Desktop: `unsupported` in this version.
- `{"t":"state","busy":bool,"by":"claude"|"human"}` (no reply): Android shows it; desktop only logs it.
- `{"t":"display","i":n}` (no reply): use screen `n` of `hello.screens` (`-1`: the main one) for pictures and input;
  the app sends its hello again. Sent on connect when a screen was chosen, and when it changes.
- `{"t":"watch","on":bool}` (no reply): the live view opened / closed in Harness Maxxing. Its pictures are `shot`
  requests with `"live":true`: the desktop live log shows "Live view" once instead of one line per picture.
- `{"t":"access","ok":bool,"mode":"view"|"control"}` (no reply): sent on connect and whenever it changes. `ok:false`:
  waiting for the person's OK in Harness Maxxing; then `ok:true` once accepted, and again when the mode changes.
  The desktop live log says it ("Waiting for your OK", "Accepted (Control)", "Now View only").
- `{"t":"unpair"}` (no reply): delete the config, stop (exit code 0).
- Any other `t` with an `id` -> `unsupported`; without an `id` -> ignored.

### Error codes
| code | meaning |
|---|---|
| `bad_request` | missing / invalid field, unknown action, key or button |
| `unsupported` | not possible on this device (Wayland, no XTEST, `tree` on a computer, unknown request) |
| `permission` | an OS permission is missing (macOS Accessibility); see the hello `note` |
| `no_display` | no graphical session / screen |
| `protected` | the screen cannot be captured now (locked, secure desktop, Android FLAG_SECURE) |
| `locked` | Android: screen locked |
| `blocked` | Windows refused the input (locked screen, window of an administrator app) |
| `not_found` | `open`: no such app |
| `busy` | too many requests waiting |
| `paused` | Android: paused by the user |
| `failed` | anything else (message says what) |

## Files (desktop)
| What | Windows | macOS | Linux |
|---|---|---|---|
| config dir | `%APPDATA%\HarnessLink` | `~/Library/Application Support/HarnessLink` | `$XDG_CONFIG_HOME/harness-link` |
| installed copy (on the user PATH) | `%LOCALAPPDATA%\HarnessLink\harness-link.exe` | `~/.local/bin/harness-link` | `~/.local/bin/harness-link` |
| login entry of older versions (removed at start) | HKCU `...\CurrentVersion\Run` value `HarnessLink` | `~/Library/LaunchAgents/com.harnessmaxxing.link.plist` | `~/.config/autostart/harness-link.desktop` |

Config dir: `config.json` (0600), `harness-link.log` (1 MB, one rotation), `harness-link.lock` (single instance),
On each start the app copies itself to the installed-copy path (unless it runs from there) and removes the login entry
of older versions; it runs only in the foreground of its terminal. The install script puts the installed copy on the
PATH (`~/.zshrc` / `~/.bashrc` / `~/.bash_profile` / `~/.profile` line, user `Path` on Windows).
`harness-link uninstall` removes the config dir and the installed copy.
Environment for tests: `HARNESS_LINK_CONFIG_DIR`, `HARNESS_LINK_INSTALL_PATH`, `HARNESS_LINK_NO_INSTALL=1`.
