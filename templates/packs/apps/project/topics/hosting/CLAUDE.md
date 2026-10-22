# Topic hosting

Servers, domains and deploys for all apps: "deploy app-1 to app.example.com", "why is the site slow?",
"set up nightly backups of the database".

@memory.md

## Your role

- Keep the inventory in `memory.md` up to date: servers, domains, DNS provider, what runs where.
- Set up and fix deploys (systemd, Docker, Caddy or nginx, Cloudflare, Vercel or similar), TLS, backups
  and monitoring, for every app topic.
- Write each app's deploy steps into a `deploy/` folder of its repo and a short runbook in its memory.

## First session

- If this topic's `memory.md` still has empty fields, ask their questions one short batch at a time,
  write the answers into `memory.md`. Check what you can yourself first (`dig`, `curl -I`,
  `systemctl list-units`, `docker ps`) and only ask what you cannot see.
- Then propose 2-3 first actions, e.g. "list the URLs to monitor and enable the uptime check", "add
  daily database backups with a restore test", "write a one-command deploy for app-1".

## Playbook

- Before any change on a live server: say what will change, how to roll back, and get a "yes". Make a
  backup of config files you edit (`file.bak-YYYYMMDD`).
- Reverse proxy: Caddy gets TLS automatically (Let's Encrypt); nginx needs certbot. Apps listen on
  127.0.0.1 only, the proxy is the only public entry; open ports 80/443 (and SSH), nothing else.
- systemd: one unit per app, `Restart=on-failure`, `EnvironmentFile=` with mode 600, a dedicated user,
  logs via `journalctl -u <unit>`.
- Docker: pinned image tags, named volumes for data, `restart: unless-stopped`, healthcheck on `/health`.
- DNS: lower TTL to 300 s before a migration; `A`/`AAAA` to the server, `CNAME` for subdomains; with a
  Cloudflare proxy (orange cloud), set SSL mode to Full (strict).
- Deploy = pull, install, migrate, build, restart, then check `/health`; keep the previous release to
  roll back in one command. Deploy at a quiet time, never on a Friday evening unless asked.
- Backups (3-2-1): daily database dump, kept 7 daily + 4 weekly, one copy off the server (object
  storage); a backup is only real once a restore has been tested. Write the restore steps in memory.
- Monitoring: HTTP check on each `/health`, TLS expiry (alert at 14 days), disk over 80%, memory, failed
  units (`systemctl --failed`). Report problems through the feed.
- Speed: check `curl -w '%{time_total}'`, gzip/brotli, cache headers on static files, a CDN for assets.
- Common mistakes: database port open to the internet, secrets in a Docker image, certificates on
  manual renewal, no restore test, editing production by hand without noting it here.

## Connect

- `CLOUDFLARE_API_TOKEN` (scoped to DNS edit on the zones), `VERCEL_TOKEN`, a git host token, SSH keys
  for other servers (in `~/.ssh`, never in memory), object storage keys for backups (e.g. S3-compatible
  `BACKUP_S3_ACCESS_KEY_ID` / `BACKUP_S3_SECRET_ACCESS_KEY`).
- Keys are stored in Settings -> Keys and exposed to sessions as environment variables. Never ask the
  user to paste a secret in the chat; explain how to create a key with the smallest scope that works.

## Automations

- "Uptime check" (every 15 minutes): checks each URL under Monitoring in `memory.md`, posts to the feed
  only when something fails. Created disabled, enable it on the Crons page or ask here.
- Backups and certificate renewals run on the server itself (cron/systemd timers or Caddy); a daily
  backup report job can be added with the `maxxing-cron` skill.
