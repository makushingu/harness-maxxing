---
name: maxxing-doctor
description: Diagnose and repair a Harness Maxxing installation. Use when the UI does not load, sign-in fails, sessions do not start or stay stuck, scheduled jobs do not run, Telegram is silent, backups fail, or the user asks "what is wrong" / "check the server".
---

# Diagnose & repair Harness Maxxing

Principle: **observe first, then fix the smallest thing**. Never delete data, reset the password,
purge or reinstall without the user's explicit OK. Tell the user what you found and what you changed.

## 1. Collect
```bash
maxxing doctor --json          # every check with level + fix hint (exit 1 if a check fails)
maxxing status                 # version, URL, service, auth, telegram, backup
systemctl status claude-maxxing --no-pager
journalctl -u claude-maxxing -n 100 --no-pager      # server log
```
Paths: code `{{CODE_DIR}}`, state `{{STATE_DIR}}` (config.json, secrets.json,
sessions/, crons/, telegram/, backup/, logs/), workspace from `maxxing status`.
Running turns live in transient units `maxxing-<8 chars>`: `systemctl list-units 'maxxing-*'`,
`journalctl -u maxxing-<id8>`.

## 2. Common failures
| Symptom | Likely cause | Fix |
|---|---|---|
| Browser cannot connect, `http` check fails | service down / crash loop | `journalctl -u claude-maxxing -n 100`; fix the error; `systemctl restart claude-maxxing` |
| `ModuleNotFoundError` / import error in the log | dependencies out of sync after a manual pull | `cd {{CODE_DIR}}/server && uv sync --frozen --no-dev && systemctl restart claude-maxxing` |
| "web/dist is missing" (503) | incomplete checkout | `maxxing update` |
| Domain shows a certificate error or does not load | DNS not pointing here, ports 80/443 closed, Caddy error | `getent ahosts <domain>`, `ufw status`, cloud firewall, `journalctl -u caddy -n 50`, `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile` |
| `bind` check fails | listening on a public address | `maxxing init --bind 127.0.0.1` then restart (domain mode) or the Tailscale IP |
| Tailscale URL dead after reboot | Tailscale IP changed / not up | `tailscale ip -4`; `maxxing init --bind <ip> --public-url http://<ip>:8787`; restart |
| Sign-in: "too many attempts" | login throttle (15 min window) | wait, or restart the service (clears the in-memory counter) |
| Password lost | - | user runs `maxxing password` on the server |
| Every session errors immediately | Claude not signed in / token expired | `maxxing doctor --live`; renew with `claude setup-token` -> Settings -> Claude |
| Session stuck "running" | turn unit died | `systemctl list-units 'maxxing-*'`; press Stop in the UI; check the unit journal |
| "resume failed" note in a session | Claude transcript missing | normal fallback: a new Claude context is started automatically |
| Scheduled job never runs | crontab block out of sync, cron daemon stopped, job disabled | `maxxing cron list`, `crontab -l`, `maxxing cron sync`, `systemctl status cron` |
| Job fires at the wrong hour | config time zone differs from the system zone (cron uses the system one) | `timedatectl set-timezone <Zone> && systemctl restart cron`; `maxxing init --timezone <Zone>`; restart the service |
| Job runs but fails | command error | `maxxing cron run <id>` and read the output; Crons page -> history |
| Telegram silent | token revoked, chat unlinked, another program polls the same bot | `maxxing telegram status`, `maxxing telegram test`; see `maxxing-telegram` |
| Backup fails | token expired, repo became public, secret detected | `maxxing backup status`; see `maxxing-backup` |
| Disk full | transcripts, attachments, logs | `du -sh ~/.claude/projects {{STATE_DIR}}/* <workspace>/projects/*/topics/*/attachments`; `journalctl --vacuum-size=200M` - ask before deleting anything |
| UI looks stale after update | old tab | hard reload; index.html is never cached |

## 3. Repair rules
- Prefer `maxxing` commands over editing state files. If you must edit `config.json`, stop nothing,
  keep valid JSON, and restart the service afterwards. Never print `secrets.json`.
- Restarting `claude-maxxing` is safe for running turns (they are separate units) but disconnects
  the UI for a few seconds - say so first.
- Edits of the product code are **customizations** (skill `maxxing-customize`): "unsaved
  change(s) in the code directory" -> record them with `maxxing custom save`; "update pending"
  (conflict or rollback) -> follow that skill's "During an update" section. Never `git reset` or
  `git checkout` the code directory without the user's yes - it would delete their changes.
- Finish with `maxxing doctor` and a short report: cause, fix, what remains.
