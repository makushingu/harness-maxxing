# Extensions

Each sub-folder here is an extension of Harness Maxxing: a dashboard **widget** or a full **page**.
They live in your workspace, so updates of the product never touch them, and they are included in
the memory backup.

```
extensions/
  my-widget/
    manifest.json   {"id": "my-widget", "name": "My widget", "type": "widget", "icon": "gauge", "version": "1.0.0"}
    api.py          def card(ctx) -> dict   (returns a Card)
  my-page/
    manifest.json   {"id": "my-page", "name": "My page", "type": "page", "icon": "layout", "version": "1.0.0"}
    api.py          def handle(ctx, method, path, query, body) -> dict   (optional)
    page.js         export function mount(el, ctx) { ...; return () => {} }
```

Pages and HTML widgets get the app's UI kit (`ui-card`, `ui-btn`, `ui-input`, `ui-badge`... and `ctx.icon(name)`
in a page): use it and they look like the rest of the app, in dark and light. See the "Page extensions" guide.

After adding or editing an extension: **Settings -> Extensions -> Reload**.

Guides (in the app: Settings -> Docs): "Dashboard widgets" and "Page extensions".
Quickest way: open a session and ask Claude "create a widget that shows ..." - the
`maxxing-extension` skill knows the format.
