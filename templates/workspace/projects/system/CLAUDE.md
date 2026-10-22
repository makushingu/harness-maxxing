# Project system

Harness Maxxing itself: the tutorial, help (including the server) and the product (updates,
widgets, starter packs). Open the topic that matches what you want and just ask. Tasks and
subscriptions live in `general/inbox`.

@memory.md

## Topics

| Topic | Use it for |
|---|---|
| `tutorial` | four 5-minute lessons; say "hi" to start or continue, delete the topic when done |
| `help` | questions about Harness Maxxing ("how do I ...?"), answered from the installed documentation; server health, disk, services, logs, security updates, firewall |
| `harness` | check for a new version, update, apply the workspace upgrade notes; build dashboard widgets (Card or HTML: games, canvas), pages and extensions; add starter packs |

## Facts for every topic of this project

- Product code (installed version): `{{CODE_DIR}}` · user documentation: `{{CODE_DIR}}/docs/user/`
- Workspace: `{{WORKSPACE}}` · server CLI: `maxxing` (`maxxing --help`, reference in
  `{{CODE_DIR}}/docs/user/17-cli-reference.md`).
- Never write secrets (passwords, tokens, API keys) in any file of the workspace: they belong in
  Settings -> Keys.
- Ask before anything destructive or disruptive (deleting data, restarting `claude-maxxing`,
  rebooting, changing the firewall).
- Changing the product itself is allowed: extension first, otherwise a recorded customization
  (skill `maxxing-customize`, list in `{{WORKSPACE}}/CUSTOMIZATIONS.md`). Never leave an unrecorded
  edit in `{{CODE_DIR}}`.
