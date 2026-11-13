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

It is off everywhere until you turn it on:

1. **Settings -> Features -> Harness Browser**. The first time, **Set up** installs what the server needs
   (Chromium, its own system user, `socat`, the browser tools; a few minutes, once; or `maxxing browser setup` as
   root).
2. Then say who may use it:
   - a project: its **...** menu in the sessions list -> **Browser...** -> **Can use the Harness Browser** (every
     topic of the project that does not choose for itself);
   - a topic: its **...** menu -> **Browser...** (every session of the topic; **Inherited** = what its project says);
   - an agent: its settings -> **Browser**. An agent is off until you turn it on for it: it never inherits the switch
     of its topic or project. Turned on, it gets **its own browser** (see below).

The browser has its own page: **Browser** in the sidebar.

## Profiles

A **profile** is a browser of its own: its own sign-ins (cookies), its own list of sites, its own exit (where its pages
go out, see below). **Main** always exists and is used by the sessions of every project and topic that do not choose
another one. Make another profile for what you want kept apart: a client, a second shop account. Each agent turned on
gets one of its own (see [Agents](#agents)).

On the Browser page, **Your browsers** lists Main and the profiles you made, **Agents' browsers** the agents' own.

- **New profile**: the **+** of the Browser page -> **New profile**, give it a name (`Shop`, `Client Acme`).
- **Profile settings** (button above the live view): its name, its **Exit**, **Sites it may open**, **When the exit is
  down**, who uses it, its memory.
- **Sites it may open**:
  - **Only these sites** (the default): type the sites it needs (`shop.example.com`, `example.com`: subdomains are
    included). Any other page is refused and Claude is told why (and which site to ask you to add). Images and
    scripts those pages load from elsewhere still come.
  - **Any public site**: any site on the internet.

  In both cases the addresses of your server and of local networks (`localhost`, `127.0.0.1`, `192.168.x.x`, your
  router, `*.local`...) are always refused, as are `file:` pages and the browser's own settings pages.
- **Sign-ins** stay in the profile on the server. **Forget sign-ins** erases its cookies, its tabs and the journal of
  its actions (the values typed are never kept, only their length): you will have to sign in again.
- **Delete the profile** erases its sign-ins and tabs too. A project or a topic that chose it goes back to what it
  inherits (in the end, **Main**). An agent that used it has **no browser** any more (never your sign-ins by itself):
  turn its browser on again to give it a new one. **Main** cannot be deleted.

## Who uses which profile

The **Browser...** window of a project or a topic has a **Profile** choice. **Inherited** takes the one of the parent:
a topic its project's, a project **Main**. So choosing a profile for a project is enough for all its topics and their
sessions.

The same window shows the profile's exit and its state, and **Open the browser** on that profile.

## Exits: where the pages go out

Sites see the address the pages come from. Your server's is a data-center one: some sites (shops, social networks,
banks, anything behind a strict anti-bot) ask more checks or refuse it. An **exit** makes a profile's pages, and only
them, go out somewhere else, by a normal everyday address. Chromium, the pages and Claude stay on your server.

On the Browser page, **Exits** in the second bar lists them, with **Server** (the server's own address, always there)
last. **+ Add an exit** offers four ways:

| Exit | What the sites see | What you need |
|---|---|---|
| **My phone (Tailscale)** (recommended) | your phone's 4G, or your home connection | an iPhone, an Android phone or a computer that stays on, a free Tailscale account |
| **Rented proxy** | an address in the country you choose | a residential or ISP proxy from a provider: its address (`socks5://` or `http://`), a user, a password |
| **WireGuard** | your home connection, or the VPN's | a WireGuard configuration file from your router (Fritz!Box, OpenWrt...) or a VPN |
| **My computer** | the computer you work on | soon |

Then pick the exit in a profile's settings (**Exit**). One exit can serve several profiles.

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

**Test** shows what the sites see through an exit (the **Server** entry has it too): the address, its country and
operator, its kind - **Home / ISP**, **Mobile** or **Data center** - the delay and the speed. The kind comes from
ip-api.com (it sees the address of the exit, nothing else), the speed from a small download. A rented proxy that turns
out to be a data center is said plainly: it will not help with the sites that block servers.

Safety:

- Only the browser goes out there: your sessions, agents and the rest of the server keep the server's address.
- Every site name is looked up on your server and checked public before the page goes through the exit: an exit never
  reaches the network of your home (your router, your NAS, your printer) and never answers for a name itself.

## When an exit is down

A phone switched off, a proxy that stopped: the profile **waits** for its exit, it never goes out by the server's
address on its own (the sites would see your account move to a data center and could lock it).

- Claude's browser action waits for the exit (3 minutes by default, **Settings -> Features -> Harness Browser -> Wait
  for a down exit**), then stops using the browser, finishes what it can without it and tells you.
- You get a notification **Browser exit offline** with **Retry now** and **Go on when it is back**.
- The session shows a card **The exit ... is down** with **Go on when it is back**, **Retry now** and **Open the
  exit**. With **Go on when it is back**, Claude goes on by itself as soon as the exit works again.
- On the Browser page the profile says **paused** and the exit **offline**.

A profile can choose the other way: **When the exit is down -> Go out by the server's address**. Its sites may then
see a data-center address and ask more checks.

## Using it, watching Claude

The address bar opens what you type: an address (`example.com`), or a **Google search** for anything else (a profile
limited to a list of sites needs `google.com` in it to search). A new tab has the same search box in its middle.

- **Copy and paste**: Ctrl+C (⌘C) on the page copies its selected text to your clipboard; Ctrl+V pastes yours into
  the page.
- **A file for the page** (a photo, a PDF to send): click its file button on the page, then **Choose a file** in the
  bar that shows; the file goes from your device to that page only. Claude can give a page a file of its own project
  or topic folder (never one elsewhere on the server).
- **A message from the page** (alert, confirm, "leave this page?"): it shows over the page with **OK** / **Cancel**.
- The browser speaks the language of Harness and keeps its time zone (Settings -> General): sites answer in your
  language and see your time.

The **Browser** page has two parts:

- the second bar: **Your browsers**, then **Agents' browsers** (each with its exit and its state: tabs open, asleep,
  paused), then **Exits**, and **+** to add a profile or an exit;
