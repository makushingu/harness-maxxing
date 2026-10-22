# Security policy

Harness Maxxing runs Claude Code with wide permissions on your server, so security reports matter a lot to us.
Thank you for reporting responsibly.

## Report a vulnerability privately

**Never open a public issue, discussion or pull request for a vulnerability.** Use one of these private channels:

1. **GitHub private vulnerability reporting** (preferred): on the repository, *Security* -> *Report a
   vulnerability* ([direct link](https://github.com/makushingu/harness-maxxing/security/advisories/new)).
2. The contact form on [harness-maxxing.com](https://harness-maxxing.com), starting your message with "Security".

Please include:

- the version (`maxxing status`) and how Harness Maxxing is installed (git, license key, local copy);
- what an attacker can do, and from where (internet, the local network, another user of the server, a session);
- the steps to reproduce, or a proof of concept;
- any idea of a fix.

## What happens next

- We acknowledge the report within **3 working days** and keep you informed.
- We confirm the issue, prepare a fix and release it; the changelog credits you unless you prefer otherwise.
- Please give us a reasonable time to ship the fix (90 days at most) before any public disclosure.

## Supported versions

Only the latest version on `main` (and the latest signed release) receives security fixes. Update with
`maxxing update`.

## Scope

In scope: the server (`server/`), the web UI (`web/`), the installer (`install.sh`), the PC agent (`pc-agent/`),
the shipped skills and templates. Out of scope: what Claude Code does with the permissions you gave it on your own
server, vulnerabilities of third-party components that are already fixed upstream (tell us if we ship an old
version), and reports from automated scanners without a demonstrated impact.
