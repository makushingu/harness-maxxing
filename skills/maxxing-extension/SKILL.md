---
name: maxxing-extension
description: Build a Harness Maxxing extension - a dashboard widget (a Card with stats, lists, charts, or a free-form HTML widget such as a game or canvas) or a full page with its own API - in <workspace>/extensions/<id>/. Use when the user asks for a new widget, a dashboard card, a mini-game, a custom page, an integration shown in the UI, or to fix an existing extension. Always the first choice before touching the product code.
---

# Extensions (widgets & pages)

Extensions live in `<workspace>/extensions/<id>/` (workspace from `maxxing status`, here
`{{WORKSPACE}}`). Product updates never touch them and the memory backup includes them.

- **widget**: `manifest.json` + `api.py` with `card(ctx)` returning a **Card** (JSON). The UI draws
  it with the built-in design system - no HTML/CSS to write, consistent look guaranteed.
- **HTML widget**: `manifest.json` (`"type": "widget"`, optional `"height"`) + `widget.html` (one
  self-contained file) + optional `api.py` with `handle(...)`. For games, canvas, custom drawings:
  anything a Card cannot show. Drawn in a sandboxed frame (see below).
- **page**: `manifest.json` + `page.js` (ES module, `mount(el, ctx)`) + optional `api.py` with
  `handle(ctx, method, path, query, body)` served at `/api/ext/<id>/<path>`. Listed under
  "Extensions" in the sidebar; the user can pin it to get its own entry.

## Built-in Shopify widget
"Connect my Shopify store" needs no extension: guide the user to create a custom app in Shopify admin
(Settings → Apps and sales channels → Develop apps → Create an app → Admin API scopes `read_orders`
→ Install → reveal the `shpat_…` token) and to add `SHOPIFY_STORE` (`myshop.myshopify.com`) and
`SHOPIFY_ADMIN_TOKEN` in Settings → Keys. For more shop figures (products, ads, other platforms),
build extra widgets: they sit next to it on the dashboard.

## Which kind? (and never the product code)
| The user wants… | Build |
|---|---|
| numbers, lists, charts, status from some data source | widget with `card(ctx)` |
| a mini-game, a canvas, an interactive or custom-drawn card | HTML widget |
| a whole screen (form, board, editor, report) | page |
| to change how the product itself behaves (a server rule, a CLI command…) and no extension can do it | a **core customization**: skill `maxxing-customize` - never edit the code directory without it |

Extensions survive every update untouched. Say so to the user: they never need to wait for the
authors to add something an extension can do.

## Rules
- `id`: lowercase slug `^[a-z0-9][a-z0-9-]{0,47}$`, same as the folder name. Reserved:
  `activity tasks day crons server backup telegram shopify usage customize`.
- `name`: a string, or `{"en": "...", "fr": "..."}` to follow the UI language.
- `api`: always write `"api": 1` in the manifest (the extension contract version this extension is written
  for; the update preflight uses it to tell the user before a new version stops supporting it).
- `icon`: an icon name of the app's lucide set (`gauge`, `chart-line`, `shopping-cart`, `server`, `rss`, `users`,
  `receipt`, `calendar-days`, `package`, `star`…; the full list is `ICONS` in `<code dir>/web/src/components/ui/icon.tsx`,
  an unknown name shows a puzzle piece).
- **No emoji in the UI** (titles, list items, buttons): use icons - the Card list `icon`, `ctx.icon()` in a page.
- `api.py` runs inside the server process: **stdlib only** (urllib, json, sqlite3…), short timeouts
  (≤ 10 s), no threads left behind, never print secrets. It is called in a worker thread.
- Secrets: the user stores them in Settings -> Keys; read them with `ctx["secret"]("NAME")`
  (returns None when missing -> return a Card saying which key to add). Never hard-code a token.
- Persistent data: `ctx["state_dir"]` (a folder reserved for this extension).
- `ctx` = `{"id", "workspace", "state_dir", "secret": fn(name), "config": {"timezone", "language", "public_url"}}`.
- Widget results are cached `ttl` seconds (manifest, default 300); the card's refresh button forces it.

