---
section: Using Harness Maxxing
---
# Harness Browser

A Chromium on your server for you, your sessions and your agents: Claude drives it when a site has no API (open
pages, click, fill forms, read what only shows with JavaScript or after a sign-in), and you use it yourself, for
example to sign in once so Claude can work in your account. Claude still reads pages with its usual tools (web fetch,
`curl`, an API) first: the browser is slower and costs more, it is used only when a page needs it.

It is not an everyday browser: sound is off, videos do not play by themselves, there are no extensions, and every
tab takes memory on the server.

## Turning it on

It is off until you turn the feature on; then every session may use it, agents only once you say so:

1. **Settings -> Features -> Harness Browser**. The first time, **Set up** installs what the server needs
   (Chromium, its own system user, `socat`, the browser tools; a few minutes, once; or `maxxing browser setup` as
   root).
2. Every project's sessions have it from then on (Claude only starts the browser when a page needs it). To change
   that:
   - a project: its **...** menu in the sessions list -> **Browser...** -> **Can use the Harness Browser** (every
     topic of the project that does not choose for itself);
   - a topic: its **...** menu -> **Browser...** (every session of the topic; **Inherited** = what its project says);
   - an agent: its settings -> **Browser**. An agent is off until you turn it on for it: it never inherits the switch
     of its topic or project.

Everything else is in **Settings -> Browser**.

## Settings -> Browser

Under the switch and **Set up**:

- **My browser**: your browser, a Chromium that runs on your server (not on your computer): its picture (or
  "asleep"), its **Profile** and that profile's **Connection**; **Open my browser** (or a click on the picture) opens
  it in a window to browse yourself (to sign in to a site for Claude, say). Under it, the agents' browsers. The
  **Browser** line at the bottom of the sidebar and **Open my browser** in Ctrl+K open the same window from any page.
- **Profiles**: the sign-ins (cookies) and the connection the browsers use. **+ Add a profile** makes one
  more.
- **Connections**: where the pages go out (the server's IP, your phone, your home box, a proxy). **+ Add a connection**
  adds one.
- **How it works**: the settings shared by every profile (asking you, waiting, sleep, search engine, downloads).

A browser is always shown in a window over the page you are on: yours, an agent's (its card) or a session's
(**Watch**). **–** hides the window; the browser keeps running.

## Profiles: one per project

A **profile** is a set of sign-ins of its own (cookies) and its own connection. **General** is
yours, and the profile of the projects **general** and **system**. **Each other project has its own profile**, named after it: it is made by itself the first time a session or an agent
of the project uses the browser (and, for every project that has agents, when you open Settings -> Browser). It starts
with the connection of General.

Everything of a project shares its profile: its sessions, its agents and your browser when you put it on that profile
are signed in to the same sites. Sign in once, and every agent of the project can work there.

Click a profile to open its page:

- at the top, its **name** (click it to rename it) and its **Connection**; the eye shows the address the sites see
  through it. The connection belongs to the profile: changing it changes it for its agents and sessions too;
- **Persistent**: one browser per agent on this profile, always there, with a live picture while it runs. A click opens
  it to watch or take over;
- **Temporary**: the browsers the sessions opened. They are closed once the session no longer uses them (30 minutes
  without a browser action, the same as **A profile sleeps after**); a line stays: the session, its topic, the sites it
  went to, when, for how long. Text only, no picture;
- **Profile settings**:
  - **When the connection is down** (see below), its memory;
  - **Forget sign-ins** erases its cookies, its tabs and the journal of its actions (the values typed are never kept,
    only their length): you will have to sign in again;
  - **Delete the profile** (a profile you added) erases its sign-ins and tabs too; the agents that used it go back to
    their project's. A project's profile stays as long as its project (forget its sign-ins to start again);
    **General** cannot be deleted.

Each browser only sees its own tabs: a session never sees an agent's tabs, nor yours, and the other way round. You
may open a tab in a session's or an agent's browser yourself (to sign in for it, say): it sees that tab, marked as
yours.

## Connections: where the pages go out

Sites see the address the pages come from. Your server's is a data-center one: some sites (shops, social networks,
banks, anything behind a strict anti-bot) ask more checks or refuse it. A **connection** makes a profile's pages, and
only them, go out somewhere else, by a normal everyday address. Chromium, the pages and Claude stay on your server.

