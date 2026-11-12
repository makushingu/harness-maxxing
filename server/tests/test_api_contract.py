"""docs/dev/API.md is the HTTP contract: every route the server answers has its row there."""
from __future__ import annotations

import importlib
import re
from pathlib import Path

from fastapi.routing import APIRoute, APIWebSocketRoute

API_MD = Path(__file__).resolve().parents[2] / "docs" / "dev" / "API.md"
NOT_ROWS = {"/api/stream", "/api/{rest:path}"}   # the Global bus section (text, not a row); the JSON 404 for the rest
KNOWN_MISSING = {"POST /api/agents/{project}/{topic}/{name}/chat/new"}   # agents' conversation: being reworked
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _variants(path: str) -> list[tuple[str, bool]]:
    """(path, listed) for each path a row stands for: `[/{id}]` optional, `<x>` = a parameter, `a\\|b` or `{a\\|b}`
    alternatives of the last word (`listed`: that word is one of the values a parameter takes)."""
    path = re.sub(r"<[^>]+>", "{}", path.split("?")[0])
    path = re.sub(r"\{([^}]*\\\|[^}]*)\}", r"\1", path)           # {start\|stop} = start\|stop
    out = [path.replace("[", "").replace("]", ""), re.sub(r"\[[^\]]*\]", "", path)] if "[" in path else [path]
    expanded = []
    for p in out:
        head, *alts = p.split("\\|")
        assert all("/" not in a for a in alts), f"an alternative spans words: {p}"
        expanded += [(v, bool(alts)) for v in [head] + [re.sub(r"[^/.]+$", alt, head) for alt in alts]]
    return [(re.sub(r"\{[^}]+\}", "{}", p), listed) for p, listed in expanded]


def _rows() -> list[tuple[set[str], str, bool]]:
    rows = []
    for m in re.finditer(r"^\| ([A-Z /]+?) \| `(/api/[^`]*)`", API_MD.read_text(encoding="utf-8"), re.M):
        methods = {x.strip() for x in m.group(1).split("/") if x.strip()}
        for p, listed in _variants(m.group(2)):
            rows.append((METHODS if "ANY" in methods else methods, p, listed))
    return rows


def _pattern(path: str, listed: bool) -> re.Pattern:
    """A whole-word `{param}` needs a `{}` in the row (or, last word of a row that lists values, one of them); one
    inside a word (`install.{kind}`) matches a literal too."""
    segs = path.split("/")
    parts = []
    for i, seg in enumerate(segs):
        if re.fullmatch(r"\{[^}]+\}", seg):
            parts.append(r"[^/]+" if listed and i == len(segs) - 1 else r"\{\}")
        else:
            parts.append(re.sub(r"\\\{[^}]*\\\}", r"[^/]+", re.escape(seg)))
    return re.compile("^" + "/".join(parts) + "$")


def _routes() -> list[tuple[str, str]]:
    """(METHOD or WS, path) of every route: the app's own and each router of maxxing.api.ROUTERS (in this FastAPI
    included routers are not flattened into app.routes; websockets and routes outside the OpenAPI schema count too)."""
    from maxxing.api import ROUTERS
    from maxxing.app import create_app
    found = list(create_app().routes)
    for name in ROUTERS:
        found += getattr(importlib.import_module(f"maxxing.api.{name}"), "router").routes
    out = set()
    for r in found:
        if isinstance(r, APIWebSocketRoute):
            out.add(("WS", r.path))
        elif isinstance(r, APIRoute):
            out |= {(m, r.path) for m in r.methods if m in METHODS}
    return sorted(out)


def test_every_route_has_its_row_in_api_md():
    rows = _rows()
    missing = [f"{method} {path}" for method, path in _routes()
               if path.startswith("/api/") and path not in NOT_ROWS and f"{method} {path}" not in KNOWN_MISSING
               and not any(method in methods and _pattern(path, listed).match(p) for methods, p, listed in rows)]
    assert not missing, "routes without a row in docs/dev/API.md:\n" + "\n".join(missing)