## Card schema
```
Card  = {title?, status?: "ok"|"warn"|"error", link?: "/route or https://…", blocks: [Block], updated?: unix}
Block = {type:"stat", label, value, hint?, delta?, tone?: "ok"|"warn"|"error"}
      | {type:"stats", items:[stat…]}
      | {type:"list", items:[{title, subtitle?, value?, href?, status?, icon?}], empty?: "text when no items",
         grid?: true}                                       grid = tiles side by side (shortcuts, examples)
                                                            icon = icon name (as the manifest), accent-coloured
      | {type:"chart", kind:"bar"|"line", series:[{name, points:[[x, y], …]}], unit?}
      | {type:"table", columns:[str], rows:[[cell, …]]}
      | {type:"progress", label, value, max, hint?}
      | {type:"markdown", text}
      | {type:"timeline", start, end, now?, lanes:[{name, sub?, color?, href?, dense?,
                         events:[{at, state?: "ok"|"error"|"running"|"planned", label?}]}]}
```
(`timeline`: unix seconds; one row per lane on a start..end axis - bookings, deliveries, shifts, runs.)
Unknown block types are dropped; the card must be JSON-serialisable.

## Minimal widget - `extensions/disk-usage/`
`manifest.json`
```json
{"id": "disk-usage", "name": "Disk usage", "type": "widget", "icon": "hard-drive", "version": "1.0.0", "span": 1, "ttl": 60}
```
`api.py`
```python
import shutil


def card(ctx):
    rows = []
    worst = 0
    for mount in ("/", "/var"):
        du = shutil.disk_usage(mount)
        pct = round(100 * (du.total - du.free) / du.total)
        worst = max(worst, pct)
        rows.append({"type": "progress", "label": mount, "value": pct, "max": 100,
                     "hint": f"{du.free / 1e9:.1f} GB free"})
    return {"title": "Disk usage",
            "status": "error" if worst > 95 else "warn" if worst > 85 else "ok",
            "blocks": [{"type": "stat", "label": "Fullest volume", "value": f"{worst}%"}, *rows]}
```

## Minimal page - `extensions/notes-board/`
`manifest.json`
```json
{"id": "notes-board", "name": "Notes board", "type": "page", "icon": "sticky-note", "version": "1.0.0"}
```
`api.py`
```python
import json
import time
from pathlib import Path


def _file(ctx):
    return Path(ctx["state_dir"]) / "notes.json"


def handle(ctx, method, path, query, body):
    f = _file(ctx)
    notes = json.loads(f.read_text()) if f.exists() else []
    if method == "GET" and path == "notes":
        return {"notes": notes}
    if method == "POST" and path == "notes":
        text = str((body or {}).get("text", "")).strip()[:500]
        if text:
            notes.insert(0, {"text": text, "at": time.time()})
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(notes[:200]))
            tmp.replace(f)
        return {"notes": notes}
    return {"error": "not_found", "message": f"{method} {path}"}
```
`page.js`
```js
export function mount(el, ctx) {
  el.innerHTML = `
    <div class="ui-page" style="max-width:640px">
      <h1 class="ui-h1">Notes board</h1>
      <form class="ui-row">
        <input class="ui-input" name="text" placeholder="New note" style="flex:1">
        <button class="ui-btn">Add</button>
      </form>
      <ul class="ui-list"></ul>
      <p class="ui-muted" hidden>No note yet: write the first one above.</p>
    </div>`;
  const list = el.querySelector("ul");
  const empty = el.querySelector("p");
  const form = el.querySelector("form");
  form.querySelector("button").prepend(ctx.icon("plus"));
  const render = ({ notes }) => {
    list.hidden = !notes.length;
    empty.hidden = !!notes.length;
    list.replaceChildren(...notes.map((n) => {
      const li = document.createElement("li");
      li.textContent = n.text;            // never inject data with innerHTML
      return li;
    }));
  };
  ctx.api("notes").then(render);
  const onSubmit = async (e) => {
    e.preventDefault();
    const text = form.text.value.trim();
    if (!text) return;
    render(await ctx.api("notes", { method: "POST", body: { text } }));
    form.reset();
  };
  form.addEventListener("submit", onSubmit);
  return () => form.removeEventListener("submit", onSubmit);
}
```
`ctx` in page.js = `{api(path, opts), navigate(route), theme, lang, t, icon(name)}` (`lang` = the UI language, "en"/"fr";
`icon("plus")` = an `<svg>` element of the app's icon set;
`navigate("/sessions?path=<topic path>&new=1&prompt=<text>")` opens a new session with the text typed in): `ctx.api` calls this extension's
own API (`/api/ext/<id>/<path>`) with the session cookie and CSRF header, and returns parsed JSON.
Always build the page with the **UI kit** (next section) so it looks like the rest of the app; use
`textContent`, not `innerHTML`, for any data.
The app only runs scripts from its own server: in page.js, no inline `<script>` added to the page and no `eval` /
`new Function` - import other modules of the folder instead (`import x from './x.js'`). HTML widgets are not
affected (their frame has its own policy).

