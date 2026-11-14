---
name: maxxing-browser
description: Turn on, set up, explain or troubleshoot the Harness Browser - a Chromium on this server that sessions and agents drive for sites without an API (sign-ins, forms, clicks, dashboards), that the user watches and takes over in a window (Settings -> Browser). Use when the user wants Claude to open a site, sign in somewhere, fill in a form or click through a page; when the mcp__maxxing-browser__* tools are missing ("you have no browser"); when a page is refused, a site blocks the browser, a connection (phone, proxy, WireGuard) is offline; or when the user asks where the browser, its profiles or its connections are.
---

# Harness Browser

One Chromium per **profile** on this server (sign-ins + the connection it goes out by). Each project has its own
profile, **General** is the user's own (also the projects `general` and `system`). Every session and every agent
gets **its own browser** inside its profile: it sees only its tabs. Docs: `docs/user/33-browser.md` (Docs ->
Harness Browser).

Where it is in the UI (name it in the user's language, as the UI shows it: in French **Réglages -> Fonctionnalités
-> Harness Browser**, **Réglages -> Navigateur**, **Regarder**):
- **Settings -> Features -> Harness Browser**: the feature switch, **Set up** once;
- **Settings -> Browser**: My browser, Profiles, Connections, how it works (asks, downloads, sleep);
- the **Browser** line at the bottom of the sidebar, or Ctrl+K "my browser": the user's own browser, in a window;
- in a session: the line above the message box, **Watch** = this session's browser in a window;
- an agent: its info panel (its browser's picture, its profile); a project or a topic: its **...** menu -> **Browser...**.

## Use it only when nothing simpler works
Read a page with WebFetch, `curl`, an API or the `web-scraping` skill first: faster, cheaper (the browser tools
cost about 5k tokens a turn). The browser is for JavaScript-only pages, sign-ins, forms and clicks.

## The tools are missing in this session
Check, in this order:
```bash
maxxing browser status            # feature on/off, what is missing on the server
maxxing browser show <p>/<t>      # what this folder gets, and where it comes from (project, topic, agent)
```
1. **Feature off**: ask the user, then `maxxing browser enable` (installs what is missing as root, about a minute,
   then switches it on; the same as Settings -> Features -> Harness Browser -> Set up). Never on your own.
2. **Turned off for this project or topic**: the user's choice; `maxxing browser set <p>/<t> on` only if they ask.
3. **An agent**: off until its owner turns it on (its settings -> Browser, or `maxxing browser set <p>/<t>/<agent> on`;
   the agent's own conversation asks with `maxxing agents set <itself> browser.enabled=true`).
4. Then say: **the tools come at the next message** (a turn's tools are fixed when it starts).

## Sign-ins, captchas, codes
- Never ask the user for a password in the chat. Call `ask_human` (the user gets a notification, Telegram too, and
  the window opens on the tab; it waits 30 min by default), or tell them: **Watch** above the message box, then
  sign in in the page. Sign-ins stay in the **profile**: every session and agent of the project has them after.
- To sign in once for a whole project ahead of time: Settings -> Browser -> the project's profile -> open it.
- Tabs the user opened in your browser are marked: leave them alone.

## When it goes wrong
| Symptom | What to do |
|---|---|
| "not set up on this server" | `maxxing browser setup` (root), or **Set up** in Settings -> Features |
| A page refused (agent in its sandbox) | only its domains: the notification **Add this domain**, or `maxxing agents set <path> domains='["example.com"]'` (owner) |
| A page refused (anyone) | this server, local networks, raw IPs, `file:` and Chromium pages are refused on purpose |
| Google "unusual traffic" | Google spots a driven Chromium, not the address: the search engine setting (⋮ menu of the window) -> DuckDuckGo or Bing |
| A site blocks the browser | Settings -> Browser -> the profile's connection -> **Test** (the eye = the address sites see); **Data center** => a phone (Tailscale), a home box (WireGuard) or an ISP proxy |
| "the connection is down" | stop using the browser and say so; the session shows **Go on when it is back** / **Retry now** |
| Tailscale phone never online | the phone on, same account, **Run as exit node** on, **and** the exit node approved in the Tailscale admin console (machine -> Edit route settings -> Use as exit node) |
| "profiles are in use right now" | 3 run at once by default: wait, or `maxxing browser settings --max-profiles N` |
| Server slow | `maxxing browser settings --tab-sleep MIN --max-tabs N`, or put tabs to sleep from the window |

## Commands (owner only: refused in an agent's runs)
```bash
maxxing browser enable | disable                  # the feature
maxxing browser set acme on|off|inherit           # a project (acme/blog = a topic)
maxxing browser set acme/blog/writer on [--profile shop|inherit]   # an agent, optionally on another profile
maxxing browser profile add Shop [--exit phone]   # a profile of its own (sign-ins apart)
maxxing browser exit test phone|direct            # what the sites see
maxxing browser forget <id>                       # erase a profile's sign-ins, tabs and journal
```
Connections (Tailscale, proxy, WireGuard) are added in Settings -> Browser -> Connections: their passwords go to the
vault, never in a file or the chat.
