"""Notes page - backend of a full-page extension.

The page (page.js) calls `ctx.api("notes")`, which reaches
`/api/ext/notes-page/notes` and is forwarded here:

    handle(ctx, method, path, query, body)
      method  "GET" | "POST" | "PUT" | "PATCH" | "DELETE"
      path    the part after /api/ext/notes-page/  (here "notes")
      query   dict of query-string parameters
      body    parsed JSON body (or None)

Return a dict/list (sent as JSON) or a `(status, dict)` tuple. Raise ValueError -> HTTP 400,
LookupError -> HTTP 404. The call runs in a worker thread: blocking I/O is fine.
"""
import json
import time
from pathlib import Path


def _file(ctx) -> Path:
    return Path(ctx["state_dir"]) / "notes.json"     # state_dir is created for you


def handle(ctx, method, path, query, body):
    if path != "notes":
        raise LookupError(f"unknown path {path!r}")
    f = _file(ctx)
    if method == "GET":
        return json.loads(f.read_text()) if f.exists() else {"text": "", "saved": None}
    if method == "PUT":
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            raise ValueError("send {\"text\": \"...\"}")
        data = {"text": body["text"][:100_000], "saved": time.time()}
        f.write_text(json.dumps(data))
        return data
    return 405, {"error": "method_not_allowed", "message": method}
