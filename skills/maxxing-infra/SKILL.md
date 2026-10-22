---
name: maxxing-infra
description: Put a site online, create a database or an S3 bucket on this server the standard way, add another server, or answer "where is X / what runs where / is it up" - sites (Caddy), PostgreSQL/SQLite, Garage buckets, domains, other servers over SSH, Cloudflare (Workers, Pages, R2, D1) and Hostinger. Use when the user wants something hosted, published, stored, or asks about their sites, databases, buckets, domains or servers.
---

# Infra: see everything, create on this server the standard way

The **Infra page** (Settings -> Features -> Infra page, off by default) shows every site, database, bucket,
domain and server with its status and links. The command `maxxing infra` is the same thing in the terminal **and
the only way to create things here**: never hand-write a Caddy block, a database or a bucket - use the recipes
below, they validate, roll back on error, store credentials in the vault, register the resource and back it up.

## Look first
```bash
maxxing infra status                 # sources (servers, Cloudflare, Hostinger), counts, everything down or to check
maxxing infra list [--kind site|database|bucket|domain|server|worker|pages] [--json]
maxxing infra refresh                # gather now (10-60 s); the server also does it every 15 min when the page is on
```
`list --json` gives each resource's `id`, `urls`, `status`/`status_detail`, `details` (target port, service unit,
repository, DNS records, certificate, sizes...) and `links` (domain <-> sites, site <-> server...).
When you talk about resources in a reply, add an ` ```infra ` block so the UI shows them live:
```infra
site: shop.example.com
database: shop
```
(one line per resource: `site`, `database`, `bucket`, `domain`, `server`, `worker`, `pages`, `id`; or filters
`project: acme`, `kind: database`, `location: <server name>`).

## Put a site online
```bash
maxxing infra site add NAME --dir /path/to/folder [--project P]        # static files
maxxing infra site add NAME --port 3100 [--project P] [--keep-prefix] # an app listening on 127.0.0.1:3100
maxxing infra site add NAME (--dir D | --port N) --host shop.example.com [--dns]   # its own address
maxxing infra site list | site remove NAME | reserved
```
- **Default = path site**: `https://<address of Harness>/<NAME>/`, nothing to configure, works at once. The page is
  **sandboxed** (Content-Security-Policy sandbox): it cannot touch Harness, its session or its API, and has no
  localStorage/cookies of its own. Perfect for pages, demos, landing pages, reports, static builds.
- Built sites must use **relative paths or the base `/<NAME>/`**: Vite `base: '/<NAME>/'`, Next `basePath`,
  Astro `base`. A build with absolute `/assets/...` loads Harness's files instead.
- An app (`--port`) gets the path stripped (it sees `/`); `--keep-prefix` keeps `/<NAME>/` for apps configured
  with a base path.
- **Use `--host` (advice, explain it) for**: an app with a login, a cart, cookies or localStorage, an API called
  from its own pages, anything in production. `--dns` creates the A record on Cloudflare when the token may edit DNS;
  otherwise tell the user which record to add (A `<host>` -> the server's IP, DNS only / grey cloud if the zone is
  proxied two levels deep).
- Names: a-z 0-9 -, not a route of Harness (`maxxing infra reserved`).
- An app needs a process: write a systemd unit (`/etc/systemd/system/<name>.service`, `Restart=always`,
  `WorkingDirectory=`, the port on 127.0.0.1 only), `systemctl enable --now`, then `site add --port`.
  Pick a free port (`ss -ltn`), 3100-3999 by convention.

