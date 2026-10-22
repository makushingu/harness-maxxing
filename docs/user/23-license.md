---
section: Getting started
---
# License

Harness Maxxing is **free** and **fair source**: its code is public on GitHub and published under the
[Harness Maxxing Fair Source License](https://github.com/makushingu/harness-maxxing/blob/main/LICENSE).
No license key is needed to install it or to get updates: the installer clones the public git repository
and `maxxing update` pulls from it.

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

Unchecking everything (or **Stop and delete**) deletes what we have about this server. An update never turns any of
these on: a server installed before this choice existed sends nothing until you check something.

## Existing license keys

A license key bought earlier (`HM-XXXX-XXXX-XXXX-XXXX`) keeps working: a server installed with it keeps getting
**signed** updates from the license server, and a new server can still use it
(`curl -fsSL https://get.harness-maxxing.com | LICENSE=HM-… bash`). Every signed version is checked: the installer
and `maxxing update` refuse an archive that was not signed by Harness Maxxing. A licensed server keeps working on its
version even if the license ends or the license server cannot be reached.

A key works on a fixed number of servers at a time (shown in your license email). Moving to a new server:
`maxxing license release` on the old one, then install on the new one with the key. Reinstalling the **same**
server does not take a new place.

| Command | What it does |
|---|---|
| `maxxing license status` | key, type, email, updates until, latest version (or "no license" on a git install) |
| `maxxing license check` | ask the license server for a new version |
| `maxxing license activate HM-…` | activate this server with a key (also turns a git install into a licensed one) |
| `maxxing license release` | free this server's place before moving to another server |
| `maxxing license ping` | send the daily status now |

Settings → System shows the license when the server has one.

## What is sent to the license server

Only by servers that use a license key (a git install sends only what you chose in [Saying hello](#saying-hello-optional)). When a server is activated, at each update
check and **once a day**: the license it uses, a one-way fingerprint of the machine (never the raw machine id), its
hostname, operating system, Harness Maxxing version, whether the service runs and a few health codes (disk and
memory level, uptime, Claude connected, age of the last backup, names of the problems the doctor sees). The license
server also sees the IP address the server connects from.

Never sent: your files, sessions, prompts, memory, keys, project or topic names.
Details: [harness-maxxing.com/privacy](https://harness-maxxing.com/privacy).
