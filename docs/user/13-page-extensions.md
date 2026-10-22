---
section: Extending
---
# Page extensions

A page extension adds a full page to the app, served at `/x/<id>`. It is a plain JavaScript
module – no build step – plus an optional Python API.

Where it appears: every page is listed under **Extensions** in the sidebar (the `/x` page). Click the
**pin** at the top right of a page (or on the Extensions page, or turn on **In the sidebar** in
Settings -> Extensions) to give it its own sidebar entry, right below Extensions; click it again to unpin.

```
/root/maxxing/extensions/notes-board/
  manifest.json
  page.js        the page (ES module)
  api.py         optional: its HTTP API
```

Ask Claude "create a page that ..." and the `maxxing-extension` skill writes it for you, or follow
these steps.

A new install comes with one page, **Your pages** (`extensions/pages/`): what a page extension is, and
examples (client file, order tracker, invoices...) that open a session with the request already typed. It is
an ordinary extension: delete its folder, or turn it off in Settings -> Extensions, when you no longer need it
- updates do not bring it back.

## 1. manifest.json

```json
{"id": "notes-board", "name": "Notes board", "type": "page", "icon": "sticky-note", "version": "1.0.0"}
```

`name` can also be `{"en": "Notes board", "fr": "Tableau de notes"}`: the app shows the one of its language.
`"api": 1` (optional, default 1) is the version of the extension contract the page is written for: if a future
release stops supporting it, the update preflight says so before you update (Settings -> System).

## 2. api.py (optional)

Every request to `/api/ext/<id>/<path>` calls:

```python
def handle(ctx, method, path, query, body):
    ...
    return {...}            # sent as JSON (200)
    # or: return 404, {"error": "not_found", "message": "..."}   to choose the status code
```

| Argument | Value |
|---|---|
| `ctx` | same as for widgets: `id`, `workspace`, `state_dir`, `secret(name)`, `config` |
| `method` | `GET`, `POST`, `PUT`, `PATCH`, `DELETE` |
| `path` | the part after `/api/ext/<id>/` (e.g. `notes`, `notes/42`) |
| `query` | query-string parameters as a dict |
| `body` | parsed JSON (or text), `None` for GET; max 5 MB |

It runs in a worker thread with a 30-second limit. Requests are authenticated by the app: only a
signed-in user can call it.

Example:

```python
import json
import time
from pathlib import Path


def handle(ctx, method, path, query, body):
    f = Path(ctx["state_dir"]) / "notes.json"
    notes = json.loads(f.read_text()) if f.exists() else []
    if path == "notes" and method == "GET":
        return {"notes": notes}
    if path == "notes" and method == "POST":
        text = str((body or {}).get("text", "")).strip()[:500]
        if text:
            notes.insert(0, {"text": text, "at": time.time()})
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(notes[:200]))
            tmp.replace(f)
        return {"notes": notes}
    return 404, {"error": "not_found", "message": f"{method} {path}"}
```

## 3. page.js

The app loads `/ext/<id>/page.js` and calls `mount(el, ctx)`:

| `ctx` | |
|---|---|
| `api(path, opts?)` | calls `/api/ext/<id>/<path>` with authentication and CSRF header; `opts = {method, body}` (body is sent as JSON); resolves to the parsed JSON, rejects on HTTP errors |
| `navigate(route)` | go to another page of the app, e.g. `navigate("/tasks")`; `/sessions?path=<topic path>&new=1&prompt=<text>` opens a new session with the text typed in |
| `theme` | `"dark"` or `"light"` |
| `lang` | the app's language, `"en"` or `"fr"` |
| `t(key)` | translation helper of the app |
| `icon(name)` | an icon of the app as an `<svg>` element (same names as the manifest `icon`), e.g. `button.prepend(ctx.icon("plus"))` |

Return a cleanup function: it runs when the user leaves the page.

For security the app only runs scripts it serves itself: `page.js` cannot add inline `<script>` tags to the page
nor build code from text (`eval`); split the code into modules of the extension folder instead. HTML widgets keep
working as before.

The module is downloaded once per version of `page.js` and kept: code at the top of the file runs once,
`mount` runs at every visit. Saving `page.js` gives it a new version, picked up at the next visit.

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

### Styling

The page gets the app's **UI kit**: CSS classes that look exactly like the rest of the app and follow the theme,
the accent color and the density by themselves. Prefer them to hand-written styles:

| Classes | |
|---|---|
| `ui-page` `ui-section` `ui-grid` `ui-row` `ui-stack` `ui-spacer` | layout: page column, section, responsive grid of cards, row, column |
| `ui-h1` `ui-h2` `ui-h3` `ui-text` `ui-muted` `ui-small` `ui-label` `ui-num` | text (title, section title, body, secondary, labels, figures in columns) |
| `ui-card` `ui-card-header` `ui-card-footer` | a card; the header takes an `ui-icon-box` and a `<div>` with the title and a line |
| `ui-tile` | a clickable card: `<button class="ui-tile"><div class="ui-icon-box">svg</div><div><b>Title</b><span>line</span></div></button>` |
| `ui-icon-box` (+ `ui-lg`, `ui-neutral`) | an icon on a soft square of the accent color |
| `ui-btn` (+ `ui-secondary` `ui-outline` `ui-ghost` `ui-danger`, `ui-sm`, `ui-icon-only`) | buttons (`ui-btn` alone = main action) |
| `ui-field` `ui-label` `ui-input` `ui-select` `ui-textarea` `ui-check` | forms |
| `ui-badge` `ui-dot` (+ `ui-success` `ui-warning` `ui-error` `ui-primary` `ui-outline`) | statuses |
| `ui-list` `ui-table` `ui-table-wrap` `ui-stat` `ui-stat-value` `ui-stat-label` `ui-progress` | data |
| `ui-steps` `ui-step-num` `ui-callout` (+ `ui-info` `ui-success` `ui-warning` `ui-error`) `ui-empty` `ui-skeleton` | steps, notices, empty and loading states |
| `ui-code` `ui-kbd` `ui-link` `ui-separator` | the rest |

Icons come from `ctx.icon(name)`; use them instead of emoji. Your own CSS always wins over the kit, and the app's
CSS variables are there for the rest: `--background`, `--foreground`, `--card`, `--border`, `--muted`,
`--muted-foreground`, `--primary`, `--primary-foreground`, `--success`, `--warning`, `--destructive`. HTML widgets
get the same kit. Inputs of the kit are 16 px on phones (no zoom on iPhone).

## 4. Test and load

- Python side: call `handle()` directly (see the test snippet in
  [Dashboard widgets](dashboard-widgets), with `api.handle(ctx, "GET", "notes", {}, None)`).
- JavaScript syntax: `node --check page.js` if Node is installed.
- **Settings -> Extensions -> Reload**, then open the page from the sidebar (Extensions, or its own entry once pinned). Errors appear on the
  extension's row.

