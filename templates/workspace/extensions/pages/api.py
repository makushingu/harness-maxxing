"""The topic where the examples open a new session (also a minimal example of an extension API)."""
from pathlib import Path


def handle(ctx, method, path, query, body):
    ws = Path(ctx["workspace"])
    for topic in ("projects/system/topics/harness", "projects/system/topics/update", "projects/general/topics/inbox"):
        if (ws / topic).is_dir():
            return {"topic": topic}
    return {"topic": ""}
