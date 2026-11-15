# Harness Link for Android

A small Android app that lets the Claude sessions of a Harness Maxxing server see and use the phone:
screenshots, taps, swipes, typing into a text field, system keys, the accessibility tree, the list of apps and
opening one. It is the Android side of the device protocol described in [`../link/PROTOCOL.md`](../link/PROTOCOL.md)
(the desktop app lives in `../link/`).

- Package `com.harnessmaxxing.link`, Android 11 (API 30) or later, Kotlin, no Google services.
- Distributed as an APK outside the Play Store (the server serves it on its pairing page).

## What it can do, and what it cannot

The app only answers the requests of the protocol: `shot` (JPEG of the screen, optionally a crop), `input`
(`click`, `long_press`, `drag`, `scroll`, `type`, `key`), `tree` / `tap_node` / `set_text`, `apps` / `open`.
It has no shell, reads no files, opens no URLs and installs nothing: this is the boundary even against a
compromised server. It does nothing while the phone is locked or the screen is off (`locked`), cannot capture
windows that apps protect with `FLAG_SECURE` (banking apps, password screens: `protected` on Android 14+; older
versions return a black image), and refuses everything while the person has pressed **Pause** (`paused`).

## Permissions

| Permission | Why |
|---|---|
| Accessibility service (turned on by the person in the phone's settings) | screenshots (`takeScreenshot`, API 30), gestures (`dispatchGesture`), the element tree, text in fields, Back / Home / Recents. Without it the app stays connected and reports `caps: ["apps"]` with a `note` |
| `INTERNET` | pairing request and the websocket to the server |
| `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_SPECIAL_USE` | the service that keeps the link open, with its permanent notification and the Pause button |
| `POST_NOTIFICATIONS` (asked on Android 13+) | to show that notification |
| `RECEIVE_BOOT_COMPLETED` | reconnect after a restart of the phone, once paired |
| `<queries>` for `MAIN` / `LAUNCHER` | list the apps that have an icon (`apps`), and only those (no `QUERY_ALL_PACKAGES`) |

The foreground service type is **`specialUse`**: `dataSync` is limited to 6 hours a day since Android 15 and
`connectedDevice` needs Bluetooth / USB / NFC prerequisites. `specialUse` has no time limit and only needs a
justification (the `PROPERTY_SPECIAL_USE_FGS_SUBTYPE` in the manifest), which matters only for a Play Store
listing.

**Android 13+ and apps installed from a browser**: the accessibility switch is greyed out ("Restricted
setting") until the person opens *App info → ⋮ → Allow restricted settings*. The main screen explains it and
has a button to App info.

## Pairing and settings

- Pairing link `harnesslink://pair?s=<server>&c=<code>` (from the server's pairing page / QR code), or the server
  address and the code typed on the main screen. A link always asks for confirmation, showing the server's host.
- The server must be `https://`. Debug builds also accept `http://` to `10.0.2.2`, `localhost` and `127.0.0.1`
  (network security config of `src/debug`), for the emulator.
- `POST <server>/api/devices/pair` -> `{device_id, token}`, kept in private preferences (excluded from backups).
- 401 / 403 on the websocket (or an `unpair` frame) = the phone was removed: it forgets the server and stops.
  **Forget this server** on the phone does the same locally, without telling the server.
- The device name (default: maker + model) can be changed on the main screen; a new `hello` carries it.

## Behaviour details (Android side of the protocol)

- Coordinates are in the space of the capture (`sw` x `sh`, else the last screenshot), scaled to the real screen.
- `click` = tap (`button: right` = long press, `double` = two taps); `long_press` default 600 ms; `drag` default
  300 ms; `move` = `unsupported` (no pointer).
- `scroll`: wheel notches like on a computer (`dy > 0` = see further down), one notch = a tenth of the screen,
  done as swipes of at most half a screen that stop without fling.
- `type`: inserted at the cursor of the focused field (replacing the selection; at the end when the field gives no
  cursor), with `ACTION_SET_TEXT`, so it does not depend on the keyboard. `\n` = a new line in a multi-line field,
  else the keyboard action (send / search / go). Password fields are replaced whole (their text cannot be read).
- `key`: `back`, `home` (home screen), `recents`, `notifications`, `quick_settings`, `enter` (keyboard action),
  `backspace`, `delete`, `space`, `esc` (= back), one character, `ctrl+a` / `ctrl+c` / `ctrl+x` / `ctrl+v`.
  Other valid desktop keys -> `unsupported`; unknown names -> `bad_request`.
- `tree`: visible nodes of every window (status bar, app, keyboard), top window first, only those with text, a
  description or an action, at most 400 (`truncated: true` beyond). Each node: `id` (valid until the next `tree`),
  `role` (class short name), `text`, `desc`, `b` = `[x, y, w, h]` in capture space, `click`, `edit`, `focus`, and
  when relevant `scroll`, `checked`, `password`, `rid` (view id). The reply also has `app` (package in front).
- `tap_node` clicks the node (or its nearest clickable parent, else taps its centre); `set_text` replaces the text
  of an editable node. A node that disappeared -> `bad_request` ("ask for a new tree").
- `apps`: launcher apps `{id: package, name: label}`; `open` takes a package id or a name (ignoring case).
- Extra `hello` fields: `kind: "android"`, `model`, `sdk`, `paused`. The `hello` is sent again when it changes
  (accessibility switched, rotation, name, pause), checked every 30 s.
- Notification: "Connected to Harness" / "Claude is using this phone" (`state {busy: true, by: "claude"}`) /
  "Paused", with a **Pause** / **Resume** action that sends `{"t":"paused","on":bool}`.

## Build

Needs a JDK 17+ and the Android SDK (`ANDROID_HOME`, default `/opt/android-sdk`) with the platform and
build-tools of `app/build.gradle.kts` (Gradle downloads the rest).

```sh
./build.sh            # unit tests + release APK -> dist/harness-link.apk and dist/harness-link.apk.sha256
./build.sh --debug    # debug APK (http allowed to the emulator host)
./gradlew testDebugUnitTest
```

Release signing comes from the environment, never from a file in the repository:
`HARNESS_LINK_KEYSTORE_B64` (base64 of the keystore), `HARNESS_LINK_KEYSTORE_PASSWORD`, `HARNESS_LINK_KEY_ALIAS`,
`HARNESS_LINK_KEY_PASSWORD`. Without them the release APK is signed with the local debug key (fine for tests;
phones only accept updates signed with the same key, so published APKs must always use the release key).

## Install and try

1. Download the APK on the phone (Harness: Settings -> Devices -> Add a device -> Android) and install it
   (allow installs from the browser when asked).
2. Open the pairing link (or type the server and the code), confirm, then accept the phone in Harness.
3. Turn on the accessibility service (button on the main screen; "Allow restricted settings" first if Android asks).

Emulator: `adb reverse tcp:<port> tcp:<port>` and pair a debug build with `http://localhost:<port>`, or use
`http://10.0.2.2:<port>`. The accessibility service can be turned on from adb:
`adb shell settings put secure enabled_accessibility_services com.harnessmaxxing.link/com.harnessmaxxing.link.LinkAccessibilityService`.