- the profile picked, live: its name, **via** its exit, who uses it, **Profile settings**, **Sleep**; then the browser
  itself: tabs, `+` for a new tab, the address bar, the page (full screen on a phone). A new tab shows your sites to
  open in one click.

In a session, a line above the message box says when Claude is using the browser, or how many tabs of this session
are open. **Watch** opens the browser window on that session's tab; the **x** only hides the line.

Every tab of a profile is seen by every session and agent that uses that profile; each tab says who opened it (you,
a session, the agent `writer`). When Claude is acting on the tab you are looking at, **click the page to take
over**. While you have the tab, Claude's actions on it wait (at most a minute and a half, then it is told the tab is
busy); its other tabs go on. You give the tab back with **Hand back to Claude**, or by going to another tab (after a
minute without using it, it goes back by itself).

The live view follows your connection: a slow network gets fewer pictures, never late ones, and the picture quality
adapts. The gauge button in the bar under the page shows how smooth it is (pictures per second, their size, the delay
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

- A tab unused for 20 minutes **sleeps**: it is closed and kept (italic, moon icon); a click opens it again. Claude
  sees its sleeping tabs and opens them again when it needs them. At most 12 tabs are awake per profile: above that,
  the oldest one sleeps.
- With nobody watching, no session using it and no request, a profile **sleeps** after 30 minutes. Its tabs come
  back, asleep, the next time it starts (when Claude needs it, or when you open it on the Browser page).
- Each running profile is its own Chromium. At most 3 run at once: when another one is needed, the one unused the
  longest sleeps (one busy with Claude or with you is never put to sleep).
- While one runs, the bottom of the sidebar shows **Browser · 620 MB · 6 tabs open**. When the server runs short of
  memory, the line turns amber with **Sleep** (every tab not shown goes to sleep); when memory is critical, the
  oldest tabs sleep by themselves.
- These are in **Settings -> Features -> Harness Browser**: **A tab sleeps after**, **A profile sleeps after**, **Tabs
  awake at most**, **Profiles running at once**, **Wait for a down exit**, plus **Ask me when it is stuck**, **Wait
  for me** and **Allow downloads** (off by default; files go to `downloads/browser` in the workspace).

## Agents

- **Its own browser**: an agent turned on gets a browser of its own, with its name: its own sign-ins, apart from
  yours. It starts with the sites and the exit of the browser it would have used (its topic's, else Main), then you
  change them in its profile settings. Sign it in to the sites it needs once (open its browser, sign in, done).
- **Sign-ins** (its settings -> Browser): **Its own browser** (the default), **Its topic's**, or **Share** another
  browser (Main, a client's, another agent's): it then works with the sites you are signed in to there. An agent that
  reads text from outside (e-mail, a webhook, the feed) should keep its own: a message written by a stranger could try
  to steer it, and its settings warn you when it uses Main. Such an agent also asks you before every browser action
  (unless you trust its outside texts), like for its other tools.
- **In its info panel** (the **Info** button of the agent page): a small live picture of its tab while its browser
  runs, **Claude is acting** when it is, **Waits for you** when it asks you something. A click opens its browser to
  watch or take over.
- An agent never changes the browser settings (`maxxing browser` commands that change them are refused in its runs).
- In your conversation with an agent, it can ask for its browser itself: turning it **on**, choosing whose sign-ins
  it uses, is a request you allow (a card in the conversation), turning it **off** is done at once. Once on, the
  conversation and the runs of the agent both have it.

## From a terminal

```
maxxing browser setup [--exits]                install what it needs (root); --exits: Tailscale and wireproxy too
maxxing browser status                         feature, what is missing, settings, profiles, exits, requests
maxxing browser profile add Shop --sites shop.example.com
maxxing browser profile set shop --exit phone --public
maxxing browser set acme on                    a project (acme/blog = a topic, acme/blog/writer = an agent)
maxxing browser set acme/blog/writer on        an agent: its own browser
maxxing browser set acme/blog/writer on --profile shop    it shares the sign-ins of shop (own = its own again)
maxxing browser set acme/blog inherit --profile inherit   a topic: its project's switch and profile
maxxing browser show acme/blog                 what it gets, and where it is inherited from
maxxing browser exit test phone                what the sites see through that exit (direct = the server)
maxxing browser forget shop                    erase a profile's sign-ins, tabs and journal
```

Exits are added on the Browser page (their passwords go to the vault). Every command: [CLI reference](17-cli-reference.md#harness-browser).

## Troubleshooting

- **"The browser is not set up on this server"**: run **Set up** (Settings -> Features) or `maxxing browser setup`
  as root. On Ubuntu 24.04 it also installs an AppArmor profile Chromium needs.
- **A page is refused**: add its site to the profile's list (**Profile settings**), or switch it to **Any public
  site**. Addresses of your own server and of local networks are refused on purpose.
- **A site still blocks the browser**: **Test** its profile's exit. **Data center** = the sites see a server: use a
  phone, a home connection or an ISP proxy.
- **"... browser profiles are in use right now"**: every running profile is busy; wait, or raise **Profiles running
  at once**.
- **The exit stays offline**: open it on the Browser page. Tailscale: the phone must be on, signed in to the same
  account, with **Run as exit node** on. Proxy: check its address, user and password, then **Test**.
- **The server is slow**: put tabs to sleep (status bar of the browser, or the sidebar line), lower **Tabs awake at
  most** or **Profiles running at once**.
