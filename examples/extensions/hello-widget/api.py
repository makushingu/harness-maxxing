"""Hello widget - the smallest useful dashboard widget.

Copy this folder to `<workspace>/extensions/hello-widget/`, then Settings > Extensions > Reload.

The dashboard calls `card(ctx)` (at most once per `ttl` seconds, see manifest.json) and renders
the returned Card with the product's own components - no HTML, no CSS, consistent design.

ctx = {
  "id":        "hello-widget",
  "workspace": "/root/maxxing",                          # Claude's workspace
  "state_dir": "/var/lib/claude-maxxing/extensions/hello-widget",   # private folder for your data
  "secret":    function(name) -> str | None,             # read a value from Settings > Keys
  "config":    {"timezone", "language", "public_url"},
}
Block types: stat, stats, list, chart, table, progress, markdown (see docs/dev/API.md).
Raise an exception and the dashboard shows the error on this card only.
"""
import datetime as dt
from pathlib import Path


def card(ctx):
    workspace = Path(ctx["workspace"])
    projects = workspace / "projects"
    names = sorted(p.name for p in projects.iterdir() if p.is_dir()) if projects.is_dir() else []
    today = dt.date.today()

    return {
        "title": "Hello",
        "status": "ok",                               # ok | warn | error (coloured dot)
        "blocks": [
            # two numbers side by side
            {"type": "stats", "items": [
                {"type": "stat", "label": "Projects", "value": len(names)},
                {"type": "stat", "label": "Day of year", "value": today.timetuple().tm_yday},
            ]},
            # a list; `href` makes an item clickable (SPA route or https:// URL)
            {"type": "list", "empty": "No project yet",
             "items": [{"title": n, "href": f"/files?path={projects / n}"} for n in names[:5]]},
            # a bar chart: one series, x = label, y = value
            {"type": "chart", "kind": "bar", "series": [{
                "name": "Letters in the project name",
                "points": [[n, len(n)] for n in names[:7]],
            }]},
        ],
    }
