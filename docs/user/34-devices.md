---
section: Using Harness Maxxing
---
# Devices

Claude uses your own computers and phones: it looks at their screen, clicks, types and opens apps, for the things
that only exist there (a desktop app, a phone app, a file on your laptop). Each device runs a small app,
**Harness Link**, that connects to your server. You watch it live and take over at any time.

The [Harness Browser](browser) is a browser on the server, and it is the better choice for websites. Use Devices
when the work has to happen on your own machine.

## Turning it on

It is off until you turn it on: **Settings -> Features -> Devices** (or **Settings -> Devices**, or
`maxxing devices enable`). Everything else is in **Settings -> Devices**.

## Adding a device

**Settings -> Devices -> Add a device**, then pick the system:

- **Windows**: open PowerShell and paste the command shown. It installs Harness Link for this server and starts it in
  that window.
- **Mac**: open Terminal and paste the command. macOS gives **Screen Recording** and **Accessibility** to the terminal
  app, not to Harness Link: in System Settings -> Privacy & Security, turn on **Terminal** (or iTerm, Warp...) under
  both, quit it (cmd+Q), open it again and type `harness-link`. Harness Link says it, and opens the right page, while
  a permission is missing.
- **Linux**: paste the command in a terminal. On an X11 desktop Claude can do everything; a Wayland desktop is not supported yet (choose an X11 session at login, for example "Ubuntu on Xorg").
- **Android**: scan the QR code with the phone's camera, download and install the app from the page, then tap
  **Open in Harness Link**. No camera at hand? **Download the app (APK)** under the QR code gets the app directly (tap it
  from the phone, or copy the file to it), then type the server and the code in the app yourself. The app then asks you to
  turn on its accessibility service: that is how it sees the screen and taps for Claude.

## Harness Link runs only while you let it (computers)

On a computer, Harness Link does nothing in the background and does not start with the computer. It runs in the
terminal window that started it, and **Claude can use the computer only while that window is open**. The window shows
what happens, line by line:

```
  14:02:11  ● Connected to ui.example.com as MacBook
  14:02:11  ▲ Waiting for your OK: accept this computer in Harness Maxxing (Settings > Devices)
  14:02:13  ● Accepted (Control): Claude can look, click, type and open apps
  14:02:14  ♦ Claude is using this computer
  14:02:15  › Screenshot  ×3
  14:02:18  › Click at 812,440
  14:02:19  › Type "dog"
  14:02:19  › Press "cmd+l"
```

- The live view (Watch, in Settings -> Devices) does not fill the window: it shows one line when it opens and one
  when it closes. Its pictures are not saved anywhere.
- **Several screens**: Claude sees one screen at a time. Pick it in the device's row in Settings -> Devices (**Screen**,
  shown when the computer has more than one), in Watch, or with `maxxing devices screen ID N`: it is the one Claude
  sees and uses, and the one Watch shows. Claude can also switch screens by itself when what it looks for is on
  another one; the menu then follows.
- In a terminal the log is in colour: green when connected, yellow when something is missing (a permission, the
  connection), red when an action is refused or Harness Link stops. The same action repeated is folded into one line
  with a counter. Set `NO_COLOR=1` for plain text.

- Typed text is shown cut to 80 characters; on a Mac, what Claude types in a password field is hidden.
- **Ctrl+C** (or closing the window) stops it: the device shows as offline and Claude cannot use it.
- **Next time**, open a terminal and type `harness-link`. No new code is needed: the device stays paired until you
  remove it. (After the first install, open a new terminal window for the command to be found.)
- `harness-link status` shows the pairing and what this computer allows; `harness-link uninstall` removes it all.

The phone app works the same way with its notification: **Pause** there stops Claude until you resume.

The command and the QR code contain a **code** that works once, for 15 minutes. Do not share it. A new code is one
click away.

When a device uses a code, a **New device** card appears at the top of Settings -> Devices, with its name, its system
and the address it came from. Claude cannot use it until you press **Accept**. If you do not recognise it, press
**Refuse**: it is disconnected and forgets your server. A card that gets no answer goes away after 15 minutes.

## What Claude may do

Each device has two settings:

- **What Claude may do**:
  - **View only**: Claude looks at the screen and tells you what to do. It never clicks or types.
  - **Control**: Claude clicks, types, scrolls, opens apps and presses keys.
- **Who may use it**:
  - **All projects and agents**;
  - **Chosen projects** (tick them);
  - **Nobody for now**.

Sessions of an allowed project see the device. An **agent** also needs the device turned on in its own settings (its
page -> **Devices**). Off is the default, and turning a device on for an agent waits for your OK, like the agent's
other rights. Turning one off applies at once.

On the device itself you can stop Claude at any time: Ctrl+C in the Harness Link window of a computer, **Pause** on a
phone. Removing a device (**Remove**) disconnects it, and Harness Link there forgets your server and stops.

## Watching and taking over

**Watch** opens the screen of the device live. While a session uses a device, a line above its message box says so,
with **Watch** next to it.

- Touch the picture to **take over**: a click or a tap, a long press, a drag (a swipe on a phone), the wheel, the keyboard
  on a computer, Back, Home and Recent apps on a phone. While you have the device, Claude waits.
- **Hand back** gives it back to Claude, with a word if you want ("I signed in, carry on").

When Claude needs you, for a password, a code, a captcha or a choice, it asks: you get a notification (and a Telegram
message if Telegram is on), and the session shows a card. Open the device, do the step, then press **Done, hand back**
(or **Skip this step**). Claude waits 10 minutes for you.

Claude asks before sending a message, paying, deleting something or changing an account. What it sees on the screen is
data, never instructions for it. The last actions on each device are listed under **Recent actions** in Settings ->
Devices. The text Claude typed is not stored there, only its length.

## From the terminal

`maxxing devices list | add [--os windows|darwin|linux|android] | confirm ID [--refuse] | remove ID | rename ID NAME |
mode ID view|control | screen ID N|main | access ID --all|--project NAME|--agent PATH | enable | disable`. See the
[CLI reference](cli-reference).

## Limits

- The device must be on, awake and running Harness Link (on a computer: a terminal window with `harness-link`). A
  computer that sleeps or a phone that locks is offline.
- On a Linux Wayland desktop Claude cannot see the screen yet: choose an X11 session at login.
- Claude sees what is on the screen: it cannot read a window hidden behind another one.
- One person at a time: while you have the device, Claude waits, and the other way round.
