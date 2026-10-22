---
section: Using Harness Maxxing
---
# Infra: sites, databases, buckets, domains, servers

The **Infra page** answers "where is what, and is it working?": every site, database, bucket, domain and server -
on this server, on your other servers, on Cloudflare and on Hostinger - with its status, its links (this domain ->
this server -> this site -> this app -> this repository) and the Harness project it belongs to.

It is **off by default**: turn it on in **Settings -> Features -> Infra page**. An **Infra** entry appears in the
sidebar (shortcut G then I).

## How it works

1. **Harness reads everything**: this server directly, your other servers over SSH (read-only), Cloudflare and
   Hostinger with their API keys. It links what it finds: a domain to its site, a site to its app, its database and
   its git repository.
2. **It watches it for you**: every address is checked (does it answer, is its certificate valid), so are domain
   expiry dates and disk space, every 15 minutes (`infra_refresh_min`) or when you click **Refresh**. A problem goes
   to the top of the page and to your notifications, once per incident.
3. **You create by asking Claude**: "put this folder online", "create a database for my app"... Claude follows the
   standard recipes (below) and the result appears on the page.

The page itself never changes your sites or databases; the only thing it does on its own is connecting a server
(see [Other servers](#other-servers)). To change something, ask Claude: each line has an **Ask Claude** box.

## The page

- **Overview**: a "How it works" box (with a link to this page) (close it with ×, bring it back with **How it works** at the top right), the
  count of each kind with what is down or to check, the list **To look at**, and **What Harness reads**: each
  source with what it gives and, when something is missing, the next step (**Add the key ...**, **Add these
  rights** for a Cloudflare token that cannot read everything, **Connect** for a VPS not read yet).
- **Sites, Databases, Buckets, Domains**: grouped by where they live. **Domains -> Add a domain** watches a domain
  from any registrar. Search, filter by project, show hidden lines
  with the eye button.
- **Servers**: one card per server with its address, its system, memory / disk / CPU in use and how many sites,
  databases and buckets run on it.
- Click any line for its details, what it is linked to, its repository (opens the Git page), its Cloudflare /
  Hostinger dashboard, a project, a note, to hide it, or to ask Claude about it.

## What it reads

| Source | What you see | Needs |
|---|---|---|
| This server | Caddy (or nginx) sites and what is behind each one (folder, app port, systemd service, Docker container, git repository), PostgreSQL / MySQL databases (also inside Docker), SQLite files, Garage buckets, disk, memory | nothing |
| Your other servers | the same, read over SSH | `python3` there and SSH access: see [Other servers](#other-servers) |
| Any domain | registrar and expiry date (public RDAP service), who serves its DNS (OVH, GoDaddy, Namecheap, IONOS, Gandi, o2switch...), who hosts its address (one of your servers, Vercel, Netlify, GitHub Pages, Shopify, Cloudflare, Webflow, Wix, Squarespace...) | nothing (public DNS); add the domains no provider lists in **Domains -> Add a domain** |
| Cloudflare | domains (zones) and their DNS, Workers and their addresses, Pages, R2 buckets and their public addresses, D1 databases, Registrar domains | the key `CLOUDFLARE_API_TOKEN` (+ `CLOUDFLARE_ACCOUNT_ID`) |
| Hostinger | domains with their expiry date, VPS, DNS zones | the key `HOSTINGER_API_TOKEN` |
| Vercel *(beta)* | projects with their production deployment (state, date, git repository, framework), their domains; domains bought at Vercel with their expiry date; every team the token sees | the key `VERCEL_TOKEN` |
| Netlify *(beta)* | sites with their last deployment and git repository, Netlify DNS zones | the key `NETLIFY_AUTH_TOKEN` |
| Supabase *(beta)* | each project: its database (state, region, Postgres version; a paused free project shows "paused"), its Storage buckets, its Edge Functions, linked together | the key `SUPABASE_ACCESS_TOKEN` |
| GitHub Pages *(beta)* | the Pages sites of your repositories, their address and build state | the GitHub tokens already in your keys (Git page) |

Keys go in **Settings -> Keys** (the Infra page links to them). Harness only **reads** with them. Give read rights
where the provider allows it (Cloudflare, GitHub); Vercel, Netlify and Supabase tokens cannot be limited to reading:
leave them **not exposed** to sessions (the default in Keys) so only the Infra page uses them. A token without one of
the rights only hides that part: the page says which.

The public DNS lookups go through a public resolver over HTTPS (Cloudflare's 1.1.1.1 by default): it sees the domain
names asked, nothing else. Each name is looked up at most every 6 hours.

### Creating the keys

- **Cloudflare**: [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens) ->
  Create token -> Custom, rights (Read): Zone, DNS, Workers Scripts, Workers Routes, Cloudflare Pages, Workers R2
  Storage, D1, Registrar; add **DNS Edit** if you want Claude to create DNS records for new sites.
- **Hostinger**: hPanel -> Profile -> API -> new token.
- **Vercel**: [vercel.com/account/settings/tokens](https://vercel.com/account/settings/tokens) -> Create token, scope
  "Full account" to see every team (Vercel has no read-only token: Harness only reads).
- **Netlify**: User settings -> Applications -> Personal access tokens -> New access token.
- **Supabase**: [supabase.com/dashboard/account/tokens](https://supabase.com/dashboard/account/tokens) -> Generate
  new token.
- **GitHub Pages**: nothing more if the Git page already shows your repositories.

*Beta* means written from the provider's official API reference and tested against its documented answers, not yet
seen on a real account: if a line shows an error, ask Claude from that line (it sees the error) and tell us.

### My provider is not listed

- **Domains**: nothing is needed. Add the domain in **Domains -> Add a domain** (or ask Claude "watch the domain
  example.com"): its registrar, expiry date, DNS provider and host are read from public information, and it is
  linked to your server when it points to it. Alerts before expiry work the same.
- **A server** (OVH, DigitalOcean, Hetzner, Scaleway...): **Add a server**, it is read over SSH like any other.
- **A platform** (Render, Railway, Fly.io, Firebase, AWS...): its sites still show through their domains (the page
  says who hosts each address). Full support is planned provider by provider.

## Other servers

- **A Hostinger VPS** shows up by itself once the Hostinger key is in the vault, named **VPS Hostinger**. If it
  already accepts an SSH key of this server, Harness connects it on its own (the Hostinger API says which key, so
  nothing is tried blindly). Otherwise open it and click **Connect**: Harness adds its own key
  (`harness-maxxing@<this server>`) to the VPS' `root` account through your Hostinger key, then reads it. That is the
  only change the Infra page makes on a provider; you can remove the key in hPanel -> VPS -> SSH keys.
- **Any other server**: **Add a server** (top of the page) with its address, SSH user and port. If none of this
  server's keys is accepted there, the window gives you one line to run on that server, then **Try again**.
- In the panel of a connected server: change the **name shown** (the internal name, used in links, never changes) or
  **Disconnect** it (nothing changes on the server).
- From the terminal: `maxxing infra server connect <IP or Hostinger VPS id>`, `server rename NAME "Label"`.

Harness only reads the other servers (sites, ports and services, Docker, databases, buckets, disk, memory). The
server needs `python3` (every usual Linux has it).

## Statuses

- **OK** (green), **To check** (orange): a page answering 404, a certificate or a domain expiring soon, a DNS record
  pointing to another server than the one serving the site, a disk almost full, a failed backup...
- **Down** (red): no answer, a server error (5xx), an expired domain, a resource created by a recipe that cannot be
  found any more.

**Alerts** go to the notifications feed (and Telegram when its feed thread is on): a site or a server going down
and back up, a certificate expiring within 14 days, a domain expiring within 30 then 7 days (when not
auto-renewed).

## Create things on this server

Ask Claude in plain words; it follows a fixed recipe (skill `maxxing-infra`, command `maxxing infra`) so everything
is done the same way, checked before it is applied, and appears on the page:

- **"Put this folder online"** -> `https://<your Harness address>/<name>/`, at once, no DNS. These pages run
  **isolated** (sandboxed): they can never touch Harness or your session (an app behind such a path never receives
  your Harness cookie and cannot set one; hidden files like `.env` or `.git` are never served; the workspace root,
  the code, the state folder and `.ssh` cannot be published). Perfect for pages, demos, reports, static
  sites. An app with a login, a cart or cookies needs its **own address** (`shop.example.com`): Claude advises it,
  and creates the DNS record on Cloudflare when the key allows it.
- **"Create a database for my app"** -> PostgreSQL (installed the first time, reachable from this server only), one
  database and one user per app, its address stored in **Keys** (`DB_<NAME>_URL`), **backed up every night**
  (job "Infra: database backups", 7 copies kept in `/var/backups/maxxing-db`).
- **"Create a bucket"** -> S3 storage on this server (Garage), its keys in **Keys** (`S3_<NAME>_...`), optionally
  public at `https://<your Harness address>/<name>/`. Files stay on this disk: for big public files Cloudflare R2 is
  often better, Claude says so.
- **"Add my other server 203.0.113.7"** -> Claude connects it (`maxxing infra server connect`); if it does not
  accept a key of this server yet, Claude tells you the line to run there.

## In conversations

When Claude talks about resources, it adds a small `infra` block that the app shows live (status, link to the page):

````
```infra
site: shop.example.com
database: shop
```
````

Lines: `site`, `database`, `bucket`, `domain`, `server`, `worker`, `pages`, `id` (one resource each), or filters
`project: acme`, `kind: database`, `location: <server>`. Shown when the Infra page is on (otherwise the text stays).

## Terminal

`maxxing infra status`, `maxxing infra list [--kind site] [--json]`, `maxxing infra refresh`, and the recipes:
`site add|remove|list`, `db install|create|sqlite|backup`, `bucket install|create`, `server connect|add|rename|remove|list`,
`domain add|remove|list`,
`annotate`. See `maxxing infra --help` and the CLI reference.

## Safety of `infra.json`

The servers of `<workspace>/infra.json` are reached through `ssh` by the server itself, so Claude may not edit that
file (it is in the deny rules of every turn, like the folder settings); use `maxxing infra server add` or the page.
An entry written by hand that the CLI would refuse (odd user, host or key path) is ignored. One provider that does
not answer (Cloudflare, Hostinger, a server) only leaves its own section empty: checks and alerts of the rest go on.
