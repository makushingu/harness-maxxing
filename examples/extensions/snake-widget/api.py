"""Snake - backend of an HTML widget (optional: an HTML widget works without api.py).

widget.html calls `maxxing.api("best")` / `maxxing.api("best", {method: "PUT", body: {...}})`;
the dashboard forwards it to `/api/ext/snake-widget/best`, handled here.
"""
import json
from pathlib import Path


def _file(ctx) -> Path:
    return Path(ctx["state_dir"]) / "best.json"


def handle(ctx, method, path, query, body):
    if path != "best":
        raise LookupError(f"unknown path {path!r}")
    f = _file(ctx)
    best = json.loads(f.read_text()).get("best", 0) if f.exists() else 0
    if method == "GET":
        return {"best": best}
    if method == "PUT":
        score = int((body or {}).get("score", 0))
        if score > best:
            best = score
            f.write_text(json.dumps({"best": best}))
        return {"best": best}
    return 405, {"error": "method_not_allowed", "message": method}
