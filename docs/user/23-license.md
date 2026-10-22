---
section: Getting started
---
# License

Harness Maxxing is **free** and **fair source** (source-available): its code is public on GitHub and published under the
[Harness Maxxing Fair Source License](https://github.com/makushingu/harness-maxxing/blob/main/LICENSE).
No license key is needed to install it or to get updates: the installer clones the public git repository
and `maxxing update` pulls from it. A key is only for companies (see [Enterprise key](#enterprise-key-optional)).

## What the license allows

- **Use** Harness Maxxing for free, for any personal or professional purpose of your own.
- **Copy, modify, fork and redistribute** it, with or without changes, as long as the license and the copyright
  notice stay with every copy and modified copies say so.
- **Organisations**: one legal entity may use it for its own internal needs.

## What needs the owners' written consent

- selling, reselling, renting or licensing it (or a fork), or charging for distributing it;
- putting it in a paid product, offer or service (paid installation, setup or support built on it included);
- running it as a paid hosted or managed service;
- using the "Harness Maxxing" name or logo for a fork, a product or a service (saying truthfully that your work is
  based on Harness Maxxing is fine);
- using it for affiliates, subsidiaries, clients or other third parties of an organisation.

For any of these, ask for a commercial license: [Harness Maxxing Enterprise](https://harness-maxxing.com/#enterprise).
The full text is the `LICENSE` file in the code folder (`/opt/claude-maxxing/LICENSE`).

## Saying hello (optional)

Nobody has to tell us anything. The onboarding has a step **About you** and **Settings → Profile** has a card
**Harness Maxxing team** with three choices, all optional:

| Choice | What is sent to `api.harness-maxxing.com` |
|---|---|
| **Help count the installations (anonymous)** - checked by default in the onboarding | once a day: a random number the server got the first time and the Harness Maxxing version. Nothing else: no name, no email, no IP kept, no content. |
| **Email** | your email, your pseudo (Settings → Profile) and the interface language, so we can warn you about a security issue or a breaking change. Never shared, never sold. |
| **Also send me the product news** (needs an email) | the same, plus a few product emails a month at most. |

Unchecking everything (or **Stop, don't contact me**) stops it: the server sends nothing more and is never contacted
again (security alerts included). To have what we have about it erased, ask us (see
[harness-maxxing.com/privacy](https://harness-maxxing.com/privacy)). An update never turns any of these on: a server
installed before this choice existed sends nothing until you check something.

## Feedback (bugs, ideas)

**Feedback** at the bottom of the sidebar (on a phone or a tablet: ⊞ → **Feedback**) writes to the Harness Maxxing
team: pick **Bug**, **Idea** or **Other**, write your message and give your email. The email is required: it keeps
spam away and lets us answer you (a confirmation is sent there). The server sends to `api.harness-maxxing.com`
your email, your message, its type, the Harness Maxxing version, the interface language and your pseudo (Settings →
Profile) - nothing else: no logs, no files, no session content. The last email used is filled in next time (the first
time: the one of Settings → Profile → Harness Maxxing team, if any).

## Donations

Harness Maxxing is free; donations fund its development. The **Donate** links carry a hand-and-heart icon in the app's
accent colour: a small icon at the bottom of the sidebar, next to the eye, the theme and the account (on a phone or a
tablet: a line of the ⊞ menu), **Settings → Support** (last in the list of Settings), at the bottom of **What's new**,
after a **Feedback** is sent and in **Settings → License**. They are only links: they open
[harness-maxxing.com/donation](https://harness-maxxing.com/donation) in a new tab (in the interface language: pay with
Lightning or Bitcoin), and the app never talks to a payment service. **Settings → Support → Hide the Donate buttons**
removes them for every browser of the server (the Support page stays).

## Enterprise key (optional)

Only companies in one of the cases above need a key; nobody else has anything to do. Give it in
**Settings → License** (or in the onboarding step **About you**, box "I have an Enterprise license key"), or
`maxxing license activate`. The key is checked by `api.harness-maxxing.com` and counted on this server (one key =
one server). It changes nothing in how Harness Maxxing works: the code and the updates keep coming from GitHub.
**Remove the key** (Settings → License, or `maxxing license remove`) frees its place for another server.

| Command | What it does |
|---|---|
| `maxxing license status` | the key of this server (type, email, end date), or "no Enterprise key" |
| `maxxing license activate` | record a key (asked hidden; or `HM-…`, or `--key-from-stdin`) |
| `maxxing license remove` | forget the key and free its place |

The installer still accepts `LICENSE=HM-…` (scripts written before): the key is recorded at the end, the code
comes from GitHub like every install.

### Servers installed with a key before 2.0.0a87

They used to update from signed archives. Since 2.0.0a87 they **move to the public git repository by themselves**:
a few minutes after updating to 2.0.0a87 (or at the next `maxxing update`) the code follows the `stable` branch of
`github.com/makushingu/harness-maxxing`, at the same version, with the customizations kept; the key stays (Settings
→ License). If it cannot move yet (no network, uncommitted changes in the code folder, an update being finished) it
tries again every few hours and `maxxing doctor` says why.

## What is sent to the license server

Only when a key is recorded or removed: the key, a one-way fingerprint of the machine (never the raw machine id),
its hostname, operating system and Harness Maxxing version; the license server also sees the IP address. A server
still on signed archives (before it moves to git) also sends, at each update check and once a day, whether the
service runs and a few health codes (disk and memory level, uptime, Claude connected, age of the last backup).

Never sent: your files, sessions, prompts, memory, keys, project or topic names (a **Feedback** message carries only
what you typed, see above).
Details: [harness-maxxing.com/privacy](https://harness-maxxing.com/privacy).