## Databases
```bash
maxxing infra db install               # PostgreSQL, localhost only, + the nightly job "Infra: database backups"
maxxing infra db create NAME [--project P]   # role + database NAME; URL in the vault: DB_<NAME>_URL (not exposed)
maxxing infra db sqlite /path/app.db [--project P]   # declare a SQLite file: shown and backed up
maxxing infra db backup                # dump everything now into /var/backups/maxxing-db (7 kept per database)
```
- Ask before `db install` (it installs a package). The app reads its URL with `maxxing keys get DB_<NAME>_URL`
  (put it in the app's own env file, mode 600) - never print the password in the chat.
- Remote access = SSH tunnel only (`ssh -L 5432:127.0.0.1:5432 root@server`). Never open 5432.
- Databases in Docker are shown but not backed up by the job: say so if it matters.

## Buckets (S3 on this server)
```bash
maxxing infra bucket install                       # Garage, single node, every port on 127.0.0.1
maxxing infra bucket create NAME [--public] [--project P]
```
- Keys in the vault: `S3_<NAME>_ACCESS_KEY_ID`, `S3_<NAME>_SECRET_ACCESS_KEY`, `S3_<NAME>_ENDPOINT`
  (`http://127.0.0.1:3900`), `S3_<NAME>_BUCKET`, `S3_<NAME>_REGION` (`garage`). Any S3 client works
  (path-style addressing).
- `--public` serves its files at `https://<address of Harness>/<NAME>/`.
- A bucket here lives on this disk, without a copy elsewhere: for big public files or production, advise
  Cloudflare R2 (free egress) - check the free disk first (`maxxing infra list --kind server`).

## Other servers
```bash
maxxing infra server connect HOST [--user root] [--port 22] [--label "Shop server"]   # finds a key that works
maxxing infra server connect <Hostinger VPS id>        # id = the N of server:hostinger:N in `list --kind server --json`
maxxing infra server add NAME HOST [--key /root/.ssh/id_x] [--label L]   # a given key
maxxing infra server rename NAME "Label" | server list | server remove NAME
```
Prefer `connect`: for a Hostinger VPS it uses the key the VPS already accepts (read through the API) or adds the
Harness key (`<state>/ssh/infra_ed25519`) to its root account through the Hostinger API (tell the user: it is a
change on their VPS). For another server, when no key works it prints the line to run there. A running Hostinger VPS
that already accepts one of our keys is connected by the refresh itself. The name is the short host name
(`srv100200`, part of the ids); the label ("VPS Hostinger") is what the page shows.
The server must accept SSH from this one without a password (key) and have `python3`. The probe only reads
(Caddy/nginx sites, ports and services, Docker, PostgreSQL/MySQL including in containers, SQLite, Garage). To act
on that server, use `ssh` yourself - the Infra page never changes anything remotely.

## Domains from any registrar
`maxxing infra domain add example.com` (or Domains -> Add a domain): no key needed, its registrar, expiry, DNS
provider and host come from RDAP and the public DNS. Use it for every domain the providers below do not list.

## Providers (keys in Settings -> Keys)
- **Cloudflare**: `CLOUDFLARE_API_TOKEN` (+ `CLOUDFLARE_ACCOUNT_ID`). Read rights: Zone, DNS, Workers Scripts,
  Workers Routes, Pages, R2, D1, Registrar (Account settings: Read). `--dns` needs DNS Edit. A missing right
  only hides that part (`maxxing infra status` says which).
- **Hostinger**: `HOSTINGER_API_TOKEN` (hPanel -> API): domains with their expiry, VPS, DNS zones.
- **Vercel** `VERCEL_TOKEN`, **Netlify** `NETLIFY_AUTH_TOKEN`, **Supabase** `SUPABASE_ACCESS_TOKEN` (beta): sites and
  deployments, domains, Supabase databases/buckets/functions. **GitHub Pages**: the GitHub tokens of the vault.
- Other registrars and hosts: no key, `maxxing infra domain add` (RDAP + public DNS: registrar, expiry, DNS
  provider, who hosts the address). A provider line in error: read its message in `maxxing infra status`.

## Organise
`maxxing infra annotate ID --project P --note "..." [--hide|--show]` - attach a resource to a Harness project,
leave a note, hide noise. The page's resource panel does the same, plus "Ask Claude".

## Alerts
While the page is on: a site/server going down (and back up), a certificate expiring within 14 days, a domain
expiring within 30 then 7 days (not auto-renewed), a failed backup -> the notifications feed (and Telegram if the
feed thread is on).
