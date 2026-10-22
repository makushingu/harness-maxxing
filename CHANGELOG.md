# Changelog

All notable changes to Harness Maxxing. Versions follow semantic versioning.
`maxxing update` prints the lines added here since your installed version.

## 2.0.0-alpha.93 - 2026-10-22

Changes:
- **Mark a server issue as seen.** In the list of the dot at the bottom of the sidebar, **Seen** stops an issue
  (a scheduled job that failed once, an old backup...) from counting in the dot; it comes back when it changes, or
  after 24 hours if it is still there.
- **Sideways scrolling glides to the nearest session** instead of jumping to it when you let go.
- **Leftovers of the old paid model removed.** Harness Maxxing installs and updates from the public git repository;
  the code that downloaded signed archives with a license key, `maxxing license check`, `maxxing license ping` and
  `maxxing update --allow-downgrade` are gone. Servers installed with a key before 2.0.0a87 still switch to the git
  repository by themselves, customizations kept; an optional Enterprise key works as before (Settings -> License).
- **Third-party notices**: `THIRD_PARTY_NOTICES.md` lists the code and fonts shipped or installed with Harness
  Maxxing, with their licenses.

## 2.0.0-alpha.92 - 2026-10-22

Changes:
- **Donate gets a hand-and-heart icon in the app's accent colour** (no more pink). In the sidebar it is now a small
  icon next to the eye, the theme and the account, instead of a large button; **Settings -> Support** moves to the end
  of the Settings list, in the accent colour. **Settings -> Support -> Hide the Donate buttons** still removes them.

## 2.0.0-alpha.91 - 2026-10-22

Changes:
- **A visible Donate button** at the bottom of the sidebar (on a phone or a tablet: in the ⊞ menu); the small donation
  links of What's new, the Feedback window and Settings -> License are now Donate buttons too. The donation page
  (harness-maxxing.com/donation) now has one tab per way to pay: Lightning, Bitcoin. **Settings -> Support -> Hide the
  Donate buttons** still removes them all.

## 2.0.0-alpha.90 - 2026-10-22

Changes:
- **Settings -> Support**: Harness Maxxing is free, donations fund its development. A **Donate** button opens the
  donation page of harness-maxxing.com (Bitcoin or Lightning) in a new tab; a small "Support the project" link also
  shows at the bottom of What's new, after a Feedback is sent and in Settings -> License. They are only links: the app
  never talks to a payment service. **Hide the donation links** (Settings -> Support) removes the small links for
  every browser.

## 2.0.0-alpha.89 - 2026-10-22

Changes:
- **Feedback button at the bottom of the sidebar** (on a phone or a tablet: ⊞ -> Feedback): report a bug, suggest an
  idea or write anything to the Harness Maxxing team, straight from the app. Your email is required, so we can answer
  you; only your message, its type, the version and the language are sent.
- Settings -> License shows "enterprise" for an Enterprise key (it said "paid").

## 2.0.0-alpha.88 - 2026-10-22

Changes:
- **Settings -> License: an optional Enterprise key, for the companies that need one.** The page explains who needs
  a key (an organisation using Harness for its affiliates or clients, a paid offer built on it); nobody else has
  anything to do. A key can also be given in the onboarding step About you. It changes nothing in how Harness works:
  updates keep coming from GitHub.
- The installer no longer deals with license keys: every install comes from GitHub (`LICENSE=` still works and just
  records the key).
- `maxxing license status` says where updates come from; `maxxing license remove` forgets the key.

## 2.0.0-alpha.87 - 2026-10-22

Changes:
- **Servers installed with a license key now update from GitHub, like every other install.** A few minutes after
  this update the code follows the `stable` branch of the public repository, at the same version, with your
  customizations kept. Nothing to do; your key is kept (Settings -> System shows it).

## 2.0.0-alpha.86 - 2026-10-22

Changes:
- **Say hello to the authors, if you want.** A new onboarding step **About you** and a card **Harness Maxxing
  team** in Settings -> Profile: help count the installations (anonymous: a random number and the version, once a
  day), leave an email for security alerts and, if you like, the product news. Everything is optional;
  **Stop, don't contact me** ends it. An update never turns any of it on: an existing server sends nothing until
  you check something.

## 2.0.0-alpha.85 - 2026-10-22

Changes:
- **The code moved to `github.com/makushingu/harness-maxxing`.** The old address redirects; nothing to do.
- New installs follow the `stable` branch (published versions only) instead of `main`.

## 2.0.0-alpha.84 - 2026-10-22

Changes:
- **Harness can update itself while nobody uses it** (off by default): Settings -> System -> "Update by itself
  when nobody is here". It only does it when nobody is on the interface, nothing is running and the update does
  not touch your customizations; otherwise it waits and tells you in the notifications.
- **Chat: a Connect button when the agent asks to sign in to an MCP server.** The sign-in steps of Settings -> MCP
  open right in the conversation.
- **Delete dialog: click the name to fill the field, Enter to confirm.**
- **Sessions: the mouse wheel scrolls the columns sideways** when the pointer is between columns (on no session).
- Browser of my PC: the PC's browser tools are always there for a turn, even when Claude's own config lost them.

Fixes:
- Adding, renaming or removing an MCP server no longer erases a setting Claude Code saved at the same moment.
- A `~/.claude.json` that is a link to your dotfiles stays a link when Harness Maxxing updates it.
- Restoring a backup whose MCP list has a damaged entry skips that entry and restores the others, instead of stopping
  with an error.
- A very long MCP header or environment value can no longer freeze Harness Maxxing for seconds.
- Backup settings: a GitHub token typed with an accent or a space now says "not valid" instead of failing with a
  server error.
- A `.gitignore` inside a backed-up folder no longer silently leaves files out of the backup.
- Restoring a backup where a folder sits in place of a file now skips that file (and keeps the one you had) and
  restores everything else, instead of stopping half-way with an error.
- Harness PC: unpairing the PC while it reconnects no longer leaves it paired; a malformed message from the PC agent
  is ignored instead of cutting the link; the browser MCP endpoint answers a malformed call with a proper error.
- `maxxing update`: when it stops because your uncommitted changes cannot be saved, your edits of the web UI are put
  back in place instead of staying hidden in a git stash.

## 2.0.0-alpha.83 - 2026-10-22

Changes:
- **The cost shown under each answer is explained.** Hover (or tap) the amount: it is the price of the answer at
  Anthropic API prices. With a Claude subscription it is not billed, it only shows how much you used; with an API
  key it is billed to your account. The model, duration, tokens and cache share have their tooltip too.
- **Choose what the line under each answer shows** (model, duration, cost, tokens, cache share): ⚙ at the end of
  the line, or Settings -> General -> Line under each answer. Same choice on every device.

## 2.0.0-alpha.82 - 2026-10-22

Changes:
- **Harness Maxxing is now free and fair source.** The code is public on GitHub: anyone can install it, use it,
  modify it, fork it and share it for free. Selling it, offering it as a paid service or using its name for
  another product needs the owners' written consent; an organisation uses it for itself only. See Settings ->
  Docs -> License.
- **No license key needed any more.** `curl -fsSL https://get.harness-maxxing.com | bash` installs from the public
  git repository and `maxxing update` keeps it up to date from there. A license key you already have keeps
  working, with its signed updates (`LICENSE=HM-…`).
- **No more "no license on this server" warning** in `maxxing doctor` and `maxxing license status`: a server
  without a key is the normal case.

Fixes:
- Renaming a project or topic while one of its sessions is running now says to stop the session first, instead of
  "this name already exists".
- Phones and tablets: the *All / Running / Unread* chips of the Sessions panel are easier to tap.
- Phones and tablets: the *jump to the latest message* pill is easier to tap.
- Phones and tablets: the ⋯ button of a file row is easier to tap.
- A voice message transcript with a very long word or link now wraps inside its bubble instead of running off the screen.
- Phones and tablets: the play button of a voice message and the audio player buttons (play, mute, speed) are easier to tap.
- Settings → *My PC's browser* (pairing): on phones the install command is shortened and its Copy button stays on screen.
- Settings → *My PC's browser*, paired: on phones the idle-time choice scrolls inside the card and long recent URLs are shortened, instead of clipping the card.
- Settings → *System* on phones: the *check your extensions* link and the *Repair with Harness* button wrap instead of pushing the Version card off the screen.
- A voice message sent directly must be a file under an `attachments` folder of the workspace (its transcription rewrites the file).
- Settings → *MCP*: removing a project server only rewrites a `.mcp.json` inside the workspace.
- Restoring a backup checks its backup settings (patterns, schedule) like Settings does; a pattern that could freeze the backup is refused.
- Settings → *My PC's browser*: Claude can no longer reach the PC's own network through oddly written addresses (`http:/192.168.1.1`, `%31`, full-width digits) or names such as `127.0.0.1.nip.io`.
- `maxxing update --branch` only accepts the branch names the installer accepts.

## 2.0.0-alpha.81 - 2026-10-21