In Settings -> Browser, **Connections** lists them: **Server's IP** (always there) first. **+ Add a
connection** offers four ways:

| Connection | What the sites see | What you need |
|---|---|---|
| **My phone (Tailscale)** (recommended) | your phone's 4G, or your home connection | an iPhone, an Android phone or a computer that stays on, a free Tailscale account |
| **Rented proxy** | an address in the country you choose | a residential or ISP proxy from a provider: its address (`socks5://` or `http://`), a user, a password |
| **WireGuard** | your home connection, or the VPN's | a WireGuard configuration file from your router (Fritz!Box, OpenWrt...) or a VPN |
| **My computer** | the computer you work on | soon |

Then pick it at the top of a profile's page (**Connection**). One connection can serve several profiles.

**My phone (Tailscale)**: a wizard that ticks each step itself when it sees it done.

1. **Install Tailscale for the browser** (**Set up**, a minute, once). It is a Tailscale of the browser's own: the
   rest of the server does not use it.
2. **Sign in to Tailscale**: the server shows up as `harness-browser` in your account.
3. **On the phone** (iPhone or Android): install Tailscale (QR code for the App Store or Google Play), sign in with
   the same account, then **Exit node -> Run as exit node**, and leave it on, charging, on Wi-Fi or 4G (on Android,
   battery optimization off for Tailscale; on an iPhone, do not swipe the app away). Tailscale then wants the exit
   approved once in its console: [login.tailscale.com](https://login.tailscale.com/admin/machines) -> **Machines**,
   **... -> Edit route settings -> Use as exit node**. Until then, the wizard names the devices it sees online that
   are not an exit yet, with a button to the console.
4. **Choose the device** the pages go out by.

**Advanced: Headscale** takes your own Headscale server instead of Tailscale's. **Sign out of Tailscale** unlinks it.

**Rented proxy** and **WireGuard**: a form (address and user, or the configuration to paste). The password and the
WireGuard file go to **Settings -> Keys** (`BROWSER_EXIT_<ID>`), never into the settings. WireGuard needs a small tool
(wireproxy), installed by **Set up** on the exit's page.

**Test** shows what the sites see through a connection (the **Server's IP** entry has it too): the address, its country and
operator, its kind - **Home / ISP**, **Mobile** or **Data center** - the delay and the speed. The kind comes from
ip-api.com (it sees the address of the exit, nothing else), the speed from a small download. A rented proxy that turns
out to be a data center is said plainly: it will not help with the sites that block servers.

You do not need to press **Test** to know a connection works: while Settings -> Browser is open, each connection is
checked by itself every minute (green = up, red = down, *checking...* meanwhile), and the address the sites see is
measured again every hour, without the speed. The last result stays after a restart. **Test** measures the speed too.

Safety:

- Only the browser goes out there: your sessions, agents and the rest of the server keep the server's address.
- Every site name is looked up on your server and checked public before the page goes through the connection: it never
  reaches the network of your home (your router, your NAS, your printer) and never answers for a name itself.

## When a connection is down

A phone switched off, a proxy that stopped: the profile **waits** for its connection, it never goes out by the server's
address on its own (the sites would see your account move to a data center and could lock it).

- Claude's browser action waits for the connection (3 minutes by default, **Settings -> Features -> Harness Browser ->
  Wait for a connection that is down**), then stops using the browser, finishes what it can without it and tells you.
- You get a notification **Browser exit offline** with **Retry now** and **Go on when it is back**.
- The session shows a card **The connection ... is down** with **Go on when it is back**, **Retry now** and **Open the
  connection**. With **Go on when it is back**, Claude goes on by itself as soon as the connection works again.
- In Settings -> Browser the profile says **paused** and the connection **offline**.

A profile can choose the other way: **When the exit is down -> Go out by the server's address**. Its sites may then
see a data-center address and ask more checks.

## Which sites

A browser opens **any public site**. The addresses of your server and of local networks (`localhost`, `127.0.0.1`,
`192.168.x.x`, your router, `*.local`...) are always refused, as are `file:` pages and the browser's own settings
pages.

The **runs** of an agent **in its sandbox** (its page -> **Protection**: schedules, webhooks, e-mail, notifications,
**Run now**) open only **its domains**: the same list as its commands and WebFetch (`example.com` includes its
subdomains). Any other page is refused, and a tab that gets there anyway (a link, a redirect) is emptied; you get a
notification "*agent*: *site* is not one of its domains" with **Add this domain**, for its next runs. Its browser card
says **Limited to its domains**. When **you talk with the agent**, it is not limited (like its commands), and neither
are sessions and free agents.

In the live view of such an agent's browser you go where you want, but a bar warns when the page is outside its
domains (a sign-in page of another site, for example), since its runs would empty that tab: **Add to its domains**
keeps it.

## Using it, watching Claude

The address bar opens what you type: an address (`example.com`), or a **search** for anything else - Google by
default, or DuckDuckGo or Bing (**Settings -> Features -> Harness Browser -> Search engine**; Google sometimes asks a
browser driven by Claude to prove it is not a robot, the other two do not). A new tab has the same search box in its middle.

- **Copy and paste**: Ctrl+C (⌘C) on the page copies its selected text to your clipboard; Ctrl+V pastes yours into
  the page.
- **A file for the page** (a photo, a PDF to send): click its file button on the page, then **Choose a file** in the
  bar that shows; the file goes from your device to that page only. Claude can give a page a file of its own project
  or topic folder (never one elsewhere on the server).
- **A message from the page** (alert, confirm, "leave this page?"): it shows over the page with **OK** / **Cancel**.
- The browser speaks the language of Harness and keeps its time zone (Settings -> General): sites answer in your
  language and see your time.

The **⋮** at the end of the address bar holds what you change while browsing: its **profile** (your browser and an
agent's; a session's is its project's), the profile's **connection** and its state, the **search engine**, the **picture** (**Auto** follows your network, **Smooth** = lighter pictures, more of them, for a
far or slow connection, **Sharp**), **Forget sign-ins**, and **Profiles and connections...** for the rest.

In a session, a line above the message box says when Claude is using the browser, or how many tabs of this session
are open. **Watch** opens the browser window of that session (of the agent, in an agent's conversation); the **x**
only hides the line.

Each tab says who opened it (you, a session, the agent `writer`). When Claude is acting on the tab you are looking at, **click the page to take
over**. While you have the tab, Claude's actions on it wait (at most a minute and a half, then it is told the tab is
busy); its other tabs go on. You give the tab back with **Hand back to Claude**, or by going to another tab (after a
minute without using it, it goes back by itself).

The live view follows your connection: a far one still gets a steady flow (a few pictures are on their way at
once), a slow one gets fewer, never late ones, and the picture quality adapts (or pick it in the **⋮**). The gauge button in the bar under the page shows how smooth it is (pictures per second, their size, the delay
after a click). The view is drawn first while you watch it or Claude acts in it, when the server's processor is busy.

## When Claude needs you

A captcha, a sign-in, a code sent to your phone: Claude does not try to get past them. It asks you and waits
(30 minutes by default, **More settings -> Wait for me**; **Ask me when it is stuck** off = it never asks):

- a notification **"... needs you in its browser"** (also on Telegram when it is linked), with **Open the browser**
  and **Skip**;
- in the session: **Claude needs you**, and the browser window opens by itself on its tab;
- for an agent: it shows as waiting for you like a request to allow (the yellow **!**); the **!** opens the browser
  on its tab.

What Claude asks shows in a bar under the address. Do the step in the page, then **Hand back to Claude**, with a word
for Claude if you like. Claude is told which pages you went to in that tab and gets a picture of the page as you left
it, then goes on. If you drive one of its tabs without being asked, it is told what you did at its next browser
action. **Skip** tells it to do without that step. With no answer in time, it gives up that step for this run.

## Sleep and memory

- When a session's turn ends, the tabs it opened **sleep 15 minutes later** if no new turn uses them (unless you are watching that browser): a page
  left running, a 3D render or a video, does not keep the server busy. Claude opens them again at its next turn.
- A tab unused for 20 minutes **sleeps**: it is closed and kept (italic, moon icon); a click opens it again. Claude
  sees its sleeping tabs and opens them again when it needs them. At most 12 tabs are awake per profile: above that,
  the oldest one sleeps.
- With nobody watching, no session using it and no request, a profile **sleeps** after 30 minutes. Its tabs come
  back, asleep, the next time it starts (when Claude needs it, or when you open it).
- Each running profile is its own Chromium. At most 3 run at once: when another one is needed, the one unused the
  longest sleeps (one busy with Claude or with you is never put to sleep).
- While one runs, the bottom of the sidebar shows **Browser · 620 MB · 6 tabs open**. When the server runs short of
  memory, the line turns amber with **Sleep** (every tab not shown goes to sleep); when memory is critical, the
  oldest tabs sleep by themselves.
- These are in **Settings -> Features -> Harness Browser**: **A tab sleeps after**, **A profile sleeps after**, **Tabs
  awake at most**, **Profiles running at once**, **Wait for a connection that is down**, **Search engine**, plus **Ask me when it
  is stuck**, **Wait for me** and **Allow downloads** (off by default; files go to `downloads/browser` in the workspace).

## Agents

- **Its profile**: an agent uses its project's profile, like the project's sessions and other agents: sign in once
  for all of them. Its browser itself is its own (its tabs), and lasting: it is one of the **Persistent** browsers of
  that profile. To keep an agent apart (one that reads e-mail or a webhook, a client's account), **+ Add a profile**
  and pick it in the agent's settings -> **Browser -> Profile**, or under its browser picture in its info panel.
- An agent that reads text from outside (e-mail, a webhook, the feed) asks you before every browser action (unless
  you trust its outside texts), like for its other tools.
- **In its info panel** (the **Info** button of the agent page), at the top: a small live picture of its tab while its
  browser runs, **Claude is acting** when it is, **Waits for you** when it asks you something, and its **profile**
  under it. A click opens its browser to watch or take over.
- An agent never changes the browser settings (`maxxing browser` commands that change them are refused in its runs).
- In your conversation with an agent, it can ask for its browser itself: turning it **on**, choosing its profile, is
  a request you allow (a card in the conversation), turning it **off** is done at once. Once on, the conversation and
  the runs of the agent both have it.

## From a terminal

```
maxxing browser enable                         install what is missing, then switch the feature on (disable = off)
maxxing browser setup [--exits]                install what it needs (root); --exits: Tailscale and wireproxy too
maxxing browser status                         feature, what is missing, settings, profiles, exits, requests
maxxing browser profile add Shop
maxxing browser profile set shop --exit phone
maxxing browser set acme on                    a project (acme/blog = a topic, acme/blog/writer = an agent)
maxxing browser set acme/blog/writer on        an agent: on, with its project's profile
maxxing browser set acme/blog/writer on --profile shop    it uses the profile shop (inherit = its project's again)
maxxing browser set acme/blog inherit          a topic: its project's switch
maxxing browser show acme/blog                 what it gets, and where it is inherited from
maxxing browser exit test phone                what the sites see through that exit (direct = the server)
maxxing browser forget shop                    erase a profile's sign-ins, tabs and journal
```

Connections are added in Settings -> Browser (their passwords go to the vault). Every command: [CLI reference](17-cli-reference.md#harness-browser).

## Troubleshooting

- **Claude says it has no browser**: ask it, it checks with `maxxing browser status` and `maxxing browser show`:
  the feature off (it can turn it on with your OK), the project or the topic set to no, an agent not turned on. The
  tools come at the next message.
- **"The browser is not set up on this server"**: run **Set up** (Settings -> Features) or `maxxing browser setup`
  as root. On Ubuntu 24.04 it also installs an AppArmor profile Chromium needs.
- **A page is refused**: for an agent in its sandbox, add the site to its domains (its page -> **Protection**).
  Addresses of your own server and of local networks are refused on purpose, for everyone.
- **Google shows "unusual traffic"**: Google spots a Chromium driven by a program, whatever the address: pick
  DuckDuckGo or Bing as the search engine (**⋮** of the window).
- **A site still blocks the browser**: **Test** its profile's connection. **Data center** = the sites see a server: use a
  phone, a home connection or an ISP proxy.
- **"... browser profiles are in use right now"**: every running profile is busy; wait, or raise **Profiles running
  at once**.
- **The connection stays offline**: open it in Settings -> Browser. Tailscale: the phone must be on, signed in to the same
  account, with **Run as exit node** on, and the exit node approved in the Tailscale admin console (the phone ->
  **Edit route settings** -> **Use as exit node**). Proxy: check its address, user and password, then **Test**.
- **The server is slow**: put tabs to sleep (status bar of the browser, or the sidebar line), lower **Tabs awake at
  most** or **Profiles running at once**.