## UI kit - the app's look for pages and HTML widgets
Page extensions and HTML widgets get the app's design system as CSS classes (loaded for you, they follow the theme,
the accent colour and the density). **Use them instead of writing your own styles**: the result looks like the
app, in dark and light. Add CSS only for the layout specific to the page.
```
layout   ui-page (page column, max 1152 px) · ui-section · ui-grid (responsive cards) · ui-row · ui-stack · ui-spacer
text     ui-h1 (page title) · ui-h2 (section/card title) · ui-h3 · ui-text · ui-muted · ui-small · ui-label · ui-num
card     ui-card · ui-card-header (ui-icon-box + <div><h2 class="ui-h2">…</h2><p class="ui-muted">…</p></div>) · ui-card-footer
tile     <button class="ui-tile"><div class="ui-icon-box">{svg}</div><div><b>Title</b><span>one line</span></div></button>
icon     ui-icon-box (+ ui-lg, ui-neutral) - the icon on a soft square of the accent colour
button   ui-btn (main action) + ui-secondary | ui-outline | ui-ghost | ui-danger, + ui-sm, ui-icon-only
form     <label class="ui-field"><span class="ui-label">Name</span><input class="ui-input"><span class="ui-small">hint</span></label>
         ui-select · ui-textarea · ui-check (checkbox)
status   ui-badge · ui-dot  + ui-success | ui-warning | ui-error | ui-primary | ui-outline
data     ui-list (<ul>, rows) · ui-table (wide: inside a <div class="ui-table-wrap">) · ui-stat > ui-stat-label + ui-stat-value · ui-progress > <span style="width:40%">
other    ui-steps (<ol>, li > ui-step-num + <div>) · ui-callout (+ ui-info|ui-success|ui-warning|ui-error, svg first)
         ui-empty (empty state: ui-icon-box ui-lg ui-neutral, ui-h2, ui-muted, a ui-btn) · ui-skeleton (loading)
         ui-code · ui-kbd · ui-link (button styled as a link) · ui-separator
```
Rules of the app's design to keep: one main `ui-btn` per area (others `ui-outline` / `ui-ghost`), an empty list
shows `ui-empty` with one sentence and an action, data loading shows `ui-skeleton` blocks of the final size, colours
only from the theme variables (`var(--primary)`, `var(--muted-foreground)`, `var(--success)`… never hex), icons not
emoji. Example: `<workspace>/extensions/pages/page.js` (the "Your pages" page) and
`<code dir>/examples/extensions/notes-page/`.

## HTML widget - `extensions/snake-widget/`
Copy `<code dir>/examples/extensions/snake-widget/` (a working game) and adapt it. In widget.html:
- `maxxing.api(path, {method, body, query})` -> Promise of the JSON returned by this extension's
  `handle()`; `maxxing.resize(px)`; `maxxing.theme` + `maxxing.onTheme(fn)`.
- The UI kit above is already in the frame (`ui-card`, `ui-btn`, `ui-stat`…), and the theme variables too:
  `var(--card)`, `--foreground`, `--muted-foreground`, `--border`, `--primary`… (older names `--mx-fg`, `--mx-muted`,
  `--mx-border`, `--mx-accent`, `--mx-card`, `--mx-bg` still work). No icon helper in the frame: inline an `<svg>`.
- The frame is sandboxed (scripts yes, same-origin no): no cookies, no localStorage, no access to
  the app or `/api/...` - persist through `api.py` + `ctx["state_dir"]`. Only `widget.html` is
  served: inline CSS/JS, or load a library from a CDN with an absolute https URL.
- Keyboard games: make the canvas focusable (`tabindex="0"`) and start on click; add touch/swipe
  for phones.

## Steps
1. Ask what to show, where the data comes from, refresh rate, which secrets are needed.
2. Create the folder and files; for API calls use `urllib.request` with `timeout=10`.
3. Test the Python side directly, without the server:
   ```bash
   cd <workspace>/extensions/<id> && python3 -c "
   import json, api, tempfile
   ctx = {'id': '<id>', 'workspace': '<workspace>', 'state_dir': tempfile.mkdtemp(),
          'secret': lambda n: None, 'config': {'timezone': 'UTC', 'language': 'en', 'public_url': ''}}
   print(json.dumps(api.card(ctx), indent=2))"     # page: api.handle(ctx, 'GET', 'notes', {}, None)
   ```
   Check `page.js` syntax with `node --check page.js` if node is available.
4. Tell the user: **Settings -> Extensions -> Reload**, then check the dashboard / the new page.
   Errors (bad manifest, import error, exception in card) are shown on the extension's row there.
5. Record the extension's purpose and data source in the topic memory (`memory` skill).

The HTTP API needs a signed-in browser session, so do not try to test it with curl; use the
Python test above and the UI.
