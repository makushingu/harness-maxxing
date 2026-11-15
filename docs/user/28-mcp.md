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

## Load servers only when needed

Every server Claude Code loads costs tokens on **each** message (its tool names and instructions: a big service
such as an ads account adds a few thousand) and time at the start of each turn (the connection). **Settings -> MCP
-> Load MCP servers only when a session needs them** (off by default) gives each message only:

- the servers its topic already used (in the last 60 days);
- the servers named in your message ("look at my **Facebook ads**", "the file in my **Drive**");
- the servers added to its topic (or project), always;
- the servers Claude asked for in this session.

When Claude needs a server it was not given, it runs `maxxing mcp load <name>` (it knows which ones exist) and stops;
Harness continues by itself with the server loaded (at most twice in a row), and the topic keeps it from then on.
When a message needs a **claude.ai connector** (Google Drive, Gmail...), that message loads every server, as before
(Claude Code loads connectors only all together). The tools of the [Harness Browser](browser) and of your
[Devices](devices) are always loaded when a turn may use them.

A message sent while Claude still has commands or agents running in the background goes to that same Claude, with
the servers it started with: what the topic used meanwhile is loaded once that work is over. Only a server you name
in the message, or one Claude asked for, starts Claude again at once (its background work stops, and the
conversation says so).

## Backup and new server

The memory backup keeps the list of servers (values that look like secrets blanked - tokens, passwords, `API_KEY`-like
names: use `${KEY_NAME}` for them so a restore works as is; plain settings such as `LOG_LEVEL=debug` are kept); a restore adds back the missing ones.
Sign-ins must be done again on a new server.

From a terminal: `maxxing mcp list|add|remove` (see [CLI reference](17-cli-reference.md)).