Changes:
- **A tidier conversation header on phones.** Three short lines: ☰, the app and ⊞ at the top; the session
  title; then the topic (tap it for its menu), the cost and a small ring showing how full the context is.
  [Show me](#show:mobile-header)
- **Menus and lists open as a panel from the bottom on phones and tablets**, easy to reach with the thumb; slide
  it down to close it. The session list bar (*Vertical*, *Collapse all*, *Options*, *New project*) sits right under
  the search.
- **Smoother on phones:** the Settings sections slide in and out, the help folds away with an animation, and
  opening the session list or a long conversation is lighter.

Fixes:
- **No more being sent back to the sign-in page for no reason.** When GitHub refused a token (expired or revoked),
  opening a session that shows a git graph signed you out. The graph now says the token was refused and you stay
  signed in. Same for an extension that answers "not allowed": it shows an error, it no longer signs you out.
- **A message no longer shows twice while Harness summarizes a session you come back to.** It appeared both as
  sent and as "1 message waiting"; it now only shows as sent.
- **A voice message sent after a quiet minute is always transcribed.** One sent at the exact moment the idle
  transcription worker stopped could wait forever and end as "transcription too long".
- **No more blank screen on phones when the sessions cannot be loaded.** While the server restarts or the
  connection drops, the Sessions page now keeps its menu and shows a Retry button.

## 2.0.0-alpha.80 - 2026-10-21

New:
- **Browser of my PC (prepared): Claude will be able to use a browser on your own computer.** The server side is in
  place; the card appears in Settings → MCP as soon as the small **Harness PC** program can be downloaded from your
  server. You will pick Windows, Mac or Linux and your browser (Brave, Chrome, Edge, Vivaldi, Opera, Chromium),
  download Harness PC (already linked to your server) and open it. Claude then opens sites you are signed in to,
  fills forms, reads pages and takes screenshots in a **separate profile** of your browser - your usual tabs,
  passwords and history are never touched. Nothing runs all the time: the browser opens at Claude's first action and
  closes after 10 minutes without one (5 to 60 min), or at once with **Stop now**. A new PC must be confirmed in
  Harness (its address is shown) before Claude can use it, Claude only opens sites on the internet (never your PC or
  your home network: router, NAS, localhost), and no file of your computer can be read or sent to a site.

Fixes:
- **Right-click → Open on GitHub only for GitHub repositories.** A clone whose remote is on another host (GitLab, a
  look-alike domain) with `github.com` somewhere in its address no longer offers a link to an unrelated GitHub
  repository.
- **Branch filter on the Git page works when a file has the branch's name.** A repository with a file called `main`
  at its root showed an error instead of the graph of `main`.
- **Two files with the same name sent at once on Telegram are both kept.** Sending `report.pdf` in two threads of the
  same topic at the same time could lose one file and save the other's content under its name.
- **Telegram no longer freezes on a huge line of Markdown.** A reply with one very long line full of `[`, `_` or `*`
  (a copied web page) could block the bot for seconds: no messages, no /stop. Lines over 2,000 characters are now
  sent as plain text.
- **Bigger Copy buttons on phones and tablets.** The Copy button of code blocks (docs, replies, Settings) is now
  easier to tap: 40 px instead of 36 px.

## 2.0.0-alpha.79 - 2026-10-21

Changes:
- **Voice messages look like voice messages.** No more file name and big player: one bubble with a round mic
  button (tap it to listen to the recording) and the transcript next to it.

## 2.0.0-alpha.78 - 2026-10-21

New:
- **Voice messages are sent right away, like on Telegram.** When you stop recording, the voice message appears
  in the conversation at once, with a player; the server transcribes it, shows the transcript under it and sends
  it to Claude. No more waiting for the transcription before you can go on: talk again or type while it works.
  Prefer to review the text first? Turn off **Settings → Voice → Send voice messages right away**.

## 2.0.0-alpha.77 - 2026-10-21

Changes:
- **No more zooming on phones and tablets.** Pinching or double-tapping no longer zooms the page: the app stays
  in place like a native app. Text sizes stay readable, and fields never make the iPhone zoom in.

Fixes:
- **No dashboard flash when the app opens on a phone.** The dashboard appeared for a split second before your
  last session; the session now shows right away.

## 2.0.0-alpha.76 - 2026-10-21

New:
- **A new layout for phones and tablets.** The conversation now fills the screen and the app opens on your last
  session. **☰** at the top left opens all your sessions: search, **New session**, the *All / Running / Unread*
  filters, then your projects and topics, in bigger rows that are easy to tap. **⊞** at the top right opens
  everything else: every page, notifications, extensions, the update waiting, server health, your Claude plan,
  theme, settings and help. The bar at the bottom is gone. Tablets get the same layout as phones; on a computer
  nothing changes. [Show me](#show:touch-nav)
- **Press and hold** a session, a topic or a project in the list to open its menu (rename, favorite, archive,
  delete...).
- **Bigger microphone and send buttons** on phones and tablets.
- In the installed app, **swipe from the left edge** to open your sessions, from the right edge to open the menu.
- **Settings → General → Layout**: *Auto* (touch layout on phones and tablets), *Touch* or *Desktop*, for each
  device - handy on a tablet with a keyboard. **When the app opens**: your last session or the dashboard.

## 2.0.0-alpha.75 - 2026-10-21

Fixes:
- **The dashboard loads faster with many extensions.** It read the extensions folder again for every widget;
  with 50 extensions a refresh took about 155 ms, now about 23 ms.
- **Text size buttons are easier to tap on a touch tablet.** In the file viewer, the text size button and its
  −, % and + buttons were 32 px high on a tablet; they are now 40 px, like on a phone.
- **The session title, its folder and "Thinking" are easier to tap on a phone.** Their touch areas were about
  20 px high; they are now about 40 px, without making the session header taller.
- **The Infra page is easier to use on a touch screen.** Its fields, buttons and links (Documentation, Create the
  token, Connect Cloudflare or Hostinger, site addresses) are now at least 40 px high on tablets and phones.
- **The feed's source filters are easier to tap.** They were 28 to 36 px high on touch screens; they are now 40 px.
- **The show password button is easier to tap on a tablet.** Sign-in and Settings → Security fields are 44 px
  high on touch screens, and so is their eye button.
- **The Settings menu is easier to tap.** Its section buttons were 36 px high on phones and touch tablets; they are now
  40 px.
- **With "reduce motion" on, the dashboard charts show at once.** Their dots, bars and lines still popped in one by
  one for up to 0.7 s.
- **The plan usage bars no longer vanish after a bad reading.** A broken value saved from a turn made the usage
  request fail until the next turn.
- **A restart no longer calls the plan usage service too early.** After the service asked to wait, a restart forgot it
  and asked again right away.
- **An archive listed during a slow moment is listed in full next time.** If the server was busy when you first opened
  a zip or tar, the list stayed cut short until the file changed.
- **Files whose name is not UTF-8 can be opened, renamed and deleted.** A name copied from an old zip or a Windows
  share showed up in the list but answered "not found".
- **A damaged reading position no longer stops a file from opening at the right place.** A bad value saved in the
  browser broke the restore.
- **One odd answer from the domain registry no longer breaks the Infra page.** An expiry date that was not a date
  stopped every refresh of the page.
- **A damaged line in a session log no longer hides the whole session.** The other messages show as usual.
- **Moving a session while a message is being sent is refused cleanly.** A message sent at the same moment could start
  in the old folder after the move.
- **Webhook sources created at the same time are all kept.** Two sources added at once could overwrite each other.
- **A notification with an odd character is no longer lost.** A webhook whose title held a broken character was
  refused with an error.
- **A webhook with a malformed body gets a clear refusal.** Some bodies made the server answer with an internal error.
- **Stripe deliveries with a forged timestamp are refused cleanly.** A crafted signature header made the server answer
  with an internal error.
- **Webhooks with an unexpected layout get a clear refusal.** A Stripe or GitHub delivery with a missing or odd field
  made the server answer with an internal error.
- **A webhook with a number where text is expected still shows up in the feed.** A Shopify, GitHub or Stripe delivery
  with such a field made the server answer with an internal error.
- **Scheduled job runs are no longer lost from the history.** When several jobs finished at the moment the history was
  being shortened, some runs disappeared.
- **Schedules with unusual digits are refused with a clear message.** A schedule typed with a superscript or Arabic
  digit caused an error or was saved as is.
- **A scheduled job with an odd timeout value still stops on time.** A timeout written as text in the jobs file let
  the job run with no limit.
- **An extension that calls sys.exit no longer disturbs the server.** Its page answers with an error and its widget
  shows one.
- **Installing the same pack twice at once makes two separate projects.** Two clicks in a row could mix both installs
  into one project with duplicate jobs.
- **A password with a broken character is refused with a clear message.** Setting it gave an internal error instead.

## 2.0.0-alpha.74 - 2026-10-20

Improvements:

- **The Tasks page and its dashboard widget load faster on a big board.** With thousands of tasks the list
  is about six times faster and the widget is instant.

## 2.0.0-alpha.73 - 2026-10-20

Fixes:
- **`maxxing custom save` refuses every change of the web UI.** A file under `web/` whose name had a space or an
  accent slipped through and was saved as a customization; it is now refused like the others, and `maxxing update`
  sets it aside the same way.
- **`maxxing custom drop` needs a real id.** An empty id (or one or two characters) matched the first
  customization and removed it; it is now refused, and a prefix shared by several customizations asks for a longer one.
- **A huge priority in `tasks.json` no longer breaks the Tasks page.** A number like `1e999` made every request
  fail; it now counts as no priority.
- **An infinite order or date in `tasks.json` no longer breaks the Tasks page.** It is read as the default value.
- **A task project whose `workspace` is not a name no longer breaks the Tasks page.** The field is ignored.

## 2.0.0-alpha.72 - 2026-10-20

New:
- **Open a branch or a commit on GitHub from the git graph.** Right click a branch label or a commit (long press on a
  phone), in the chat or on the Git page, then **Open on GitHub**: it opens on github.com in a new tab. **Copy the
  GitHub link** and copy the branch name / commit SHA are there too; what is not pushed yet says so. [Show me](#show:git-branch-menu)
- **A dashboard that builds itself.** Every card now assembles smoothly: numbers count up to their value, lists
  and tables rise in row by row, chart bars grow and lines draw, progress bars fill, and **Today's schedule** opens
  each job's line and drops its runs on it from left to right. Cards further down wait until you scroll to them,
  and the cards slide to their new place when the notifications panel opens or closes. Nothing moves when your
  system asks for reduced motion. [Show me](#show:dashboard-motion)
- **Zoom for markdown and text files, and Harness remembers where you were in them.**
  [Show me](#show:text-zoom) A markdown preview or a text editor (Files page, full-screen viewer, file preview)
  has "− 100% +" in its toolbar (the **T** button when space is short): the text gets larger or smaller, the
  passage you are reading stays in place, and the size is kept in this browser. Ctrl/⌘ + wheel (or a trackpad
  pinch) over the text does the same. Switching between **Preview**, **Edit** and **Split**, or opening the file
  again (even after a reload), brings you back to the same passage instead of the top.

Fixes:
- **The plan usage bars stay in the sidebar.** With **Show plan usage** on, the 5-hour and week bars could vanish
  when you came back to a conversation after a break: Anthropic's usage endpoint asked to wait, and that answer hid
  the figures already read from Claude. Those figures now stay shown until new ones come.
- **Waiting messages show their text everywhere.** A message waiting behind a running turn was shown as
  "+ 1 from another device", without its text, after a reload or once the app came back from the background, even
  when you had typed it yourself. The waiting-messages card now shows every message with its text, wherever it was
  sent from; one from Telegram, a scheduled job or Harness itself says so.
- **Every settings section is reachable on a short window.** On a computer whose window is not very tall, the list of
  settings sections was cut after **Trash**: the last ones could not be seen or clicked. The list now scrolls on its
  own when it does not fit, and the section you open stays in view.
- **Speed and quality lists are readable again on a computer.** Opening the speed or quality picker of a video showed
  a white list where only the highlighted line could be read: the list now uses the theme colors, light or dark.
- **The trash opens again after deleting a file with a long accented or Asian name** (it failed with a server error).
- **Animated PNG pictures get a thumbnail again** in the file grid and the chat.
- **An MCP server whose keys could not be saved is not left half-added**: the addition is undone and says why.

Audit fixes (55: security, bugs, speed, phones and tablets):
- A turn killed because the server ran out of memory now says so again, instead of "server reboot or crash", on
  recent systemd versions.
- When the kernel kills Claude itself for lack of memory, the turn error now says it ran out of memory instead of
  "Claude exited with code -9".
- A shell job that leaves a background program running no longer leaves a defunct `cat` process behind on the server.
- Changing the password now always signs out every other browser, even if the disk fills up during the change (a
  failure used to leave the new password stored while old, possibly stolen, cookies still worked).
- A stray non-ASCII session cookie (for example one set by a sibling subdomain) or setup token no longer breaks the
  sign-in page with an error 500: it is simply refused.
- Signing out and two-step sign-in keep working when secrets.json holds a non-text cookie or device key (restored or
  edited by hand) instead of answering error 500.
- A thumbnail cut short by an ffmpeg timeout or a restart is no longer kept and shown broken forever: it is made again
  on the next request.
- Two requests for the same thumbnail at the same time (chat preloading and the file grid) no longer show a truncated
  image.
- Folders and searches that contain a file whose name is not UTF-8 (a Latin-1 name from a zip or an SMB copy) open
  again instead of failing with error 500; the odd characters show as �.
- The Infra page keeps refreshing when the public RDAP or DNS service sends an unexpected answer (a list, an
  incomplete registrar card, records without data) instead of failing on every refresh.
- A domain whose expiry date could not be read (RDAP service down or busy) is checked again after an hour instead
  of staying blank for a day.
- Files with very long names (240+ bytes) can be deleted to the trash and saved from the editor again, instead of
  failing with a server error.
- Deleted files ending in .json or .sessions now show up in the trash and can be restored, deleted or emptied
  (they used to vanish and never free their space).
- Half-written video copies left behind by a server restart are now cleaned up instead of filling the disk.
- Telegram: a voice note being transcribed (or a big file being downloaded) no longer freezes the bot; commands such
  as /stop in other threads answer right away, and messages of the same session keep their order. If Harness
  restarts while one is being handled, the bot asks you to send it again instead of losing it in silence.
- Telegram: the live "Working…" status no longer lists commands from earlier turns when a session's history is large.
- Telegram: a server restart while several messages were arriving no longer sends the already handled ones to Claude
  a second time.
- Telegram: replies whose bold and italic markers cross (`**a *b** c*`) keep their formatting instead of arriving as
  plain text.
- **Domain expiry lookups cannot hang a refresh.** The public expiry service is read with a size cap, a total time limit and only a few secure redirects.
- **Extensions and packs stay in their folder.** A widget or page file that is a link to a file elsewhere on the server is no longer shown, and installing a pack never writes through a link.
- **A broken extension stays off.** An extension shown in error no longer serves its page or its widget.
- **Thumbnails cannot show a file from elsewhere.** A crafted image or video (a playlist pretending to be a picture) can no longer make a thumbnail or a video preview read a file outside the files folder.
- **Changing the password over SSH cancels pending sign-ins.** `maxxing password`, `maxxing 2fa off` and `maxxing 2fa forget-browsers` now also cancel a two-step sign-in request already allowed in Telegram.
- **Page preview links serve pages only.** A preview link can only be made for an HTML page, and never serves a file inside a hidden folder.
- **Opening a trapped archive no longer stalls the server.** Listing an archive stops after a fixed amount of work and says the list is incomplete, even for an archive built to unpack to gigabytes.
- **Odd characters sent to the Telegram bot are refused cleanly.** While the bot waits for its link, a message with accented or other special characters from someone else gets the usual refusal instead of an error.
- **The Telegram bridge rests when nothing happens.** It no longer re-checks its threads every few seconds on an idle server.
- **Signing out or changing the password never freezes the interface.** These actions no longer make the rest of the app wait while secrets are written.
- **Settings → Stats opens faster.** Statistics no longer re-read every session from disk each time.
- **Dashboard widgets load lighter.** The shared style sheet of extensions is kept in memory and only re-downloaded when it changes.
- **Many open conversations cost less.** A conversation where Claude is working silently is checked a little less often; new messages still show up at once while it writes.
- **`maxxing doctor` is faster.** It no longer re-reads every installed tool from scratch on each run.
- **Phones use less data.** The plan usage bars of the sidebar (not shown on a phone) are no longer refreshed there every minute.
- **A server command with an unclosed quote is refused with a clear message.** Adding an MCP server whose command or arguments had an unbalanced quote failed with a generic server error.
- **A failed MCP server addition no longer leaves your keys visible to every session.** When Claude Code refused the new server, the keys it referenced stayed shared with all sessions; they are now hidden again.
- **A crafted file can no longer stall the memory backup.** A long run of "password:" labels made the secret scanner take minutes, holding the backup for as long; it now scans such a file in a split second.
- **Changing the backup repository or turning the backup off no longer breaks a backup in progress.** Both now wait until the running backup or restore ends ("try again in a minute") instead of deleting its working copy.
- **The MCP page opens faster on long-used servers.** Claude Code's settings file grows with every folder it has
  opened; it is now read again only when it changes, not on each refresh of the page.
- **Buttons that appear on mouse hover now show on touch tablets.** Message actions, the feed and session menus,
  the task selection circle and menus, the copy button of the info panel and diagram tools were invisible between
  768 and 1023 px on a touch screen (iPad portrait); they are always shown on touch screens now.
- **Tables in extension pages no longer overflow on phones.** A wide `ui-table` scrolls sideways instead of pushing
  the page; extensions can also wrap any table in `ui-table-wrap` to get that on every screen.
- **Long repository paths wrap on the Git page**, and the name/value fields of an MCP server get their own full-width
  line on small phones (under 400 px) instead of two cramped fields.
- **A long file name no longer hides the size and the ⋯ menu in the file list.** The name is shortened with "…" and
  the list stays the width of the screen (phones, tablets and computers).
- **The Copy button of code blocks shows on touch tablets** and is larger to tap (36 px).
- **Bigger buttons in the file viewer on phones and touch tablets.** Preview/Edit, Reload, Open in a new tab, the PDF
  buttons, the filter fields and the path "…" button were 28 px high; they are now at least 36 px on touch screens.
- **Buttons are easier to tap on touch tablets** (MCP, Backup and every settings page): they take the same 40-44 px
  height as on phones instead of 32-36 px.
- **Commits of the Git graph are easier to tap** on phones and touch tablets: each row is 40 px high instead of 30.
- **Branch labels of the Git graph stay readable on a phone**: when a commit carries several long branch names, each
  keeps its first characters instead of shrinking to its icon.
- **The MCP page hides short secrets in a server's command line too.** `--api-key=…`, `--token …`, a header such as
  `Authorization: Bearer …` and a key in the server address are now masked, whatever their length.
- **The memory backup no longer saves an MCP server's passwords.** A login written in an address
  (`DATABASE_URL=postgres://user:password@…`) or a short secret passed as `--token=…` is left out of the backup,
  like the other secrets; enter it again after a restore.
- **Adding an MCP server no longer shows its key to other users of the machine.** The key written in clear is no
  longer passed on the command line (visible in the process list) while the server is added or restored.
- **A restore on a server in use only writes what the backup is meant to hold.** Files outside your backup list
  (a `.mcp.json`, a script) are kept aside until you turn the restored items on, and the settings that run a command
  (status line, key helper, environment, project MCP servers) are held like hooks.
- **The backup's secret scanner knows more formats.** PGP private keys, `"password": "…"` in JSON, npm, Hugging Face
  and SendGrid tokens, passwords in addresses (`postgres://user:password@host`) and files saved in UTF-16 now stop
  the backup before anything is pushed.
- **The app opens faster.** It now downloads only the texts of the pages it shows: opening the dashboard or a
  conversation fetches about half as much text as before (the texts of the settings, tasks, servers and other pages
  come with those pages).
- The Git page shows an empty repository (or one whose current branch has no commit yet) instead of a cryptic git
  error.
- On the Git page, opening an id that is not a commit (a folder or file id) says "no such commit" instead of showing
  an empty, garbled commit.
- The Stats page no longer stays empty when one session holds a garbled number (hand edit, another tool): that
  value counts as zero.
- The plan usage bars no longer fail with an error when the usage service sends an invalid number.
- Refreshing the plan usage from several tabs at once makes a single request to Anthropic, so it is less likely to
  be put on hold for an hour.
- The "connection restored" pill no longer stays on screen when the connection blips again right after a restart.
- Tasks: on a touch screen the round selection buttons of the list and board (tasks, groups, columns) have a full
  finger-sized hit area and no longer overlap the done box.
- Tasks: on a touch screen the ⋯ buttons of cards and projects, the view switch and the project chips are
  finger-sized (the projects' ⋯ button also shows without hovering on a touch tablet).
- Tasks: on a phone, a gear chip at the end of the project chips opens Projects (it used to be reachable only from
  inside a task).
- Tasks: on a phone narrower than 400 px the view buttons move under the header, so the page title is no longer cut
  to "Tas…".
- Settings → Updates: the "Show me" links of the release notes are buttons that show the feature, as in What's new
  (they did nothing there), and they are finger-sized on touch screens in both places.

## 2.0.0-alpha.71 - 2026-10-19

Tasks, project by project:
- **Every workspace project now has its tasks.** The Tasks page gets a column of projects on the left (a row of
  chips on a phone): each project of Sessions appears there by itself, follows it when you rename it, and keeps its
  tasks in a free project if you delete it. Free projects (Personal, Admin...) and tasks without a project still
  work. Hide a project you do not use for tasks with its menu; the `system` project starts hidden.
  [Show me](#show:tasks)
- **Overview**: one card per project with its open tasks, progress, overdue and urgent tasks and next due date, the
  projects that need attention first. A project's header shows its progress and opens it in Sessions.
- **New views**: **Week** (overdue, today, the next six days: drag a task onto a day to set its due date),
  **Calendar** (the month, tasks on their due date) and **List by topic** inside a project. In All tasks, the board
  can show **one row per project**.
- Claude knows it too: "add a task to the blog project", "what is due this week in acme?".

## 2.0.0-alpha.70 - 2026-10-19

**IMPORTANT - security fixes and a clean, managed installation.** This release closes the issues of two external
audits (the server and a fresh install on Ubuntu) and of our own installer reviews. Update now (`maxxing update`);
nothing else to do, see the notes below for the few behavior changes.

Security:
- **Oversized requests are refused before they are read.** A browser that is not signed in can no longer send the
  server a huge request to fill its memory: it is turned away at once (the sign-in form itself takes at most 64 kB).
  Signed-in requests are capped too (1 MB, more for the file editor, messages to Claude and uploads). Live views
  (open conversations, dashboard updates) are capped as well: 24 per browser, 96 in total; past that a view simply
  retries a few seconds later. The web server also gets its own memory limit, so it cannot take the whole server
  down.
- **Signing out ends everything that sign-in opened.** Preview links stop working when you sign out (one browser or
  all of them), and the live views already open in a signed-out browser stop within 15 seconds.
- **HTML previews load only what a web page needs.** A page opened in the preview still loads its styles, scripts,
  pictures, fonts, audio and video, but no longer the notes, data or documents next to it (`.json`, `.csv`, `.txt`,
  `.md`, `.pdf`, `.xml`...). Put the data inside the page or in a `.js` file instead.
- **A restore can no longer run code before you said yes.** Extensions whose code a restore writes are turned off
  before the first file is written. A memory restore during the installation keeps jobs, extensions, Claude Code
  hooks, local MCP servers and saved customizations off until you explicitly turn them on.
- **The first sign-in link expires after one hour** and is no longer written to the system journal (run
  `maxxing setup-link` for a fresh one).
- **No going back to an old version with known holes:** the installer refuses a release older than this one, and
  `maxxing update` refuses a downgrade unless you ask for it (`--allow-downgrade`). Licenses are bound to the server
  they were activated on.
- **Scheduled jobs can no longer take the server down.** A job started by its schedule runs like "Run now": in its own
  unit, capped in memory, all jobs together sharing one memory budget (75 % of the RAM by default,
  `jobs_memory_max`). Past its timeout a job is stopped, then everything it started is killed 5 seconds later.
  On new installations, programs a job leaves running in the background end with it; existing installations keep
  their jobs running as before (`cron_keep_background`, see the Crons page).
- **Sessions and jobs of new installations get extra systemd protections** (`unit_hardening`, off on existing ones)
  that do not get in the way of administering the server (they
  cannot change the clock, the process personality or use realtime scheduling). They still run as root: running them
  as a dedicated user is a separate project.
- **Infra checks of your sites are light and bounded** (headers only, given up after 10 seconds), and **Garage (S3
  storage) is installed only if its download is the genuine one.**
- **Python 3.11 or newer is required** (the standard install uses 3.12); the doctor flags an older Python.

Installation:
- **No more `curl | sh`.** Every third-party program (uv, Python, Node.js, Claude Code, Caddy's key, Scrapling and its
  packages, the browser, Remotion, the voice models, Garage) has a pinned version and checksum in one list,
  `deps.toml`, shipped with each release. A download that does not match installs nothing. Claude Code comes from its
  pinned, checked build instead of a script fetched at install time (it keeps updating itself afterwards).
- **New `maxxing deps`** to see and manage these components: `list` (installed and expected versions), `verify`
  (checksums, and files that another user could replace), `update`, `remove <name>`, `clean` (caches, old
  versions, leftovers, oversized logs) and `check` (known vulnerabilities, from osv.dev). The doctor reports them.
- **Dependencies update themselves with Harness Maxxing:** each `maxxing update` moves them to the versions of the
  new release, installed next to the old ones and switched only once they work. Every week a job cleans old
  versions and leftovers, and another checks for known vulnerabilities and tells you (notifications, Telegram) -
  both created turned off on existing installations (Crons page). Your own tools stay yours: a `node` or a `uv` the
  server already had is neither replaced nor shadowed, the shared caches of uv / npm / pip are only emptied on request
  (`maxxing deps clean --caches`), and a working server Python is not moved during an update.
- **The system cleans up after itself:** nothing is left in `/tmp`, archives are not kept, and
  `maxxing uninstall --purge` removes everything the installer put on the server.
- **One browser instead of two:** Scrapling, video rendering and PDFs share the same Chromium (about 250 MB less).
- **Faster:** a fresh install has the web UI ready in about a minute; the heavy tools (browser, video, voice model)
  finish in the background (`maxxing deps list` shows them). A re-run only redoes what changed (about 10 seconds).
- **Install from a local copy of the code**, without a license or a download: `bash ./install.sh` in an unpacked
  archive (or `SOURCE_DIR=...`). Such an install says "updates unavailable" instead of failing every week.
- **Small servers:** on a fresh server, a 2 GB swap file is added under 4 GB of memory when there is none (`SWAP=0`
  to skip, `SWAP=1` to add it on a server already in use), and
  local voice transcription is off by default under 3 GB (asked if you set `VOICE=local`). The doctor warns under 4 GB
  without swap.
- More reliable on Ubuntu 22.04, 24.04, 26.04 and Debian 12: the packages the installer needs (python3, gnupg,
  openssh-client, python3-systemd) are installed in one pass, Ubuntu's universe component is turned on if an image
  shipped without it, and Python lives with Harness Maxxing's other files instead of `~/.local`.
- **SSH password logins are turned off - only when it cannot lock you out** (this session is proven to use a key;
  an interactive install asks first; `SSH_HARDEN=0` never touches SSH). fail2ban watches the ports SSH really
  listens on, and on a fresh server a protection the installer turns on that does not work stops the installation
  (`ALLOW_UNPROTECTED=1` to go on anyway; a re-run or a server already in use only warns). The SSH tunnel command shown at the end uses your real user, address
  and port.
- No failing job right after the install: "Memory compaction" starts once Claude is signed in at the end of the
  onboarding. Shipped skills name the real folders of your install.

Behavior changes to know: an HTML preview that loaded `.json` / `.csv` / `.md` files next to it no longer gets them;
open preview links must be reopened once; scripts posting more than 1 MB of JSON to a core route get "too large".

## 2.0.0-alpha.69 - 2026-10-18

- `maxxing update --branch <name>`: when the new branch does not start, the automatic rollback now really goes back
  to the branch and version that were running (it used to stay on the new, broken code), without rewriting the
  branch it had switched to.
- `maxxing update --rollback` after a `--branch` switch goes back to the branch that ran before, and no longer wipes
  changes you have not saved yet in the code directory: it stops, changes nothing and tells you how to put them
  aside and back.
- When an update stops on a conflict or is rolled back, the edits of the web UI it had set aside are put back in
  place, as "nothing changed" promises, and so are the unsaved changes it had saved after a `--branch` switch.
- A cleaner look where it stood out from the rest of the app: the **Make it yours** and **Activity** cards of the
  dashboard, the **Your pages** page and the starter projects (Settings -> Starter pack and the setup) now use the
  app's icons and cards instead of emoji.
- **Your pages and widgets look like the app**: the pages and HTML widgets Claude builds for you now get the app's
  own components (cards, buttons, fields, badges, tables, figures, icons), so they follow your theme, your accent color
  and the density, in dark and light, without extra work. Dashboard cards can show an icon in their lists too.
- Sessions: your pseudo no longer shows under each of your messages (it is still used when your web messages are
  copied to Telegram).

## 2.0.0-alpha.68 - 2026-10-18

- **Stop** and steering no longer get lost when you press them just as a turn starts: the turn now stops (or takes
  your message) instead of running to its end.
- Stop never signals a process that is not the session's: when a session's worker had died (out of memory, killed),
  Stop could hit an unrelated program that reused its number.
- **Hand off**: a message you type in the new session right away now waits for the summary of the old one and runs
  with it - it used to run first, in an empty conversation, and Claude did not know what you were talking about.
- Compact when you come back: **Stop** during the summary now cancels only the summary - the message you just
  sent stays and runs right after (it used to vanish). A session whose context is mostly what every new thread
  loads anyway (CLAUDE.md, memory) is no longer summarized: it would save nothing.
- A side question whose session you delete while Claude answers no longer shows an error.
- A turn that ends while Harness restarts (during an update, for instance) is no longer forgotten: its Telegram
  reply and its notification are sent once the server is back.
- Automatic Claude Code updates: a message sent while Claude Code is being updated now says so in the conversation
  ("Claude Code is being updated: this turn starts as soon as it is done") instead of looking stuck; it never waits
  more than 7 minutes.
- Only the installed server updates Claude Code: a second Harness Maxxing started on the same machine (development,
  tests) never updates the machine's Claude Code on its own.
- Git page, a repository with many branches stays readable: the lines of the graph squeeze on a narrow screen, each
  commit's text starts right after the lines of its own row, long branch names end with "…" (full name on hover)
  and never hide the commit message. On a phone or a tablet, a commit opens in a sheet from the bottom instead of
  under the whole graph; the filter and the refresh button share one line.
- Fixed: deleting the workspace folder from the Files page (with the default files root it is just one folder
  among others) sent your whole workspace - every project, topic and memory - to the trash. The workspace and the
  folders that hold it can no longer be moved or deleted there.
- Fixed: the Files page could move or delete a topic folder while one of its sessions was running; like the
  sidebar, it now asks you to stop the session first.
- Fixed: a few unusual paths (an invisible control character, a broken link, a file where a folder was expected)
  gave a server error instead of a clear message.
- Fixed: when Claude changed your tasks while you were editing one on the Tasks page, saving could erase
  Claude's change. Both are now kept: your edit is applied on top of the file as Claude left it.
- Fixed: a task written by hand with an unexpected field (notes as a list, a number as a title) stopped the search
  from finding anything new - files, memories or tasks - until the task was fixed. Such fields are now read as
  text.
- Fixed: an import could set a topic's permission mode (for example "bypass permissions") or the order of your
  projects through the folder settings files of the export. These files are now refused, like Claude Code
  settings already were.
- Fixed: an import could write outside your workspace by following a link already in a topic (a link to a
  repository, say). Such files are now skipped.
- Fixed: an import whose file landed where a folder already was (or the other way round) stopped half-way with a
  server error. That file is now skipped and listed in the report; the rest is imported.
- Fixed: restoring a project or topic with a very long name (48 characters) next to a new one of the same name
  brought it back under a name that was too long, so it did not show in the sidebar. The restored name is now
  shortened to make room for "-restored".
- A shell job that prints a lot (logs, a download progress bar) no longer writes its whole output to a temporary
  file first: only the end of the output is kept, as shown in the history, so a chatty job can no longer fill the
  server's memory or `/tmp`. A program the job leaves running in the background (`nohup app &`) keeps running.
- If the closing line of the Harness block in the crontab was deleted by hand, saving or syncing jobs no longer
  removes your own crontab lines that came after it.
- Notifications from Shopify and GitHub: someone who captured one signed delivery can no longer make it appear again
  and again by resending it with a new delivery number - a replayed event is recognized as a duplicate.
- Two copies of the same event arriving at the same moment (a service retrying) no longer make the second one fail
  with a server error: it is simply counted as a duplicate.
- Telegram: when the bot could not delete the thread of an archived session (Telegram asked to slow down, the
  connection dropped, missing rights), the thread stayed in the chat forever. It is now retried at the next sync.
- Telegram: a long notification whose text contains `&`, `<` or `>` near its 700th character could be refused by
  Telegram (a symbol cut in half). Notifications are now always cut cleanly.

## 2.0.0-alpha.67 - 2026-10-18

- **Edit a stopped message**: stopped Claude too early? Click the pencil under your message (or right click / long
  press -> Edit): its text, quotes and attachments come back in the message box, ready to fix and send again.
- **New session from a message**: right click any message - yours or a reply (long press on a phone) - then *New
  session from this message*: a new session of the same topic opens with it already typed.
  [Show me](#show:msg-actions)
- Instant queue: **Edit** on the waiting messages puts them back in the message box at once, and the **×** that
  empties the queue acts at once too. Many attachments sit in a small strip of two rows that scrolls.
- **Short session titles**: a new session is named in a few words from its first message (greetings and "can
  you…" removed) instead of its first 60 characters, for sessions started from Telegram too; a title you typed or
  a rename is never replaced. Settings -> Claude can also let Claude write them, naming the subject (one quick call
  to the smallest model per new session, counted in your Claude plan: off by default).
- Coming back to a very long session after a break is cheaper: Claude's cache only lasts a few minutes (up to an
  hour), so when you write to a session idle for more than an hour with a big context (200k tokens by default),
  Harness first summarizes it and your message continues in a fresh thread from the summary. Threshold or Off in
  Settings -> Claude. [Show me](#show:idle-compact)
- New switch **Update Claude Code automatically** (Settings -> Claude, off by default): the server then installs
  Claude Code's stable release by itself when nothing has run for 10 minutes - never during a conversation, a
  queued message or a scheduled job - and goes back to the previous version if the new one does not start.
  [Show me](#show:claude-auto-update)
- **A command that runs out of memory no longer kills the session**: a heavy render or build that fills the RAM is
  stopped alone, Claude sees it and can try a lighter way. Each session and scheduled job may use at most 75 % of
  the RAM (`unit_memory_max` in config.json). The video skill explains how to assemble long edits with ffmpeg
  without filling the memory.
- Previews follow the files: when Claude rewrites an image or a video under the same name, its thumbnail, the HUD
  and the viewer show the new version. Media player: the speed and quality buttons open your device's own list
  (never cut off on a phone, works in full screen); video quality **Auto** prepares its lighter copy once you press
  play (or right away when the browser cannot read the original, like iPhone HEVC videos).
- A part that fails to display (a widget, a message, the file viewer, the HUD) shows a small "could not be
  displayed" line instead of taking down the whole page. A tab left open across an update reloads itself once.
  The app opens even when the browser blocks site storage. Huge diffs and texts no longer freeze the page.
- Sturdier server: an extension that hangs or quits while loading no longer keeps Harness from starting, one that
  never answers no longer freezes the app, and many widgets at once wait their turn. A turn always ends, even when
  a program Claude started in the background keeps running. Search, Telegram and turn-end notices survive an
  error; settings, secrets and scheduled jobs are written safely (power cut, two programs at once).
- Lighter server while Claude works (live checks, model list, the first screen after a pause).
- Safety of the Git page: a repository on the server can no longer make git run a program while the page reads it,
  and GitHub's rate limit or an odd answer no longer breaks the page. Each repository is listed once: the extra
  working folders of a clone (`git worktree add`) are counted on it; a card names its branch only when it is not
  `main`/`master`.
- Safety of the Infra page: a server written by hand into `infra.json` can no longer run a command through ssh
  options (it is ignored, and kept in the file to fix); an app published on a path of your Harness address never
  receives your Harness cookies nor sets them (its own cookies and logins still work); published folders never
  serve hidden files and system folders cannot be published. One provider's outage no longer stops the refresh.
- HTML page previews serve only the page and what it loads - never `memory.md`, `CLAUDE.md`, code or settings next
  to it - and end when you sign out. *Ask Harness* on a notification opens the session in plan mode: Claude changes
  nothing until you approve a plan, whatever the webhook's text says.
- Restoring a backup on a server already in use brings its scheduled jobs and extension code back turned off,
  keeps local MCP servers and Claude Code hooks aside, and says so in a notification; on a new server (a move)
  everything comes back as before.
- Two-step sign-in is harder to get around: someone who knows your password can no longer try Telegram codes
  from many addresses (codes pause for an hour after 20 wrong ones on the server - the Allow button still works),
  can no longer fill the waiting list to keep you out, and an Allow pressed by mistake no longer lets them in once
  you changed the password.
- **Settings -> MCP** hides more secrets: a header or environment value written in clear, a password or the query
  values of an address show as `•••` (values that look like secrets are also left out of the memory backup).
  **Connect** never leaves a Claude Code process behind, and a broken MCP settings file no longer stops the page.
- Smaller fixes: webhook signatures with odd characters, notification links, the Infra page with an endless
  hosting answer or a mistyped international domain, the thumbnail cache stays under
  512 MB, video copies in line, `maxxing doctor`'s Caddy fix keeps a copy and puts it back if the new
  configuration is refused.

## 2.0.0-alpha.66 - 2026-10-18

- Smoother on a phone, above all as an installed app: panels that slide up from the bottom (menu, task, forms,
  confirmations) close with a **swipe down** and slide away instead of vanishing; in a session, a **swipe from
  the left edge** goes back to the list. The bottom bar is slimmer ("Home" instead of a cut-off "Dashboard"),
  steps aside while you type, and no longer stays a few pixels too high after the keyboard closes or when you come
  back to the app (iPhone). Forms in a panel stay above the keyboard.
- On a phone, the menu (logo at the top left) now opens the pages that have no room in the bottom bar: Git, Infra,
  Extensions and your pinned pages (Git and Infra when they are turned on).

## 2.0.0-alpha.65 - 2026-10-18

- On new installations the **Git & GitHub** page is off by default, like the Infra page: turn it on in
  Settings -> Features. Nothing changes on a server where it is already set up; the git graphs in conversations
  work either way.

## 2.0.0-alpha.64 - 2026-10-18

- New **Settings -> MCP**: every MCP server Claude uses (Google Ads, Notion, a database...) in one list, with where
  it applies - every session or one topic, with a link to it - and its state: connected, to connect, error.
  **Add a server** by its address or command, for every session or one topic, with its keys taken from
  Settings -> Keys; **Connect** signs in to services that need it, right from the browser; **Remove**. Claude can
  do the same when you ask it in a topic (`maxxing mcp`). Servers follow a renamed topic and are kept in the
  memory backup. [Show me](#show:mcp)

## 2.0.0-alpha.63 - 2026-10-18

- How much of your Claude plan is used, always in view: two small bars at the bottom of the sidebar, under the
  health indicator - the current 5-hour window and the week, in % used as on claude.ai (orange from 70 %, red from
  90 %). Hover them for the reset times. The figures come with every Claude answer, so nothing extra is asked of
  Anthropic; usage elsewhere (claude.ai, another computer) shows up at the next answer. Hidden with an API key.
- Fixed: the plan usage in Settings -> Stats could fail to show its reset times.

## 2.0.0-alpha.62 - 2026-10-18

- Infra reads your domains wherever they are, without any key: for every domain, its registrar, its expiry date,
  who serves its DNS (OVH, GoDaddy, Namecheap, IONOS, o2switch, Gandi...) and who hosts its address (one of your
  servers, Vercel, Netlify, GitHub Pages, Shopify, Cloudflare...). **Domains -> Add a domain** watches any other
  domain you own, with the same expiry alerts. [Show me](#show:infra-domains)
- New providers on the Infra page, in beta: **Vercel** (projects, deployments, domains), **Netlify** (sites,
  deployments, DNS), **Supabase** (each project's database, Storage buckets and Edge Functions) and **GitHub Pages**
  (with the GitHub keys you already have). Add their key in Settings -> Keys; the page links to where each token is
  created.
- Fixed: a domain whose DNS zone exists at Hostinger but whose name servers point elsewhere showed the wrong DNS
  provider; the public name servers now decide. The Infra page links to its documentation, which lists every
  supported provider and what to do when yours is not there.

## 2.0.0-alpha.61 - 2026-10-18

- Two-step sign-in with Telegram (Settings -> Security or Settings -> Telegram): after the password, a new browser
  waits for your approval - an **Allow** / **Deny** message in the Alerts thread of your bot, with the IP, the
  browser and a code to type if the buttons do not answer. Trusted browsers skip it for 30 days. Telegram does
  not answer? On the server, `maxxing 2fa off` turns it off. [Show me](#show:twofa)
- Fixed: cards in two-column lists (Git repositories, Infra) left uneven gaps when their contents differed.

## 2.0.0-alpha.60 - 2026-10-18

- Infra: your other servers connect from the page. A Hostinger VPS that already accepts a key of this server is
  connected by itself; otherwise one click on **Connect** adds Harness's key to the VPS through your Hostinger key,
  and its sites and databases appear. Any other server: **Add a server** (if no key works, the window gives the one
  line to run there). A Hostinger VPS is named "VPS Hostinger"; rename or disconnect any server from its panel.
  [Show me](#show:infra-servers)
- The Infra page explains itself: a "How it works" box, and **What Harness reads** lists each source with the next
  step when something is missing (a key, a right of the Cloudflare token, a VPS to connect). The Servers tab shows
  one card per server with memory, disk and CPU in use and what runs on it. The page fits a phone screen.

## 2.0.0-alpha.59 - 2026-10-18

- New optional **Infra** page (Settings -> Features, off by default): every site, database, bucket, domain and
  server you have - on this server, on your other servers (over SSH), on Cloudflare (Workers, Pages, R2, D1, DNS) and
  on Hostinger (domains, VPS) - with its status, its links (domain -> server -> site -> app -> repository) and the
  project it belongs to. Addresses and certificates are checked every 15 minutes; a site going down, a certificate or
  a domain about to expire shows up in your notifications. [Show me](#show:infra)
- Ask Claude "put this folder online", "create a database for my app", "create a bucket", "add my other server": it
  now follows one standard recipe (command `maxxing infra`). A small site goes online at once at
  `https://<your address>/<name>/`, isolated from Harness; a database is backed up every night; passwords go to Keys.
- Conversations show sites, databases and domains live when Claude talks about them (with the Infra page on).

## 2.0.0-alpha.58 - 2026-10-18

- Git page: every GitHub token of your keys is used, whatever its name, so the repositories of every connected
  account show (and of tokens limited to a few repositories). The connected accounts are listed at the top (click
  one to filter), each repository shows which keys see it, and a key GitHub refuses is pointed out without hiding
  the others.

## 2.0.0-alpha.57 - 2026-10-18

- Git & GitHub is now a regular page: **Git** in the sidebar (shortcut G then B), on by default, to hide in
  Settings -> Features. It no longer goes through the Extensions page, which is back to your own extensions only.

## 2.0.0-alpha.56 - 2026-10-18

- Git as pictures: when Claude talks about a repository (branches, commits, what is not pushed), the conversation
  shows the real graph of that repository, read live; click a commit to see the files it changed.
  [Show me](#show:git)
- New optional extension **Git & GitHub** (Extensions -> Added extensions -> Add): every repository of the server
  and of your GitHub account, with your rights on each; click one to see all its branches and commits as a graph,
  the details of each commit and the open pull requests. Read-only. GitHub needs a `GITHUB_TOKEN` key.
- Ready-made extensions are now simply part of the app: **Add** shows one, **Remove** hides it, and they are
  updated with Harness Maxxing (nothing is copied into your workspace any more).
- Fixed: turning an extension on or off showed no message when it failed.

## 2.0.0-alpha.55 - 2026-10-18

- The Extensions page has two parts: **Your pages** (the ones Claude made for you in your conversations, with a
  button to ask for a new one) and **Added extensions**: ready-made extensions shipped with Harness Maxxing, added
  in one click, updated when a new version comes, removed to the trash. The first ones arrive with the next
  updates. From the server: `maxxing extensions list|add|update|remove`.

## 2.0.0-alpha.54 - 2026-10-18

- Sidebar: pinned extension pages are aligned with the other entries, with their icon at full size.

## 2.0.0-alpha.53 - 2026-10-18

- Connexxion is removed: it was a test build, released by mistake in alpha.50. It no longer appears in the
  sidebar or in Settings, and the public `/api/peer/v1/*` address is gone. Your pseudo (Settings → Profile) stays.

## 2.0.0-alpha.52 - 2026-10-18

- Extension pages: a pin button at the top of each page adds it to the sidebar, right below
  Extensions (click again to unpin). The Extensions entry now stays visible even when every page is pinned.

## 2.0.0-alpha.51 - 2026-10-17

- Scheduled jobs: a shell job can call `claude -p` - it runs with the same Claude account and Claude Code
  folder as your sessions (before, a script calling Claude had no credentials).

## 2.0.0-alpha.50 - 2026-10-17

- Connexxion: what another server writes can no longer make Claude change a topic's Claude settings, MCP
  servers, CLAUDE.md or memory.md.

- **Connexxion**: connect your Harness Maxxing with someone else's. One of you invites (a one-time code
  `XXXX-XXXX-XXXX-XXXX` and this server's address), the other joins, the first accepts, and you both compare a
  fingerprint. Then you discuss in one thread, with proposals the other accepts or refuses, typing and online
  indicators. Turn it on in Settings → Connexxion.
- **Agree, then let the agents work**: the AI condenses the discussion or drafts a plan with tasks for each side;
  any edit makes a new version and both of you must accept the same one. Either of you can refuse or stop at any
  step.
- **Whose quota**: run the agreed plan on your Claude quota, on theirs (they accept first), or shared - two
  agents, one per server, split the tasks and coordinate with each other. Daily budgets per connection, usage of
  each side, a log of everything. No Claude token ever leaves a server, and the other side's messages are never
  instructions for your AI.
- Also in Connexxion: send files (accepted first, checked by hash), share a skill or an extension (you read every
  file before installing; extensions arrive disabled), hand over a session, groups of several connections,
  read-only observers, pause, cut, and connections closed by themselves after 60 idle days.
- Narrow conversation columns: the message box no longer squeezes when a model switch is pending and plan mode is
  on - it shows only the next model and the plan icon (the full labels come back when there is room).
- **Your pseudo**: Settings → Profile - a name, a color and an emoji shown on your messages instead of "You", in
  Connexxion and in Telegram mirrors.

## 2.0.0-alpha.49 - 2026-10-17

- **Video quality**: big videos (1440p screen recordings, AV1 rushes, heavy exports) start fast. The player has
  a quality button - Auto, Original, 1080p, 720p, 480p. The server makes the lighter copy once, the video keeps
  playing meanwhile and switches at the same moment when it is ready. Auto plays a 720p copy only when the
  original is heavy. [Show me](#show:video-quality)
- **Faster playback**: the speed button of the video and audio player now opens a list from 0.5× to 4×, and the
  < / > keys go one step slower or faster.
- **Download is instant** for pictures and PDFs you are looking at (viewer, Files, previews): the file already
  shown is saved straight away instead of being downloaded a second time. Videos and other files still use the
  browser's own download, with its progress.
- **Right click on a picture, a video or a file in a conversation** (long press on Android): Open, Download, Quote,
  Copy path. Quote adds the file to your next message as one short line (its path, shown with a thumbnail):
  Claude opens the file only if it needs to, so a picture does not fill the conversation's context.
  [Show me](#show:file-menu)

## 2.0.0-alpha.48 - 2026-10-17

**Costs and tokens**
- Claude starts faster and sends a shorter prompt: its update check, telemetry and feature-flag download are skipped
  when a turn starts (0.87 -> 0.52 s to the first event, about 900 fewer tokens on every call). The one-hour prompt
  cache of subscriptions is unchanged.
- `maxxing sessions token-report`: where the tokens of your sessions go (context size per call, cache rewritten
  after an idle hour, the tools whose outputs fill the context) and what each compaction threshold would have saved.
  On this server: compacting at 400k saves 43 % of the re-read context, 45 % when long turns are compacted too, 56 %
  at 300k.
- Switching the model of a session with a big context asks first: the new model re-reads the whole conversation
  without cache once (on one server: 2 switches = 1 million tokens rewritten).
- Automatic compaction also works inside one long turn (many tool calls in a row), near the same threshold, instead
  of letting that turn grow up to the model's limit.

**Speed**
- Replies show up sooner: while Claude works, new messages and tool rows appear about 70 ms after Claude writes
  them (117 ms before), and the end of a turn - the Telegram reply, the notification, a scheduled job's result - is
  picked up in 0.14 s instead of 0.57 s (median, measured).
- Settings -> Stats shows how fast turns start (Claude ready, first answer). Without a proxy in front (Tailscale or
  local access) the app page is sent compressed. `maxxing doctor` warns about a small server without swap.
- The first page is about 9 % lighter (226 -> 205 kB compressed): the English texts are no longer downloaded by
  an interface shown in French.

**Look**
- The sign-in page takes your colors: the theme, accent and background you last picked are kept by the server, so
  the sign-in page and a browser that never chose one (new phone, private window) show them instead of the default
  dark blue. [Show me](#show:look)

**Conversations**
- A diagram opens like a picture: click it and it fills the file viewer (zoom, fullscreen, drag to move, ← / → with
  the other files of the conversation, its code under **Source**). [Show me](#show:diagram)
- Audio files named in an answer, or sent as an attachment, get a small player right in the conversation.
- Messages no longer show a copy button on hover (select the text to copy it; code blocks and diagrams keep theirs).
- In the file viewer, images and diagrams zoom with the mouse wheel alone, 5 % per notch around the pointer, and a
  zoomed view is moved by dragging it with the hand.
- The **+** key zooms in again in the file viewer (it never did; **=** and **-** worked).

**Security**
- A topic can have its own permission mode (topic menu -> Permissions), and so can a scheduled Claude job: put the
  topics and jobs that read web pages, e-mails or forwarded messages in a stricter mode. [Show me](#show:topic-permissions)
- `maxxing doctor` spots a Caddy site written by an older installer: `X-Frame-Options DENY` (PDF previews in Files
  stayed blank) or a 500 MB body limit (the app allows 2 GB uploads); the fix command reloads Caddy. New installs
  allow 2 GB through Caddy.
- New passwords need at least 12 characters (an existing shorter one keeps working), and wrong current passwords in
  the password-change form are slowed down and blocked like wrong sign-ins.
- Every page now tells the browser that the app, its widgets and the files it shows may not use the camera,
  location, payments or USB devices (Permissions-Policy); the microphone stays allowed for voice messages.
- Files the server keeps in its state folder (settings, sign-in status, notifications, session logs) are readable by
  root only; older ones are fixed at the next start.
- `maxxing doctor` says when Claude Code is behind its latest release (its own auto-update can be off), how big the
  skill list sent with every prompt is, and with `--deps` looks up known vulnerabilities of every installed package
  (osv.dev).
- KaTeX (formulas in diagrams) updated to 0.18 for a published security fix (GHSA-238p-pmpm-9mq7, low severity).
- Video tools install exactly the versions that were checked (a lockfile for Remotion) instead of the newest ones.
- The backup's secret scanner also recognises Stripe keys and webhook secrets, Google API keys, JSON web tokens and
  a password written next to its label (`password: ...`, `mot de passe : ...`), for example in `accounts.md`.
- "Protect the secrets" (Settings -> Claude, on by default): Claude's tools refuse to read or edit the server's
  secrets and the SSH keys, whatever the permission mode.

## 2.0.0-alpha.47 - 2026-10-17

- **`maxxing keys`**: list, read, create or update the keys of Settings -> Keys from the command line. A
  script that renews a token (a 24-hour shop token, a webhook secret it just created) saves it with
  `printf %s "$TOKEN" | maxxing keys set NAME`; scripts read keys as environment variables.

## 2.0.0-alpha.46 - 2026-10-17

- **Search (Ctrl+K) in big workspaces**: every `memory.md` and `CLAUDE.md` is always found - one big project
  full of files used to take all the room, and the other projects had nothing in the search. Each topic now gets
  its fair share of the other files; data files (.json, .csv, .xml, .svg) are left out.
- Lighter on the server: the files are walked every 10 minutes instead of every 30 seconds, and the walk stops
  at its limit. The search index shrinks at the update (on a large server: 448 MB -> 58 MB).

## 2.0.0-alpha.45 - 2026-10-17

- Installer: when Claude Code is already used on the server, it asks whether Harness Maxxing gets **its own
  Claude Code folder** (recommended - your setup is not touched) or shares the existing one. Fresh servers get no
  extra question, and re-running the installer keeps the first choice.

## 2.0.0-alpha.44 - 2026-10-17

- **Install next to a Claude Code you already use**: `CLAUDE_DIR=/root/.claude-harness` before `bash` gives
  Harness Maxxing its own Claude Code folder (skills, global instructions, conversations, sign-in). Your
  `~/.claude` stays as it is, and you bring skills over when you need them. Also `maxxing init --claude-dir`.

## 2.0.0-alpha.43 - 2026-10-17

- **Settings -> Updates**: every version of Harness Maxxing, newest first, with a search (it replaces the
  "All updates" page of the docs). "What's new" links to it.

## 2.0.0-alpha.42 - 2026-10-17

- **Drag a session to another topic** in the session list: drop it on a topic, or on any session of that
  topic. Same as "Move to another topic" (its history moves with it). Sessions that are working cannot move
  until they finish.

## 2.0.0-alpha.41 - 2026-10-17

- Sessions: a sideways trackpad swipe really scrolls the columns now, wherever the pointer is - the columns'
  snapping used to pull each small move straight back.

## 2.0.0-alpha.40 - 2026-10-17

- Docs: new page **All updates** (Settings -> Docs, and the member area) - every version, newest first. It is
  this changelog itself, so it is always complete.

## 2.0.0-alpha.39 - 2026-10-17

- **Smart updates.** Settings -> System now shows what the next update does to *your* server before you
  click - tested on a throw-away copy, nothing changed: each of your code changes carries over, is now
  included in the product, or must be adapted; edits of the interface files and extensions the new version
  no longer supports are listed too.
  - All compatible: **Update** does it all, then your extensions and changes are checked automatically and
    Harness applies the version's workspace novelties in a session.
  - Something to adapt: **Update with Harness** opens a session that adapts each change from what it is
    for, tests, then updates. Your current version keeps running until everything works.
  - After an update: "your extensions and changes work", or what stopped working with **Fix with Harness**.
- Customizations can carry a check (`maxxing custom save ... --check "<command>"`, `maxxing custom check`),
  run after every update. New commands: `maxxing update --preflight` and `maxxing update --verify`.
- Edits of the interface files no longer block an update: they are set aside, and Harness rebuilds them as
  an extension.
- Extensions declare the contract version they use (`"api": 1` in `manifest.json`).

## 2.0.0-alpha.38 - 2026-10-17

- **A clearer dashboard**: a new install shows Activity, Server, Today's schedule, Tasks and **Make it yours** -
  no more cards full of zeros or "Not configured". Before your first session, Activity shows where to start
  (first session, tutorial, starter projects); an empty day shows the next scheduled run. The other cards are
  one click away in **Edit layout** (Shopify shows up by itself once connected).
- **Make it yours** (last card): click an example - Shopify sales, website visitors, Stripe revenue, uptime,
  customer reviews... - and a session opens with the request already typed. Send it: Harness builds the widget.
- **Your pages**: a new page under Extensions explains page extensions (client file, order tracker,
  invoices...) with the same one-click examples. Delete it when you no longer need it.

## 2.0.0-alpha.37 - 2026-10-17

- **Starter pack**: add a pack as many times as you like - each time it is a new project (`ecommerce-2` for a
  second store...), with its own scheduled jobs (disabled).
- **Default projects** card in Settings -> Starter pack: **Put back** re-creates `general/inbox` and the `system`
  topics you deleted, without overwriting anything (`maxxing packs add basics` on the server).

## 2.0.0-alpha.36 - 2026-10-17

- Settings -> System: **Version** (updates) is now the first card.

## 2.0.0-alpha.35 - 2026-10-17

- **Reorder the session tree**: drag a project above or below another, or a topic within its project. The
  order is saved on the server, so it is the same on every device.
- Sessions: a sideways trackpad swipe now scrolls the columns wherever the pointer is (it used to work only
  below them).
- Settings: **System** and **Stats** moved to the top of the list, right after General.

## 2.0.0-alpha.34 - 2026-10-17

- Settings: the starter projects section is now **Starter pack**, at the bottom of the list (before Docs).
- Settings -> Notifications: the "Sources" card no longer sticks to the card above it.

## 2.0.0-alpha.33 - 2026-10-17

- **Starter projects**: ready-made projects for your kind of work - online store (code, orders, ads, social),
  affiliate site (website, blog, affiliation, google), content creator (scripts, video, stats), apps (template,
  hosting, app-1 to app-3), second brain (journal, knowledge, reading, ideas) and freelance business (clients,
  proposals, prospecting, admin). Each topic already knows the job and asks you a few questions at its first
  session; no fake data. Pick them at the first sign-in (install all, choose, or none), any time in
  **Settings -> Starter pack**, by asking in `system/harness`, or with `maxxing packs add`. An existing project is never
  overwritten, and their scheduled jobs are created disabled.
- **A lighter start** (new installs): `general/inbox` for quick questions, tasks and subscriptions, and `system`
  with three topics - `tutorial` (the 4 lessons in one topic, it remembers where you stopped), `help` (the
  product and the server) and `harness` (updates, widgets and extensions, starter projects). Existing servers keep
  their projects and topics as they are.

## 2.0.0-alpha.32 - 2026-10-16

**Costs and tokens**
- **Costs are counted right**: Claude reports a running total for the whole conversation, and it was added on every
  turn, so the cost shown on each session was far too high (on one server: 9,768 USD shown for 492 USD really spent).
  Each turn now counts only its own cost, and existing sessions are recomputed from their logs at the first start.
- **Automatic compaction**: when a turn ends with more than 400k tokens of context, Harness summarizes the session
  and continues in a fresh thread seeded with the summary (like Compact), before your next message - a note says
  so. Long sessions stop re-sending their whole history: about half the tokens on long work. Settings -> Claude
  changes the threshold or turns it off.
- Shorter tool outputs: Claude keeps at most 15,000 characters of a command's output (instead of 30,000), and the
  workspace CLAUDE.md gets a short "Saving tokens" section (cut long outputs, grep logs, shrink screenshots).
- Opening a session loads its last 100 events instead of 200 (half the data, older ones still load on scroll).

**Security**
- The app page only runs its own scripts (Content-Security-Policy); HTML widgets keep working in their own sandbox.
- Signing out now really signs that browser out: the server refuses its cookie afterwards, even a copy of it. Your
  other browsers stay signed in; changing the password still signs every browser out. Cookies still last 30 days.
- The service can run in a systemd sandbox (no new privileges, read-only kernel settings, no kernel modules, at
  most 2048 processes): new installs get it, existing ones with `maxxing harden` (undo: `maxxing harden --undo`).
  Claude sessions are not limited by it.
- Links opened from an HTML page shown in Files keep that page's sandbox.
- Uploads are limited to 2 GB each and refused when they would leave less than 1 GB free on the disk ("Not enough
  free disk space"); both limits are settings in config.json (`upload_max_mb`, `upload_min_free_mb`).
- Stripe, Shopify and GitHub notification sources refuse every event until their signing secret is set (a warning
  appears in the feed). The Telegram bot answers only the account that linked it.
- Optional signed updates: with `update_verify_signature` on, `maxxing update` installs only versions signed by a
  key you trust.

**Speed**
- Faster server pages: services, Trash and the version card answer in 3-4 ms instead of 25-50 ms; the dashboard
  in about 14 ms instead of 40-50 ms.
- The `maxxing` command starts about 5x faster (`maxxing --help` 450 -> 90 ms; every cron run benefits).
- Session logs are about 25 % smaller (Claude's start-up lists and thinking progress lines are no longer stored);
  `maxxing sessions compact-logs` slims existing logs the same way. The search index no longer keeps a large
  write-ahead file.
- A new turn right after the previous one ended starts up to 0.5 s sooner.
- **Two sessions per column (grid)**: with several sessions open, the new grid button at the top of the Sessions
  page stacks them two by two (four sessions = a 2x2 grid), or drag a column onto the lower part of another, or use
  "Put under the column on the left" in its menu. Only the session you clicked shows its full message box; the
  others keep a slim "Write..." bar that opens it. Drag the line between two stacked sessions to share the height,
  double-click it to split evenly; the button (or "Give it its own column") puts them back side by side.
- **Conversations stay at the bottom**: when you are reading the latest message, it no longer slides under the
  message box when the box grows (several lines, waiting messages, a stacked session's box opening), when you move
  the line of the grid or resize the window, and a session that changes place (moved, stacked, a layout picked)
  no longer jumps to the top of its conversation. Only scrolling up yourself leaves the bottom.
- **Ready-made layouts**: with two sessions open or more, hold the mouse button down on the grip of a session (the
  dots left of its title): small layouts show up (side by side, 2x2, one big + two stacked...), click the zone
  where it should go and the others fill the rest. Or drag the session by its grip: a layouts bar slides down at
  the top, drop the session on a zone. Resting on the grid button at the top shows the same layouts for every open
  session; with the keyboard, **...** menu > **Layouts...**.
  Each layout is named (side by side, grid, main on the left / right...), every open session gets a place, and only
  the layouts that fit your screen are offered.
- **Delete a message that got no answer**: right-click a message you stopped before Claude answered (or use the
  bin next to it, also on a phone) and pick **Delete this message**: it leaves the conversation with its "Stopped."
  line, and **Undo** in the notice brings it back. Claude's own memory of the session is not changed.

## 2.0.0-alpha.31 - 2026-10-16

- **Buttons react instantly**: plan mode, notifications, favorite, archive, model and rename of a session, "mark all
  as read" in notifications, and the switches of Settings (extensions, keys, Telegram, Claude, voice,
  notifications) change as soon as you click; if the server refuses, they come back with the error message.
- **Claude plan usage works with the long-lived token**: the quota (dashboard widget, Settings -> Statistics) no
  longer says `no_oauth_credentials` on a server signed in with `claude setup-token`. When Anthropic asks to wait
  before the next reading, the last values stay shown with the time of the next reading, and every other case is
  explained in a sentence instead of an error code.
- **The logo follows your accent color everywhere**: the loading screen no longer fetches (and may flash) the blue
  logo first, and the installed app (its icon and launch screen), the iPhone home-screen icon, the "Claude
  finished" notifications and the offline page now use your accent instead of blue.
- **A sharp logo**: redrawn as a vector, it stays crisp at every size and on every screen (sidebar, loading screen,
  browser tab, installed app), with rounded corners everywhere except where the phone cuts its own shape (Android,
  iPhone home screen).
- **No more zoom on phones**: tapping a field (the sessions search, the file viewer filters, the cron editor's
  command, the code editor...) no longer zooms the page on an iPhone, double-tapping a button no longer zooms
  either (pinch-to-zoom still works), and on Android the keyboard resizes the page instead of covering it.
- **Easier to tap**: the small "×" buttons (attachments, task labels, backup patterns) and the task column
  selector have a larger touch area. Every page and its menus, dialogs and sheets were checked at four phone and
  tablet sizes: nothing overflows the screen.
- **Every page checked for speed**: each page now asks for its data as soon as you point at its link in the
  sidebar (or tap it), and while its code downloads instead of after. On a mid-range phone (measured with a 4x
  slower processor):
  - a folder of 1 500 files opens in 1.7 s instead of 4.5 s: the list shows its first rows at once and the
    next ones as you scroll;
  - **Settings -> General** opens in 1.2 s instead of 1.8 s (the font previews load one by one after the page
    is shown, and the time zone list is only built when you open it), and switching to Settings from another
    page takes half the time;
  - the dashboard shows its cards as soon as its data arrives, and the whole grid is in place in about half a
    second instead of more than one.
- **Shorter entrance animations**: dashboard cards, settings cards and the app's first appearance animate
  faster, and the sessions list does not replay its intro every time you come back to it.
- **A slow widget no longer holds the dashboard**: after 1.5 s the dashboard shows the other cards and that one
  fills in when it is ready. HTML widgets (games, canvases) no longer restart each time the dashboard refreshes.
- **Smoother conversations while Harness writes**: a running answer now only redraws the conversation, not the
  message box and the column around it, and the sessions list updates its counters at most every 2 seconds.
- **Fewer requests**: data the server already sends live (sessions, tasks, scheduled jobs...) is no longer
  reloaded every time you come back to the tab (only after a minute away), the notifications page makes one
  request instead of two, and the documentation search makes one request instead of 24.
- **Thumbnails can no longer slow everything down**: opening a folder full of new photos prepares at most 3
  thumbnails at a time, without delaying the rest of the app. Large folders also list faster on the server.
- **Extension pages open instantly the second time**: their code is downloaded once and reused until the file
  changes.

## 2.0.0-alpha.30 - 2026-10-15

- **Install the app from the account menu**: **Install app** (the person icon at the bottom of the sidebar) is
  always there now: one click in Chrome and Edge, and the exact steps for Safari on a Mac (Add to Dock),
  Firefox, iPhone and Android otherwise. **Settings -> General -> App** explains it too, with a QR code to open
  the app on your phone and add it to the home screen.
- **Faster app**: after each update the app downloads about 4 times less before it is ready (fonts,
  translations and code coloring now load only when needed), and open conversations and session lists put less
  load on the server. A font other than the default may show a plain font for a moment the first time it is used.
- **Conversations open sooner**: the app asks the server for the first screen while it is still starting, and a
  long conversation shows its last messages first, the earlier ones right after (on a mid-range phone, a
  300-message conversation shows in 3.0 s instead of 3.8 s). Session lists and folders answer up to twice as fast.
- **Lighter over Tailscale or local access**: the server now compresses its answers itself when no domain proxy
  does it (the sessions list: 175 kB -> 13 kB).
- **Sessions list: Projects / Sessions**: one small button at the top switches between the sessions grouped by
  project (as before) and every session in one list, most used first - one line each, the title and its topic.
  The old "Hidden" layout is that list now.
- **Lighter list header**: the filter hides behind a magnifier (click to search, Esc to close), and the
  Favorites block only shows once you have a favorite.
- **Smooth sessions list**: switching Projects / Sessions, opening the search and a Favorites block appearing
  are animated like the rest of the app.
- **Badges fade out**: a counter that reaches 0 (finished, running, notifications) shrinks and fades out instead of
  vanishing, and pops in when it appears.
- **A column left alone fills the page again**: close the other columns and the last one takes the whole width,
  even if it was resized; its width comes back when you open a second column.
- **Diagrams in answers**: Claude can explain with a small diagram (flowchart, sequence, states, timeline...)
  drawn right in the conversation, in the colors of the light or dark theme, with Enlarge, Show the code and
  Copy. The drawing library is only downloaded the first time a diagram appears.
- **Local files always clickable**: the workspace instructions now ask Claude to cite every local file, image or
  video by its full path (a link to the file viewer, with a thumbnail for media) and to keep the files it wants
  to show inside the files root rather than in `/tmp` (see the upgrade note).
- **The assistant is now called Harness** in the interface and on Telegram: "Ask Harness…", "Message Harness…",
  "Harness has finished", "Harness prompt" for scheduled jobs, the *Ask Harness* button under notifications.
  "Claude" stays where it means the underlying account and CLI (Settings -> Claude, sign-in, subscription usage).

## 2.0.0-alpha.29 - 2026-10-15

- **Security hardening: sign-in**: after 8 wrong passwords an address is blocked for 15 minutes, even with the
  right password. When many addresses fail at once, sign-in slows down for everyone (retry after a few seconds).
- **Security hardening: files**: files opened in the browser never run scripts (only images, audio, video and
  PDF are shown as they are). HTML page previews never reach hidden files; a page saved directly in the files
  root or the home folder is shown alone, without the files next to it - put it in its own folder.
- **Security hardening: the rest**: webhooks refuse requests over 1 MB right away, dashboard widgets only reach
  their own extension, imports skip Claude Code settings and hooks, more environment names are reserved for
  Keys, and the server sends its own security headers.
- **Quote Claude's answers**: select text in a reply and click **Quote** - the passage goes into a card above
  the composer (several quotes stack, each removable) and is sent as a quote before your message, then shown
  as a quote block in the conversation. Works in side-question answers and on phones too.
- **Finished badge in green**: the counter of finished sessions is no longer solid blue - it is a
  see-through green (the running one stays in your theme color).
- **Click a badge to see those sessions**: a click on the running or finished counter (sidebar, tab bar,
  or a project / topic of the session tree) shows only those sessions in the tree, unfolded, with
  **Open all** and **×** to come back to the whole tree. Your open columns stay as they are.
- **The column resize handle no longer covers the scrollbar**: it sits just past the right edge of each
  column, and only a thin line lights up when you point at it.

## 2.0.0-alpha.28 - 2026-10-15

- **Notifications feed**: one place for what happens, instead of chat messages - a panel next to the dashboard
  widgets (bell + unread count; a page with every event of the last 30 days, filters, mark all read).
  Cron runs (failures one by one, successes folded), updates and sign-ins arrive by themselves.
- **Webhooks**: connect Stripe (sales, refunds, failed payments), Shopify (orders, refunds, stock), GitHub
  (failed workflows, PRs, releases) or any tool sending JSON - Settings -> Notifications -> Add a webhook, with
  the steps for each service and signature checks.
- **From any script**: `maxxing feed post "Title" --level warning --source mail` - ask Claude "notify me when…"
  and it sets it up.
- **Telegram thread "Notifications"**: the bot posts there by itself (no Claude, instant), per-source rules
  (auto by level, off, silent, rings), with **Ask Claude** and **Open** buttons under each message.

## 2.0.0-alpha.27 - 2026-10-15

- **Documentation brought up to date**: the welcome page and the README list everything added lately (file
  viewer, plan mode, HUD, side questions, list layouts, favorites, project emoji, moving a session, looks).
- **The help topic knows every page**: `system/help` now also answers from Customizing, Import, Tools and
  License, with up-to-date summaries (the update refreshes its page list).

## 2.0.0-alpha.26 - 2026-10-15

- **Move a session**: click the project / topic under a session's title and pick another topic. The session
  moves in the list, keeps its conversation and continues in the new topic's folder (once Claude has finished).

## 2.0.0-alpha.25 - 2026-10-15

- **Project emoji next to the project name**, not instead of it: `🛒 acme/blog · Launch plan` in Telegram threads,
  `🛒 acme / blog` in the "Where?" buttons of a new Telegram chat and in the sessions list labels.

## 2.0.0-alpha.24 - 2026-10-15

- **An emoji per project**: the project's **…** menu -> *Set an emoji…*. It shows before the project in the
  sessions list, the labels of Favorites / Recent / Hidden, and in Telegram.
- **Telegram threads show the project**: `🛒 blog · Launch plan` with an emoji, `acme/blog · Launch plan`
  without. Existing threads are renamed once after the update (Telegram shows a small "renamed" line).

## 2.0.0-alpha.23 - 2026-10-15

- **List options**: the Favorites / Recent choices are clear checkboxes (an empty box when off); the same for
  every checkbox menu. The Hidden layout keeps one sort button (no separate reverse button).

## 2.0.0-alpha.22 - 2026-10-15

- **Three layouts for the sessions list** (button at the bottom of the list): **Vertical** (the tree, with
  Close all / Open all), **Horizontal** (projects, then a project's topics, then a topic's sessions, with a
  button back to the projects) and **Hidden** (only the sessions, labelled with their project / topic, sorted by
  recent activity, A → Z or creation date).
- **Favorites and Recent**: blocks at the top of the list, switched on in the list options. Add a session to
  your favorites from its **…** menu - favorites are the same on every device.

## 2.0.0-alpha.21 - 2026-10-15

- **Open in Files** (file viewer) now opens a new tab on a computer, like **Edit**; the viewer stays open.

## 2.0.0-alpha.20 - 2026-10-15

- **Edit from the file viewer**: text files (markdown, txt, code, CSV, HTML) have an **Edit** button that opens
  them in the Files page, straight in the editor - in a new tab on a computer.

## 2.0.0-alpha.19 - 2026-10-15

- **File viewer**: a folder written with a final slash (`.../report/`) stayed on a loading placeholder - it
  now opens. A path that does not exist, or is outside the files root, says so instead of loading forever.
## 2.0.0-alpha.18 - 2026-10-14

- **File viewer**: files clicked in a session open in a viewer you can put fullscreen. **← / →** (or a
  swipe on a phone) go through every file of the conversation - pictures, documents, code, anything.
  Folders open as a grid with thumbnails; *Parent folder* goes up.
- **More files shown as they are**: CSV / TSV as a sortable, filterable **table**, HTML as the **real page**
  (with its images and scripts, isolated from your session), **archives** (zip, tar, gz) list their
  contents, **fonts** show a specimen, **TIFF** pictures are converted, **PDF** thumbnails in the grid.
- **Files page**: ← / → now go to the previous / next file of any type; markdown, CSV and HTML have
  Preview / Edit / Split; a fullscreen button opens the viewer.
- With a domain, PDF previews showed a blank frame: fixed (the update adjusts your web server setting).

## 2.0.0-alpha.17 - 2026-10-14

- **Tinted background**: Settings -> General -> Background: keep neutral greys or take a shade of your accent
  color (dark + blue = a bluish dark, light + green = a soft green light...).
- **Many more fonts**: 23 interface fonts grouped by style (modern, with character, rounded, serif, easy to
  read, monospace) and 11 code fonts, all bundled and only loaded when chosen.

## 2.0.0-alpha.16 - 2026-10-14

- **Accent colors that match the logos**: each of the six accents now has the hue of its mascot (blue,
  orange, purple, green, yellow, red), tuned for readable buttons in the dark and light themes; the color
  names follow (Clay -> Orange, Violet -> Purple, Amber -> Yellow, Rose -> Red).

## 2.0.0-alpha.15 - 2026-10-14

- **Ask without interrupting**: a message sent while Claude works waits in its card; besides **Steer** and
  **Edit**, **Question** now asks it on the side - Claude answers about the session (where it is at, why it
  did something, what is left) without stopping its task. The answer opens in a larger panel above the
  composer that you close with its ×; it is not added to the conversation.

## 2.0.0-alpha.14 - 2026-10-14

- **Open all / Close all** shows "Close all" as soon as anything is open; "Open all" only when every
  project is folded.

## 2.0.0-alpha.13 - 2026-10-14

- **Plan mode**: Claude first explores and proposes a plan, and changes nothing - no file written, no
  command that modifies anything - until you validate it. Answer to adjust the plan as many times as
  you like, then click **Validate**. Turn it on with the plan button of a session header, or
  tick **Plan mode** when you start a new session. The HUD can validate the plan too.
- **Smoother Settings**: the highlight of the menu slides to the section you open, and its cards rise in one
  after the other.

## 2.0.0-alpha.12 - 2026-10-14

- **Settings -> Features**: every optional feature in one page - HUD mode, "notify me when a session
  finishes", web conversations in Telegram, the Claude plan usage widget and presentation mode by default.
- **Open all / Close all** at the bottom of the session tree: unfold or fold every project and topic at once.

## 2.0.0-alpha.11 - 2026-10-14

- **The logo takes your accent color**: six colors (blue, orange, violet, green, amber, rose), each with its
  own version of the mascot in the sidebar, on the sign-in page, the start-up screen and the browser tab.
  The teal and graphite accents are gone (if you used one, you are back on blue).
- **Choose your fonts**: Settings -> General -> Appearance -> Font (Inter, Geist, IBM Plex Sans, Nunito Sans,
  Atkinson Hyperlegible or your system font) and Code font (system, JetBrains Mono, Fira Code, Geist Mono).
  All fonts ship with the product: nothing is loaded from the internet.

## 2.0.0-alpha.10 - 2026-10-14

- **HUD mode**: a small floating window for one session - the prompt, the last three steps of Claude
  and its answer. In Chrome and Edge it stays on top of all your apps and you can move it
  anywhere (a second screen too); other browsers open it in a small window. **Share my screen** attaches
  a capture of your screen to each message you send from it, so Claude sees what you see - and can
  answer with that capture annotated (arrows, boxes) to show you where to look. While Claude works you
  see what it is doing; when it is done, its answer and its images (‹ › to go through them) appear right
  in the HUD. Turn it on in Settings → General, then click the HUD button of a session.
- **Smoother sessions page**: a new session slides into the list, a deleted or archived one fades away,
  and the others glide to their new place (also when the most recent session moves to the top). Opening,
  closing or moving a column works the same way: the other columns slide over instead of jumping.
- **Images open much faster**: a big image is shown at once from its thumbnail, then from a light version
  (a 4.6 MB photo: 0.1 s instead of 2.2 s on 4G, about 20x faster); the original loads quietly right after,
  so zooming stays instant. Media in a conversation are prepared by the server as soon as the message
  arrives, hovering a picture already starts loading it, and files you open again from the Files page
  come from the browser cache.
- **A real video and audio player** in the colors of your theme: poster image, big play button, progress
  bar with what is loaded, volume, speed (0.75x-2x), picture in picture, full screen and keyboard
  shortcuts once you click it (Space/K, arrows, J/L, 0-9, M, F).

## 2.0.0-alpha.9 - 2026-10-14

- **New logo**: the Harness Maxxing mascot (in the sidebar, sign-in page, start-up screen, browser tab,
  offline page and the installed app icon). The browser-tab icon no longer changes with the accent color.

## 2.0.0-alpha.8 - 2026-10-14

- **One search for everything**: Ctrl/⌘+K now searches the sessions (titles and messages), the memory,
  the tasks and the content of the workspace files, with the best matches first and the matched words
  highlighted. Words can be in any order, the start of a word is enough and accents do not matter -
  and it answers in a few milliseconds. The separate search button of the Sessions page is gone.
- **Steer Claude while it works**: a message sent during a turn waits in the queue; **Steer**
  interrupts the turn and gives it to Claude right away - it keeps what it has done and continues
  the task with your new instructions, without starting over. **Edit** puts the waiting messages back
  into the composer to change them first.
- **Fold buttons where you expect them**: the sidebar fold button is always at the bottom; the
  session tree folds from its top left corner and leaves a slim rail to unfold it.

## 2.0.0-alpha.7 - 2026-10-14

- **Safe on a server that is already in use**: the installer first looks at the server (other
  services reachable from outside, a web server on ports 80/443, an active firewall, Docker, other
  scheduled jobs, an older Node.js, an existing Claude Code setup, other Telegram bridges) and says
  what it will do differently before changing anything. `curl -fsSL https://get.harness-maxxing.com | bash -s -- --check`
  only shows that report. On such a server:
  - the firewall is not turned on when other services are exposed or Docker runs (an active ufw is
    kept, only the needed ports are added); `FIREWALL=1` forces it as before;
  - nginx / Apache keep ports 80/443: Caddy is not installed and the reverse-proxy block to paste is
    saved in `<state>/reverse-proxy.conf`;
  - **the server clock is never changed** (`system_clock = keep`): jobs still run at the times you
    pick in your own time zone (their crontab lines check the schedule in your zone, daylight saving
    included);
  - an older Node.js stays in place, Harness Maxxing gets its own in `<state>/tools/node`;
  - a busy port 8787 moves to the next free one; an existing fail2ban SSH jail and automatic-update
    settings are kept;
  - `maxxing uninstall` lists what the installer changed (firewall, time zone).
- **Faster interface on Windows and Mac**: the sign-in check starts in `index.html`, in parallel with the
  JavaScript download, and a logo splash is painted before any script runs; the command palette, shortcuts,
  install dialog and guided tour load when the browser is idle instead of before the first paint; the
  framework code is split into stable vendor chunks (a release that only touches app code keeps them cached);
  code highlighting ships 17 grammars instead of 37 (-25 % on the Markdown chunk); no more `backdrop-filter`
  blur anywhere (costly on Windows/Intel GPUs, soft text); live-update invalidations are batched; page chunks
  and the sessions list are prefetched when idle; long file lists skip off-screen
  rows (`content-visibility`); the conversation scroller is layout-isolated.
- **The browser-tab icon and the start-up logo take your accent color.**
- **Smaller downloads**: every JS/CSS file ships pre-compressed with Brotli (served to browsers that accept it,
  ~18 % smaller than the proxy's gzip) and the Inter font is preloaded.
- **No double start after an update**: a new version found waiting when the page loads is activated silently;
  the page used to reload a second time and replay its start-up.
- **Light animations**: on the first load the sidebar and its entries assemble themselves; pages fade in on
  navigation; dashboard widgets arrive one after the other; projects, topics and sessions in the tree rise in one after the other and unfold when opened;
  a session that opens cascades its last messages and new messages rise as they arrive. Transform/opacity
  only, switched off by the system "reduce motion" setting.
- **Change many tasks at once**: Ctrl/⌘ + click several cards (or tick the round box on a card, a
  column or a group) and use the bar that appears to set their status, priority, due date,
  project or labels, or to delete them. Drag a selected card to move the whole selection.
- **Know when Claude is done**: Settings -> Notifications turns on a notification when a session
  finishes (with an optional chime); unread counters are now round and can pulse.
- **Move files by drag and drop**: drop a file or folder onto another folder or onto the breadcrumb;
  files dropped from your computer onto a folder go straight into it.
- **Second brain cleaner**: Settings -> Memory sets a maximum length for every memory.md (200 lines
  by default) - the nightly clean-up and the new **Clean now** button compact and reorder the files
  above it; the page lists every memory file with its size.
- **Stats**: Settings -> Stats shows your Claude plan usage and the tokens of each
  project, topic and session, with a per-day chart.
- **Right context gauge**: the session gauge measures against the real context window of the model
  in use, as Claude reports it (1 million tokens for the current models instead of a fixed 200 000),
  so it no longer turns red too early - and when you switch a session to another model, it shows
  that model's window before you send.
- **What's new**: after each update, a short note tells you what changed (also in Settings -> System).
## 2.0.0-alpha.6 - 2026-10-14

- **Licenses**: install with `curl -fsSL https://get.harness-maxxing.com | bash` and the license key
  from your email - no GitHub account or token any more. Every version is a **signed archive**
  (ed25519, checked before anything is installed); `maxxing update` downloads it and installs it
  exactly as before (customizations carried over, rollback). New `maxxing license
  status|check|activate|release|ping`; Settings -> System shows the license; the doctor checks it.
  A license works on a set number of servers; `maxxing license release` frees one before moving.
  Installed servers keep working even when updates end. Once a day the server sends its version,
  whether the service runs and a few health codes (never files, prompts or keys) - see
  docs/user/23-license.md.

## 2.0.0-alpha.5

- **Renamed Harness Maxxing** (was Claude Maxxing, then briefly Agent Maxxing) everywhere you see it (UI, installer, CLI, Telegram, docs, skills).
  Technical names are unchanged: service `claude-maxxing`, `/opt/claude-maxxing`,
  `/var/lib/claude-maxxing`, the `maxxing` command.
- **Tools installed with the product**: zip, unzip, jq, ripgrep, ImageMagick, poppler-utils,
  Node.js 22 and **Remotion** (prepared once, shared by every video project; `install.sh --tools`
  re-runs it). New commands `maxxing video new|status` and `maxxing pdf IN.html OUT.pdf`.
- **Reliability fixes from an external audit** (thanks to FEUAZUR, PRs #1, #2 and #4 - integrated
  selectively): a damaged `config.json` / `secrets.json` no longer breaks the UI nor gets overwritten
  (a copy is kept, doctor reports it); atomic writes keep file permissions; the update token never
  appears in the process list; password checks no longer block the server; no update lost for a slow
  browser tab; uploads with the same name at the same time no longer collide; a refused message keeps
  its text and attachments, sending is blocked while an upload failed, drafts survive leaving the
  session; the task editor keeps an edit that failed to save; file names with `%` open; stale searches
  are cancelled; the trash shows load errors with Retry; more image/video/audio types previewed.
  Claude settings show "Claude Code default" when no model is chosen; the token tooltip details cache
  reads and writes; Claude tuning variables (effort, thinking, caching…) reach systemd-run turns.
- **Scrapling at install + skill `web-scraping`**: static, JavaScript and protected pages to
  Markdown / CSV / JSON (`scrapling extract …`, `scrapling-python script.py`), results saved in the
  topic, polite by default. No MCP server (it would cost context in every session).
- **Server hardened at install**: automatic security updates, fail2ban for SSH (1 h ban after 5
  failures) and a firewall (ufw) letting in only SSH (detected ports), 80/443 or Tailscale - a dev
  server Claude starts on 0.0.0.0 is no longer exposed. `FIREWALL=0` skips the firewall;
  `install.sh --secure` applies it to an existing server; `maxxing doctor` warns when missing.
- **New skills**: `video-motion-design` (Remotion videos), `pdf-document` (HTML -> PDF),
  `image-edit` (ImageMagick / ffmpeg recipes), `seo-audit` (real checks + prioritized report).
- **Import from another agent** (onboarding step 3, Settings -> Import, `maxxing import`): copy a
  prompt into Hermes, Claude Code, OpenClaw or any agent, drop the zip it makes - projects, topics,
  memory, skills, to-dos and recurring jobs arrive. Preview first; nothing is overwritten (memory
  merged in an "Imported" section, other files saved next to the existing ones); files with keys
  are refused; then Claude finishes the job (tasks, jobs, keys to add) in a session.
- **Trash with restore**: Settings -> Trash lists everything deleted - files, folders, topics and
  projects (with their sessions) and sessions - with **Restore** (back where it was, or next to it if
  the name is taken), *Delete forever* and *Empty the trash*; items older than 30 days are removed
  automatically. Deleting a session now moves it to the trash instead of erasing it.
- **Telegram threads = open sessions**: the bot chat now mirrors the Sessions page. Every open
  session (the ones you talk to - not cron runs - not archived, active in the last 30 days, at most
  50) has its own thread `<topic> · <title>`; renaming a session renames it, **archiving** a session
  deletes its thread (the conversation stays on the server), un-archiving brings it back, `/close`
  in a thread archives its session and deletes the thread (a thread deleted by hand comes back the
  next time the session is used). Write in the main chat (or create a thread) to
  start a new session: the bot asks which topic (default `general/inbox` after 5 minutes). `/new` in
  a session thread opens a sibling session with its own thread; `/sessions` lists the open ones.
  Kept in sync automatically (a few seconds after any change, and every 10 minutes) - no cron.
  Settings -> Telegram -> *Keep a thread for* (7 / 14 / 30 / 90 days). Existing chats are migrated on
  the first start: each topic's thread is kept for the session Telegram used there (history stays),
  the other topic threads and "General" are deleted.
- **Web conversations on Telegram**: what you write in the web UI and Claude's answers are copied
  into the session's thread, silently; the session's bell makes its answers ring on the phone
  (Settings -> Telegram -> *Show web conversations in Telegram*, off by default).
- The Telegram icon next to sessions is gone (every session is on Telegram now); the cron clock stays.
- Telegram live status: the final summary could be overwritten by a last "working…" update.
- Installer: Claude Code failed to install after `sudo -i` from a non-root account (Anthropic's
  installer refuses to run under sudo) - it is now installed for root on purpose, retried once, and
  a failure shows the installer's output and the likely cause (network, country, disk).

## 2.0.0-alpha.4 - 2026-10-12

- **Installed app on phones**: no more empty band under the bottom tabs (the home-indicator inset was
  added in full under a 60 px bar); the tab bar is a bit slimmer, its colour reaches the screen edge,
  and the mobile conversation view is anchored to both edges of the screen.
- **Today's schedule widget** (built in, on by default): the day of your scheduled jobs on a
  00:00 - 24:00 line - one row per job, runs done (green / red), runs still to come, the one running
  and a "now" line. Existing dashboards get it at the end (drag it where you like). New Card block
  `timeline` that extensions can use too (bookings, deliveries, shifts...).
- **Built-in Shopify widget**: connect a store with `SHOPIFY_STORE` + `SHOPIFY_ADMIN_TOKEN` (Settings ->
  Keys) to see revenue today and over 7 days (with the change vs the week before), orders today,
  orders to ship, a 14-day revenue chart and the latest orders (Admin GraphQL, read-only, cached 2 min).
- **Customizations kept by updates**: changes to the product code are recorded as customizations
  (`maxxing custom save "title" --why "reason"`, listed in `<workspace>/CUSTOMIZATIONS.md`, patches
  in `customizations/`, included in the backup and re-applied on a new server). `maxxing update` now
  auto-saves unsaved edits, replays customizations onto the new version, and on a conflict changes
  nothing (exit 3: Claude adapts them in `system/update`, then `maxxing update --resume`); a version
  that does not start is rolled back (exit 4); `maxxing update --rollback`. The code clone gets a local
  git identity and `core.editor=true`, so a rebase finished by Claude without a terminal just works. Settings -> System shows
  customizations and a pending update. New skill `maxxing-customize`, doc "Customizing".
- **HTML widgets**: a widget can be a free-form `widget.html` (games, canvas, custom drawings) drawn
  in a sandboxed frame (no access to the app, its cookies or its API), with a bridge to its own
  `api.py` (`maxxing.api`), `maxxing.resize`, the theme and its colours as CSS variables. Example:
  `examples/extensions/snake-widget/`. Docs and the `maxxing-extension` skill updated; Claude no
  longer sends users to the product's authors for things an extension can do.

## 2.0.0-alpha.3 - unreleased

- Page extensions in the sidebar: an **Extensions** entry opens the list of extension pages (`/x`);
  pin a page (Settings -> Extensions -> "In the sidebar", or the pin on that list) to give it its own
  sidebar entry. `PATCH /api/extensions/{id}` accepts `pinned`.
- Telegram status message made compact: one header line, then a quote with the current task
  (`◐ 2/5 …`) and the last 3 steps cut to their first 42 characters; the final summary folds the
  steps into an expandable quote.
- Web: no more "New version available" toast. A build waiting at page load is applied right away;
  otherwise a discreet line in the sidebar ("New version - reload" / "Update available") and a dot
  on the Settings tab on mobile.
- Onboarding / Settings -> Claude: the subscription token is generated over SSH on the server itself
  (Claude Code is already there) instead of installing Claude Code on another computer.
- `maxxing backup status` no longer lists the always-included patterns twice.
- **Fix: local voice transcription failed on every message** with Python 3.12+ (PyAV 19 removed an
  argument faster-whisper 1.2 uses). PyAV is pinned below 19 in the `voice` extra; a test now
  decodes real audio.
- `maxxing doctor` warns when the domain goes through the Cloudflare proxy (the server cannot see
  visitor IPs: sign-in alerts and login throttling). `HEAD` requests on UI pages answer 200 (uptime
  monitors).
- Fix: restarting the service (update, Settings -> System) took 90 s and ended with a SIGKILL
  whenever a browser tab was open - live connections kept the server waiting. Graceful shutdown is
  now limited to 3 s (`TimeoutStopSec=15` in the unit of new installs).
- **Security fix**: the server log (journal) contained the Telegram bot token - the HTTP client
  logged every Telegram API URL. HTTP client logs are now at warning level and every log line goes
  through a secret redaction filter (Telegram, Anthropic, GitHub, Groq/OpenAI formats).
- Web: while the server restarts (update, reboot) a pill says "The server is restarting -
  reconnecting…" then "Reconnected"; data requests are paused meanwhile instead of turning into
  errors with Retry buttons, and everything refreshes on reconnection.
- Fix: Settings -> System -> Version always said "Latest version unknown" on a private repository
  (the check did not use the update token). New **Check now** button and "checked … ago".
- Telegram: a live status message while Claude works - Claude's task list (☑ ◐ ☐) and each step
  (⋯ running, ✓ done, ✗ failed) with a timer, edited in place, then folded into a one-line summary
  with the steps in an expandable quote. Quick answers get no status message. New default reply
  mode `progress`, also on existing installs unless "Final answer" was explicitly chosen.
- Telegram: "typing…" is refreshed every 4 s (it used to blink) and falls back to the main chat
  when Telegram refuses chat actions in a thread (errors were silently ignored).

## 2.0.0-alpha.2 - unreleased

- Installer: new look (logo, live spinner and timer per step, one summary box with the setup
  link), fewer questions (voice is on with the local engine by default, the time zone is picked in
  the web onboarding), the repository token is asked up front, the DNS record is checked before
  installing, apt noise hidden.
- Fix: the Python version is pinned to 3.12 (`server/.python-version`): on servers without a system
  Python, uv picked the newest CPython, for which the local voice engine has no wheel yet.
- Fix: changing the time zone in the UI (onboarding or Settings) now also switches the server time
  zone, so scheduled jobs fire at the times shown.
- Default projects in every new workspace: `system` (topics `help`, `update`, `server`, `tasks`,
  `accounts`, `extensions` - each with precise instructions for Claude) and `tutorial` (four
  interactive 5-minute lessons). Templates are rendered with the code/workspace paths; a default
  project or topic you delete is never re-created by updates.
- `maxxing update --check` only checks now (installed vs latest version and the changelog in
  between, changes nothing); `--notify` sends a Telegram message when an update exists; `--json`.
- Workspace upgrade notes (`docs/upgrade/<version>.md`): instructions for Claude, applied in the
  topic `system/update` after an update; `maxxing update` lists the notes of the new versions.
- New default jobs: "Check for updates" (weekly), "Morning tasks" and "Renewal reminder" (disabled).
- Cron reports with notify "always" include the job's output (e.g. the answer of a Claude job).
- Backup includes `projects/*/topics/*/accounts.md` by default.
- Docs: "The system project", default projects, tutorial, `update --check/--notify`.

## 2.0.0-alpha.1 - unreleased

First alpha of Harness Maxxing 2.

- One-line installer: domain (Caddy + HTTPS), Tailscale or local access; never listens publicly;
  unattended mode; optional restore from a memory backup; re-runnable, `--update`, `--uninstall`.
- `maxxing` CLI: `init`, `doctor` (with `--json`), `update`, `status`, `uninstall`, `setup-link`,
  `password`, `cron`, `backup`, `telegram`.
- Guided web onboarding: password, Claude connection, first project, Telegram, backup.
- Sessions: projects -> topics -> persistent sessions, live streaming, attachments, message queue,
  model per session, compact and hand-off, archive, search, command palette.
- Files, Tasks (kanban on `tasks.json`), Crons managed from the UI (shell or Claude jobs).
- Built-in Telegram gateway: one thread per topic, same sessions as the web UI.
- Memory backup to a private GitHub repository with secret scanner and one-click restore.
- Dashboard with built-in widgets, extension widgets (JSON cards) and page extensions.
- Shipped Claude Code skills: memory, memory-compaction, maxxing-setup, maxxing-doctor,
  maxxing-telegram, maxxing-backup, maxxing-cron, maxxing-tasks, maxxing-extension.
- In-app documentation (English).
- Voice messages: mic button in the composer (tap or push-to-talk) and Telegram voice notes,
  transcribed on the server - local Whisper (faster-whisper, optional `voice` extra), Groq or OpenAI;
  Settings -> Voice with install/download progress and a recording test; `maxxing voice`.
