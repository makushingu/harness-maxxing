---
name: maxxing-mcp
description: Add, connect, check or remove an MCP server for Claude Code in Harness Maxxing (Settings -> MCP). Use when the user wants Claude to use a service through MCP ("connect the Google Ads MCP", "add the Notion MCP", "install this MCP server", a URL ending in /mcp or /sse, an `npx …-mcp` command), when an MCP tool is missing or "needs authentication", or asks which MCP servers exist.
---

# MCP servers

Harness lists every MCP server of Claude Code in **Settings -> MCP**: where it applies (every session, or one
topic), its state (Connected / To connect / Error / To approve) and the buttons Connect and Remove.
Docs: `docs/user/28-mcp.md` (Settings -> Docs -> MCP servers).

## Where to add it
- Only the topic that needs it (most cases: an ads account for the `ads` topic): `--where projects/<p>/topics/<t>`.
- Every session: no `--where` (a tool used everywhere, e.g. a search engine).
Ask when it is not obvious. A server in a topic is invisible to the other topics.

## Add
```bash
maxxing mcp add google-ads https://mcp.example.com/mcp --where projects/acme/topics/ads
maxxing mcp add notion https://mcp.example.com/mcp --header 'Authorization: Bearer ${NOTION_TOKEN}'
maxxing mcp add files --command 'npx -y @acme/files-mcp' --env 'API_KEY=${ACME_KEY}' --where projects/acme/topics/blog
maxxing mcp list            # checks the states (takes a few seconds)
maxxing mcp remove notion [--where …]
```
- **Never write a token in clear** in the config: put it in the vault (`printf %s "$V" | maxxing keys set NAME`,
  or ask the user to add it in Settings -> Keys) and reference it as `${NAME}`. `maxxing mcp add` makes the
  referenced keys available to sessions (vault flag `expose`).
- Do not edit `.claude.json` by hand, and do not use `claude mcp add` directly: `maxxing mcp` writes in the
  Claude Code folder Harness uses (it can differ from `~/.claude`).
- The new server is loaded by the **next** turn: say so ("it will be available from your next message").

## Connect (OAuth)
State "To connect" (needs authentication) = the service uses a sign-in, no key needed. It cannot be done from a
turn (it needs the user's browser): tell the user to open **Settings -> MCP -> Connect**, open the sign-in page,
accept, then paste the address of the page they land on (an error page on `localhost` is expected; its address
contains `code=`). The connection is kept for every session.

## Troubleshoot
- `Error`: hover the state for Claude Code's message; for an URL, check it with `curl -sI`; for a command, run it
  once by hand in the topic folder.
- `To approve`: a `.mcp.json` file in a project folder that Claude Code was never told to trust; remove it from
  Settings -> MCP or add the server with `maxxing mcp add` instead.
- After a topic is renamed, its servers follow it; a deleted topic leaves its servers in `Error` (remove them).
- The memory backup keeps the list of servers (secrets blanked) and a restore adds them back; OAuth connections
  must be done again on a new server.
