---
section: Using Harness Maxxing
---
# Harness Browser

One Chromium on your server for you, your sessions and your agents: Claude drives it when a site has no API (open
pages, click, fill forms, read what only shows with JavaScript or after a sign-in), and you use it yourself, for
example to sign in once for everybody. Claude still reads pages with its usual tools (web fetch, `curl`, an API)
first: the browser is slower and costs more, it is used only when a page needs it.

It is not an everyday browser: sound is off, videos do not play by themselves, there are no extensions, and every
tab takes memory on the server.

It is off everywhere until you turn it on:

1. **Settings -> Features -> Harness Browser**. The first time, **Set up** installs what the server needs
   (Chromium, its own system user, `socat`, the browser tools; a few minutes, once; or `maxxing browser setup` as
   root).
2. Then let it be used, per place:
   - a topic: its **...** menu in the sessions list -> **Browser...** -> **Can use the Harness Browser** (every
     session of the topic);
   - an agent: its settings -> **Browser**.

The browser itself has a page: **Browser** in the sidebar.

## Tabs: who sees what

There is one browser, so one set of sign-ins. Each tab says who sees it, with a small mark on the tab:

| Mark | Who sees the tab |
|---|---|
| lock: **Only me** | you only (the default for the tabs you open) |
| **#** **Topic** `acme/blog` | the sessions of that topic |
| folder: **Project** `acme` | the sessions of every topic of the project |
| robot: **Agent** `writer` | that agent only |

- A tab a session opens is shared with **its topic**; a tab an agent opens is **its own** (no other agent and no
  session sees it). Each tab says who opened it.
- Click the mark of a tab to change it: **Share with -> Only me / a topic / a project / an agent**. Taking a tab back
  = **Only me**. To let an agent work in a page you opened (signed in, a form half filled), share that tab with it.
- A session sees, and drives, only the tabs shared with its topic or its project; an agent only its own tabs. Your
  **Only me** tabs are never shown to Claude, nor what you do in them. You see every tab.
- All tabs share the same sign-ins (one browser): an agent signed in to a site is signed in for you too.
- Two sessions can work at the same time, each in its tabs.

Sign-ins are common to every tab: a session allowed to use the browser can open a site where you are signed in.
That is the point (you sign in once), and the list of sites below sets where it may go.

## Which sites

Settings -> Features -> Harness Browser:

- **Only these sites** (the default): type the sites it needs (`shop.example.com`, `example.com`: subdomains are
  included). Any other page is refused and Claude is told why. Images and scripts those pages load from elsewhere
  still come.
- **Any public site**: any site on the internet.

In both cases the addresses of your server and of local networks (`localhost`, `127.0.0.1`, `192.168.x.x`, your
router, `*.local`...) are always refused, as are `file:` pages and the browser's own settings pages. The browser has
no network of its own: everything goes through a filter of Harness Maxxing that checks each address.

## Using it, watching Claude

On the **Browser** page (or the window opened from a session), you have the browser in front of you: tabs, `+` for a
new tab, the address bar, the page live (full screen on a phone). Click or type in the page and it is yours. A new
tab shows your sites to open in one click.

In a session, a line above the message box says when Claude is using the browser, or how many tabs of the topic are
open. **Watch** opens the browser window on that session's tab; the **x** only hides the line.

When Claude is acting on the tab you are looking at, **click the page to take over**. While you have a tab shared
with Claude, its actions on that tab wait (at most a minute and a half, then it is told the tab is busy); its other
tabs go on. You give the tab back with **Hand back to Claude**, or by going to another tab (after a minute without
using it, it goes back by itself).

## When Claude needs you

A captcha, a sign-in, a code sent to your phone: Claude does not try to get past them. It asks you and waits
(30 minutes by default, **More settings -> Wait for me**):

- a notification **"... needs you in its browser"** (also on Telegram when it is linked), with **Open the browser**
  and **Skip**;
- in the session: **Claude needs you**, and the browser window opens by itself on its tab;
- for an agent: it shows as **waiting for you** like a request to allow (the yellow **!** of the Office, the agents
  list, the dot under its topic); the **!** opens the browser on its tab.

What Claude asks shows in a bar under the address. Do the step in the page, then **Hand back to Claude**, with a word
for Claude if you like. Claude is told which pages you went to in that tab and gets a picture of the page as you
left it, then goes on. If you drive a tab shared with Claude without being asked, it is told what you did at its next
browser action. **Skip** tells it to do without that step. With no answer in time, it gives up that step for this
run.

## Sleep and memory

- A tab unused for 20 minutes **sleeps**: it is closed and kept (italic, moon icon); a click opens it again. Claude
  sees its sleeping tabs and opens them again when it needs them. At most 12 tabs are awake: above that,
  the oldest one sleeps.
- With nobody watching, no session using it and no request, the browser **sleeps** after 30 minutes. Its tabs come
  back, asleep, the next time it starts (when Claude needs it, or when you open the **Browser** page).
- While it runs, the bottom of the sidebar shows **Browser · 620 MB · 6 tabs open**. When the server runs short of
  memory, the line turns amber with **Sleep** (every tab not shown goes to sleep); when memory is critical, the
  oldest tabs sleep by themselves.
- These times are in **More settings**: **A tab sleeps after**, **The browser sleeps after**, **Tabs awake at most**.

## Agents

- An agent started by an outside text (an e-mail, a webhook, another agent) asks you before **every** browser action,
  like for its other tools (unless you trust that agent's outside texts): a message written by a stranger cannot
  drive your signed-in tabs on its own.
- An agent never changes the browser settings (`maxxing browser on|off|settings` is refused in its runs).
- In your conversation with an agent, it can ask for its browser itself: turning it **on** is a request you allow
  (a card in the conversation), turning it **off** is done at once. Once on, the conversation and the runs of the
  agent both have it.

## Sign-ins and downloads

- **Keep its sign-ins** (on by default): the browser's profile (cookies, sign-ins) stays on the server. Off: a fresh
  browser at every start. **Forget sign-ins** erases the profile, the tabs and the journal of its actions (the values
  typed are never kept, only their length).
- **Allow downloads** (off by default): files go to `downloads/browser` in the workspace.

## From a terminal

```
maxxing browser setup                          install what it needs (root)
maxxing browser status                         feature, what is missing, settings, tabs, requests waiting
maxxing browser settings --sites example.com,shop.example.org
maxxing browser settings --public --tab-sleep 30 --idle 60 --max-tabs 8
maxxing browser on acme/blog                   the sessions of a topic may use it
maxxing browser on acme/blog/writer            an agent (project/topic/agent)
maxxing browser off acme/blog
maxxing browser show acme/blog                 its switch and the tabs it sees
maxxing browser forget                         erase the sign-ins, the tabs and the journal
```

## Troubleshooting

- **"The browser is not set up on this server"**: run **Set up** (Settings -> Features) or `maxxing browser setup`
  as root. On Ubuntu 24.04 it also installs an AppArmor profile Chromium needs.
- **A page is refused**: add its site to the list, or switch to **Any public site**. Addresses of your own server
  are refused on purpose.
- **Claude does not see a tab**: share it with its topic or its project, or with the agent (the mark of the tab).
- **The server is slow**: put tabs to sleep (status bar of the browser, or the sidebar line), lower **Tabs awake at
  most**.
