---
section: Extending
---
# Dashboard widgets

The **Dashboard** is a grid of cards. Drag to reorder, hide the ones you do not need (layout menu),
refresh a card with its refresh button.

Cards build themselves as they appear: numbers count up to their value, lists and tables rise in row by row,
chart bars grow and lines draw, progress bars fill, and **Today's schedule** opens each job's line and drops its
runs on it from left to right. A card further down the page waits until you scroll to it, so you see it too.
When the notifications panel opens or closes, the cards slide to their new place. Everything stays still when
your system asks for reduced motion.

A new install shows Activity, Server, Today's schedule, Tasks and **Make it yours**. The others are hidden
until you need them (**Edit layout** shows them); Shopify appears by itself once a store is connected.

**Make it yours** is the card at the end: click an example ("Today's Shopify sales", "Visitors on my
website"...) and a new session opens in `system/harness` with the request already typed - send it, and
Harness writes the widget in your extensions. Any request works the same way from any session: "add a widget
that shows ...". Hide the card with **Edit layout** once you have yours.

## Built-in widgets

| Widget | Shows |
|---|---|
| Activity | recent sessions, running turns, unread answers (before the first session: where to start) |
| Tasks | in progress, due today, overdue |
| Today's schedule | the day of your scheduled jobs on a 00:00 - 24:00 line: one row per job, runs done (green, red if failed), runs still to come (hollow), the one running now (pulsing) and a "now" line; hover a dot for its time and duration |
| Scheduled jobs | next runs and recent failures |
| Server | CPU, memory, disk, uptime, health issues |
| Memory backup | last run, age, repository |
| Telegram | bot and link status |
| Shopify | revenue today and over 7 days (vs the week before), orders today, orders to ship, 14-day revenue chart, latest orders — once a store is connected (below); beyond 5000 orders in 14 days it warns that older days are incomplete |
| Make it yours | how to get your own widgets, with examples that open a session ready to send |
| Claude usage | *off by default* (Settings -> Features): plan usage windows, the same as the bars at the bottom of the sidebar (read from the last Claude answer; when none came for 10 minutes it asks an undocumented Anthropic endpoint, which may stop working; when that endpoint fails or asks to wait, the last figures read from Claude stay shown). |

## Connect a Shopify store

The Shopify widget shows a "Connect your store" card until you add two keys:

1. In Shopify admin: **Settings → Apps and sales channels → Develop apps → Create an app**, then
   **Configure Admin API scopes** → tick `read_orders` → **Install app** → reveal the **Admin API
   access token** (`shpat_…`, shown once).
2. In Harness Maxxing: **Settings → Keys** → add `SHOPIFY_STORE` = `myshop.myshopify.com` and
   `SHOPIFY_ADMIN_TOKEN` = the token.

The widget refreshes every 2 minutes (or with its refresh button) and only reads orders. Another
shop (WooCommerce, Stripe, PrestaShop…)? Ask Claude for a widget: it builds an extension the same
way (see below).

## Writing your own widget

A widget is a folder in `<workspace>/extensions/<id>/` with two files. You write **data**, not
HTML: the card is drawn by the app's design system, so it always looks right in dark and light
mode, on desktop and phone. (Need free-form drawing or interaction - a game, a canvas? See
[HTML widgets](#html-widgets-games-custom-drawings) below.)

The fastest way: ask Claude in a session, "create a dashboard widget that shows ...". The
`maxxing-extension` skill knows everything below.

### 1. Create the folder

```
/root/maxxing/extensions/disk-usage/
  manifest.json
  api.py
```

The id (folder name) is a lowercase slug: letters, digits, dashes. Reserved ids: `activity`,
`tasks`, `day`, `crons`, `server`, `backup`, `telegram`, `shopify`, `usage`, `customize`.

### 2. manifest.json

```json
{"id": "disk-usage", "name": "Disk usage", "type": "widget", "icon": "hard-drive",
 "version": "1.0.0", "api": 1, "span": 1, "ttl": 60}
```

| Key | Meaning |
|---|---|
| `type` | `widget` |
| `api` | version of the extension contract it is written for (default 1); a release that stops supporting it is announced by the update preflight before you update |
| `icon` | an icon name in kebab-case (`gauge`, `chart-line`, `shopping-cart`, `users`, `receipt`...) from the app's set of [lucide](https://lucide.dev/icons) icons; a name the app does not ship shows a puzzle piece |
| `span` | width in grid columns: 1, 2 or 3 |
| `ttl` | seconds the result is cached (default 300). The refresh button bypasses it. |

### 3. api.py

```python
import shutil


def card(ctx):
    du = shutil.disk_usage("/")
    pct = round(100 * (du.total - du.free) / du.total)
    return {
        "title": "Disk usage",
        "status": "error" if pct > 95 else "warn" if pct > 85 else "ok",
        "blocks": [
            {"type": "stat", "label": "Used", "value": f"{pct}%", "hint": f"{du.free / 1e9:.1f} GB free"},
            {"type": "progress", "label": "/", "value": pct, "max": 100},
        ],
    }
```

`card(ctx)` runs inside the server: use only the Python standard library, keep network calls short
(timeout ≤ 10 s). Extension code runs on 4 threads of its own: code that never returns (a network call without a
timeout) only blocks other extensions ("extensions are busy" until it returns), never the rest of Harness. An
`api.py` must load in under 10 s (no network call at import time), or the extension shows an error. `ctx` contains:

| Key | Value |
|---|---|
| `id` | the extension id |
| `workspace` | workspace path |
| `state_dir` | a folder reserved for this extension (cache, data) |
| `secret(name)` | value of a key from Settings -> Keys, or `None` |
| `config` | `{"timezone", "language", "public_url"}` |

Never hard-code a token: store it in Settings -> Keys and read it with `ctx["secret"]("MY_TOKEN")`.

### 4. The Card schema

```
Card  = {title?, status?: "ok"|"warn"|"error", link?, blocks: [Block], updated?}
Block =
  {type: "stat", label, value, hint?, delta?, tone?: "ok"|"warn"|"error"}
| {type: "stats", items: [stat, ...]}                      several stats in a row
| {type: "list", items: [{title, subtitle?, value?, href?, status?, icon?, emoji?}], empty?, grid?}
                                                            grid: true = tiles side by side (shortcuts)
                                                            icon: an icon name (below), drawn like the app's
| {type: "chart", kind: "bar"|"line", series: [{name, points: [[x, y], ...]}], unit?}
| {type: "table", columns: [str], rows: [[cell, ...]]}
| {type: "progress", label, value, max, hint?}
| {type: "markdown", text}
```

`link` makes the card title clickable (an app route like `/tasks` or an `https://` URL). Unknown
block types are ignored.

Example list + chart:

```python
def card(ctx):
    orders = [("#1042", "Alice", 89.0), ("#1041", "Bob", 34.5)]
    return {
        "title": "Shop",
        "link": "https://shop.example.com/admin",
        "blocks": [
            {"type": "stats", "items": [{"type": "stat", "label": "Today", "value": "123.50 €"},
                                        {"type": "stat", "label": "Orders", "value": "2"}]},
            {"type": "chart", "kind": "bar", "unit": "€",
             "series": [{"name": "Sales", "points": [["Mon", 80], ["Tue", 120], ["Wed", 123.5]]}]},
            {"type": "list", "empty": "No orders yet",
             "items": [{"title": o, "subtitle": c, "value": f"{v:.2f} €"} for o, c, v in orders]},
        ],
    }
```

### 5. Test, then load

Test the function directly on the server:

```bash
cd /root/maxxing/extensions/disk-usage && python3 -c "
import json, api, tempfile
ctx = {'id': 'disk-usage', 'workspace': '/root/maxxing', 'state_dir': tempfile.mkdtemp(),
       'secret': lambda n: None, 'config': {'timezone': 'UTC', 'language': 'en', 'public_url': ''}}
print(json.dumps(api.card(ctx), indent=2))"
```

Then **Settings -> Extensions -> Reload**. The widget appears on the dashboard. If something is
wrong (invalid manifest, import error, exception in `card`), the error is shown on the extension's
row and on the card; the rest of the dashboard keeps working.

Extensions live in your workspace: updates never touch them and the backup includes them.

## HTML widgets (games, custom drawings)

When a Card is not enough - a small game, a canvas drawing, a custom chart library - write the
widget in HTML instead. Same folder, with `widget.html` instead of (or next to) `api.py`:

```
/root/maxxing/extensions/snake-widget/
  manifest.json     {"type": "widget", "name": "Snake", "icon": "gamepad-2", "height": 300}
  widget.html       one self-contained file: inline <style> and <script>
  api.py            optional: handle(ctx, method, path, query, body) for data it saves or fetches
```

The dashboard draws `widget.html` in a **sandboxed frame**: scripts run, but the frame cannot read
the app, its cookies or its API - a widget can never act as you. It talks to its own `api.py`
through a small bridge that is injected for you:

| In widget.html | What it does |
|---|---|
| `await maxxing.api("best")` · `maxxing.api("best", {method: "PUT", body: {...}})` | calls `handle()` in this extension's `api.py` (`/api/ext/<id>/best`), returns its JSON |
| `maxxing.resize(400)` | sets the frame height in px (the manifest `height`, 120-800, is the default) |
| `maxxing.theme` · `maxxing.onTheme(fn)` | `"dark"` or `"light"`, and a callback when it changes |
| `class="ui-card"`, `ui-btn`, `ui-input`, `ui-badge`, `ui-stat`... | the app's **UI kit** (see [Page extensions](page-extensions#styling)), already loaded in the frame |
| `var(--card)` `--foreground` `--muted-foreground` `--border` `--primary`... (and the older `--mx-fg` `--mx-muted` `--mx-border` `--mx-accent` `--mx-card` `--mx-bg`) | the app's colors, updated with the theme and the accent color |

Rules: one file only (no other file of the folder is served to the frame - inline everything, or
load libraries from a CDN `<script src="https://...">`); no `localStorage`/cookies (the sandbox has
none: save through `api.py` and `ctx["state_dir"]`). The refresh button of the card reloads the
frame. Full example: `examples/extensions/snake-widget/` in the code directory.
