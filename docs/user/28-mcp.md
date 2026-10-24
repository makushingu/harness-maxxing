---
section: Using Harness Maxxing
---
# MCP servers

An MCP server gives Claude the tools of a service: read your ads account, search a Notion workspace, query a
database... **Settings -> MCP** lists every MCP server Claude Code uses in your workspace, where each one applies,
and whether it works.

## Where a server applies

| Where | Meaning |
|---|---|
| **Every session** | available in all topics (a tool you use everywhere) |
| **a topic** (`acme / ads`) | only in the sessions of that topic - the usual choice: the ads account in the `ads` topic, not in the others |

Click a topic to open it. When a topic is renamed its servers follow it; a deleted topic leaves its servers in
**Error** (remove them).

## States

| State | What to do |
|---|---|
| **Connected** | nothing, Claude has the tools |
| **To connect** | the service needs a sign-in: click **Connect** (below) |
| **Error** | hover it for the reason (wrong address, program missing, key refused...) |
| **To approve** | a `.mcp.json` file found in a project folder that Claude Code does not trust yet |
| **Not checked** | click **Check** |

States are checked in the background when you open the page and with **Check** (a few seconds per topic).

## Add a server

Simplest: ask Claude in the topic that needs it - "connect the MCP of `<service>`, here is its address". Or
**Add a server**:

- **Name**: short, letters, digits, `-` (e.g. `google-ads`).
- **Where**: every session, or a topic.
- **Address (URL)** given by the service (often ending in `/mcp`), or **Local program**: the command that starts
  it (e.g. `npx -y @acme/mcp-server`).
- **Headers** (address) or **environment variables** (program), only when the service asks for a key. Never paste
  the key itself: store it in **Settings -> Keys** and write `${KEY_NAME}` (the key button inserts it). Keys used
  this way are given to sessions automatically. A value written in clear (a token, a password) shows a **token in
  clear** warning and is hidden as `•••` in the list, as are a password and the query values of an address
  (`?key=•••`); only `${KEY_NAME}` references and harmless headers such as `Content-Type` stay readable.

The server is available from the next message of a session.

## Connect (sign-in)

Many services (state **To connect**) use a sign-in instead of a key:

1. Click **Connect**, then **Open the sign-in page**.
2. Sign in at the service and accept.
3. The browser then shows "This site can't be reached" on `localhost`: that is expected. The service sends you
   back to an address that only exists on the Harness server; the connection code is in that address. Copy the
   whole address from the address bar (it contains `code=`).
4. Back in Harness, paste it (**Paste** button, or Ctrl+V) and click **Finish**.

Do it within a few minutes: the code expires (then click **Try again**). This works whatever the access to Harness
(domain or Tailscale): Claude Code, on the server, finishes the connection with the code you pasted.

The connection is kept for every session (Claude Code renews it on its own). Done once per server.

## Remove

**...** -> **Remove**. The keys of the vault stay.

## Browser of my PC

**Settings -> MCP -> Browser of my PC** lets Claude use a browser on **your own computer** (Windows, Mac or Linux):
open a site you are signed in to, fill a form, read a page, take a screenshot... It uses a **separate profile** of
your browser (Brave, Chrome, Edge, Vivaldi, Opera or Chromium): your usual tabs, passwords and history are never
touched. Sign in to the sites Claude needs once, in the window it opens. (The card appears once Harness PC can be
downloaded from your server.)

1. Choose your computer and your browser (Harness guesses them from the browser you are using), then **Get Harness PC**.
2. Download **Harness PC** (already linked to this server, valid 15 minutes) and open it - or paste the command shown
   in PowerShell / a terminal. On Windows, SmartScreen may say "Windows protected your PC": **More info** -> **Run
   anyway** (Harness PC is not signed by a publisher yet). It needs no administrator rights.
3. The card then asks **"`<your PC>` wants to connect"**, with the address it connected from: click **Yes, it is my PC**. Until then nothing reaches that
   computer - if you do not recognise the name (someone else used your download link), click **Refuse**: it is
   disconnected and forgets your server. Every session can then use the browser tools (`harness-pc`).

**Only while Claude uses it.** Harness PC waits in the background (no window, almost no CPU or memory) and opens the
browser window at Claude's first browser action; after **10 minutes** without one (Settings: 5 to 60 min) the
browser and its tools stop. **Stop now** closes it at once. When the PC is off, asleep or Harness PC is not running,
Claude is told "the PC is offline" and carries on.

**Start with the computer** (on by default) adds Harness PC to your session's startup (Windows: Run key, Mac: login
item, Linux: autostart file), without administrator rights. **Disconnect** stops it and removes it from startup on
the PC; **Erase the profile** deletes the cookies and sign-ins of Claude's profile; **Reinstall / other PC** pairs
again (one PC at a time). The last actions (tool, page) are listed on the card.

Security: Harness PC only connects out to your Harness (nothing listens on your network); the browser's control port
stays on `127.0.0.1` of the PC and web pages cannot reach it. Harness PC itself checks every command it relays, so
even a hijacked server could not use it to reach your files: only web pages (http, https) can be opened - no
`file:`, `chrome:` or settings pages, and Claude cannot open addresses of your PC or your home network (localhost,
192.168.x.x, your router, a NAS) -, downloads cannot be sent to another folder, no file of the PC can be given
to a page, and no permission or app can be installed. Claude cannot upload files from the PC or record its screen.
The list of recent actions keeps addresses without their query part (sign-in codes are not kept).

## Backup and new server

The memory backup keeps the list of servers (values that look like secrets blanked - tokens, passwords, `API_KEY`-like
names: use `${KEY_NAME}` for them so a restore works as is; plain settings such as `LOG_LEVEL=debug` are kept); a restore adds back the missing ones.
Sign-ins must be done again on a new server.

From a terminal: `maxxing mcp list|add|remove` (see [CLI reference](17-cli-reference.md)).
