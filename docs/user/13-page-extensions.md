---
section: Extending
---
# Page extensions

A page extension adds a full page to the app, served at `/x/<id>`. It is a plain JavaScript
module – no build step – plus an optional Python API.

Where it appears: every page is listed on the **Extensions** page (`/x`), reached from Settings -> Pages -> **All
pages**, from **Extensions** in the search (Ctrl K) and, while a page is not pinned, from **Extensions** at the end of
the sidebar's pages (a tile of the ⊞ menu on a phone). Click the **pin** at the top right of a page (or on the Extensions page, or
turn on **In the sidebar** in Settings -> Pages) to give it its own sidebar entry, with the other pages; click it again
to unpin.

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
an ordinary extension: delete its folder, or turn it off in Settings -> Pages, when you no longer need it
- updates do not bring it back.

## 1. manifest.json

```json
{"id": "notes-board", "name": "Notes board", "type": "page", "icon": "sticky-note", "version": "1.0.0"}
```

`name` can also be `{"en": "Notes board", "fr": "Tableau de notes"}`: the app shows the one of its language.
`"api": 1` (optional, default 1) is the version of the extension contract the page is written for: if a future
release stops supporting it, the update preflight says so before you update (Settings -> Updates).

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
- **Settings -> Pages -> Rescan**, then open the page from **All pages** there (or its own sidebar entry once pinned). Errors appear on the
  extension's row.


## Office views of the Agents page

An extension can also bring a **view of the Office** (the overview of the Agents page): it is listed in the Office's
view menu after Classic and Space. **Create my custom view**, at the end of that menu, opens a session
that builds one with you.

```
/root/maxxing/extensions/mission-control/
  manifest.json      {"id": "mission-control", "name": "Mission control", "type": "view", "icon": "radar",
                      "version": "1.0.0", "api": 1,
                      "agents_view": {"name": {"en": "Mission control", "fr": "Contrôle de mission"}, "icon": "radar"}}
  agents-view.html   the view (one self-contained file, like an HTML widget)
  api.py             optional: its own API, as for any extension
```

- `"agents_view"`: `{"name", "icon"}` (both optional: the extension's own by default) or simply `true`. It needs
  `agents-view.html` in the folder. `"type": "view"` is an extension that only brings views; a widget or a page can
  declare one too.
- `agents-view.html` runs in the same **sandboxed frame** as HTML widgets (scripts yes; no cookies, no storage, no
  direct access to the app), with the same UI kit, theme variables and `maxxing.api` / `maxxing.resize` /
  `maxxing.theme` / `maxxing.onTheme`, plus:

| In the frame | |
|---|---|
| `maxxing.onData(fn)` / `maxxing.data` | the Office, given at once and again at every change: `{lang, new_agent_route, projects: [{name, emoji, color, agents: [...]}]}`, projects and agents in the user's order, `color` = the project's color (hex). Each agent: `path`, `project`, `topic`, `name`, `display_name`, `description`, `enabled`, `model`, `status` (`running`, `waiting`, `unread`, `failed`, `off`, `idle`), `status_text` (in the UI language), `running`, `waiting`, `unread`, `cost_today`, `last_run` (`{at, kind, ok, text}`, text cut at 300 characters), `avatar` (its 6 parts), `avatar_svg` (its pixel character as SVG markup: `img.src = "data:image/svg+xml," + encodeURIComponent(a.avatar_svg)`), `route` (its page), `chat_route` (its conversation, opened next to the Office), `enterprise`, `position`, `reports_to` (the ids of its enterprise, of the position it holds and of its lead's position; `null` when it holds no position, when Enterprises is off, and `reports_to` for a position that reports to the top) |
| `maxxing.navigate(route)` | opens a route of the Agents page: an agent's `route` or `chat_route`, or `new_agent_route` (New agent); other routes are ignored |
| `maxxing.app(path)` | a read-only GET of `/api/agents/layout` (the raw order and colors); any other path is refused |

- The frame grows with `maxxing.resize(px)` (up to 6000 px). Make it work in light and dark (`maxxing.theme`) and on
  a phone.
- What the view sees: your agents' names, roles, states and the start of their last results. As for any extension,
  it is code you trust: do not load scripts from sites you do not trust.
- If the extension is turned off, deleted or in error, the Office shows Classic (the choice comes back with it).

## 5. Community extensions

The [community library](https://harness-maxxing.com/community) lists extensions, widgets and skills written by other
people, kept in their own GitHub repositories and maintained by their authors. Each listing gives a request to copy
into a session ("Install the community extension from …"): Claude reads the code at the commit we reviewed, tells you
what it does, then installs it.

> **Not made by the Harness Maxxing maintainers: install them at your own risk.** We check that a listing looks right
> before it appears, not the code. An extension's `api.py` runs inside the Harness server, with the server's rights
> (root on a standard install): it can read your files, your keys and your sessions. Listings with an `api.py` say
> **Runs code on the server**. Read the code first, and install only what comes from someone you trust.

To install one by hand, copy its folder to `/root/maxxing/extensions/<id>/` (for example with `git clone`), then
**Settings -> Pages -> Rescan**. If it ships a skill, link it once so Claude always reads the current one
(a `git pull` of the extension updates it too):
`ln -s /root/maxxing/extensions/<id>/skill/<name> /root/maxxing/.claude/skills/<name>`. To remove it, delete the
folder and that link.

Listed here before the library opened:

| Extension | What it does | Author |
|---|---|---|
| [Dokploy](https://github.com/Anthony14FR/harness-maxxing-dokploy) | A Dokploy page (projects, apps, domains, deployment logs, deploy after a confirmation) and a skill so sessions deploy, read logs and add domains, asking first | [Anthony14FR](https://github.com/Anthony14FR) |

### Publish yours

Push it to a public GitHub repository, then list it on
[harness-maxxing.com/community](https://harness-maxxing.com/community/account) (sign in with GitHub). Every listing is
reviewed before it appears. To let Claude do it for you (repository, README, screenshots, listing), create an API key
on that page, save it in **Settings -> Keys** as `HM_COMMUNITY_KEY`, and ask in a session: *"Publish my extension
`<id>` to the Harness Maxxing community: follow https://harness-maxxing.com/community/publish.md"*. The full guide:
[harness-maxxing.com/community/publish](https://harness-maxxing.com/community/publish). A listing that no longer follows
these rules is removed:

- a public repository of its own, with its licence, that you maintain;
- `id`: lowercase letters, digits and dashes, not taken by a stock extension;
- `name` in English and French (`{"en": "…", "fr": "…"}`), `"api": 1` in the manifest;
- no key or secret in the code, the page or the session environment: the user types it in **Settings -> Keys** and
  `api.py` reads it with `ctx.secret()` (the key stays *not exposed* to sessions unless they need the variable);
- anything that changes an outside service (deploy, delete, pay, send) is shown to the user and runs only once they
  agree;
- a skill shipped with it: Claude Code does not read skills from extension folders, so the README gives the
  `ln -s` line above (a link, not a copy, so the skill never goes stale);
- a README that says what it does, what it sends where, and how to remove it.
