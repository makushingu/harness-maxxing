"""The infra registry: `<workspace>/infra.json`, what we decided (the snapshot is what exists).

    {"version": 1,
     "servers":   [{"name", "label", "host", "user", "port", "key", "note"}], other servers read over SSH
     "resources": {"<id>": {"kind", "name", "server", "project", "note", "hidden", "declared", "created", ...}},
     "domains":   ["example.com"]}                                                 domains added by hand (any registrar)

A resource id is the one the snapshot computes (`site:<server>:<host><path>`, `db:<server>:postgres:native:<name>`...),
so a declared resource and a discovered one merge. A server's `name` is part of those ids and never changes; its
`label` is what the page shows ("VPS Hostinger") and can be renamed at will. `declared: true` = created by a recipe (`maxxing infra ...`): the
page reports it as missing when the snapshot no longer finds it. Annotations (project, note, hidden) can be set on any
id. Never holds a secret: credentials live in the vault, the registry only names their keys.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from .. import config

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$")
_lock = threading.Lock()


class RegistryError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def path() -> Path:
    return config.workspace() / "infra.json"


def load() -> dict:
    d = config.read_json(path(), None)
    if not isinstance(d, dict):
        d = {}
    # infra.json can be written by hand or by a turn: an entry the CLI would refuse is ignored, never run through ssh
    raw = [s for s in d.get("servers") or [] if isinstance(s, dict)]
    servers = [s for s in raw if _server_ok(s)]
    res = {k: v for k, v in (d.get("resources") or {}).items() if isinstance(v, dict)}
    doms = [x for x in d.get("domains") or [] if isinstance(x, str) and DOMAIN_RE.match(x)]
    out = {**d, "version": 1, "servers": servers, "resources": res, "domains": doms}
    refused = [s for s in raw if s not in servers]
    if refused:
        out[_REFUSED] = refused
    return out


_REFUSED = "_refused_servers"


def _save(d: dict) -> None:
    """Writes back the entries load() ignored too: a refused hand-written server stays in the file (to fix), it
    is only never used."""
    d = dict(d)
    refused = d.pop(_REFUSED, None) or []
    names = {s.get("name") for s in d.get("servers") or []}
    d["servers"] = [*(d.get("servers") or []), *(s for s in refused if s.get("name") not in names)]
    config.write_json(path(), d)


# ---- servers ------------------------------------------------------------------------------------
def servers() -> list[dict]:
    return load()["servers"]


def get_server(name: str) -> dict | None:
    return next((s for s in servers() if s["name"] == name), None)


def _server_ok(s: dict) -> bool:
    try:
        check_server(str(s.get("name") or ""), str(s.get("host") or ""), str(s.get("user") or "root"),
                     int(s.get("port") or 22), str(s.get("key") or ""), key_must_exist=False)
        return True
    except (RegistryError, ValueError, TypeError):
        return False


def check_server(name: str, host: str, user: str = "root", port: int = 22, key: str = "", key_must_exist: bool = True) -> None:
    if not NAME_RE.match(name or "") or name == "local":
        raise RegistryError("server names use a-z, 0-9 and -, max 40 characters (not 'local')", "invalid_name")
    if not re.match(r"^[A-Za-z0-9.:\[\]][A-Za-z0-9.:\-\[\]]{0,252}$", host or ""):
        raise RegistryError("host must be an IP address or a host name", "invalid_host")
    if not re.match(r"^[a-z_][a-z0-9_.-]{0,31}$", user or ""):
        raise RegistryError("invalid SSH user", "invalid_user")
    if not 1 <= int(port) <= 65535:
        raise RegistryError("invalid SSH port", "invalid_port")
    if key and (key.startswith("-") or "\n" in key):
        raise RegistryError("invalid SSH key path", "invalid_key")
    if key and key_must_exist and not Path(key).is_file():
        raise RegistryError(f"no SSH key at {key}", "invalid_key")


def add_server(name: str, host: str, user: str = "root", port: int = 22, key: str = "", note: str = "",
               label: str = "") -> dict:
    check_server(name, host, user, port, key)
    item = {"name": name, "label": clean_label(label), "host": host, "user": user, "port": int(port), "key": key,
            "note": note, "added": int(time.time())}
    with _lock:
        d = load()
        d["servers"] = [s for s in d["servers"] if s["name"] != name] + [item]
        _save(d)
    return item


def clean_label(label: str | None) -> str:
    return re.sub(r"\s+", " ", label or "").strip()[:60]


def rename_server(name: str, label: str) -> dict:
    with _lock:
        d = load()
        s = next((x for x in d["servers"] if x["name"] == name), None)
        if s is None:
            raise RegistryError(f"no server named {name}", "not_found")
        s["label"] = clean_label(label)
        _save(d)
    return s


def free_name(base: str) -> str:
    """A server name from a host name or a label: `srv100200.hstgr.cloud` -> `srv100200`, unique."""
    stem = re.sub(r"[^a-z0-9-]+", "-", (base or "").lower().split(".")[0]).strip("-")[:36] or "server"
    if stem == "local" or not stem[0].isalnum():
        stem = f"server-{stem}".strip("-")[:36]
    taken = {s["name"] for s in servers()}
    name, n = stem, 2
    while name in taken:
        name, n = f"{stem}-{n}", n + 1
    return name


def remove_server(name: str) -> bool:
    with _lock:
        d = load()
        before = len(d["servers"])
        d["servers"] = [s for s in d["servers"] if s["name"] != name]
        if len(d["servers"]) == before:
            return False
        _save(d)
    return True


# ---- domains added by hand ------------------------------------------------------------------------
def clean_domain(name: str) -> str:
    n = (name or "").strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0].strip(".")
    try:
        n = n.encode("idna").decode() if n and not n.isascii() else n
    except UnicodeError:                       # an empty or too long label ("é..com")
        raise RegistryError("not a domain name (example: example.com)", "invalid_domain") from None
    if not DOMAIN_RE.match(n):
        raise RegistryError("not a domain name (example: example.com)", "invalid_domain")
    return n


def add_domain(name: str) -> str:
    n = clean_domain(name)
    with _lock:
        d = load()
        if n not in d["domains"]:
            d["domains"] = sorted(d["domains"] + [n])
            _save(d)
    return n


def remove_domain(name: str) -> bool:
    n = (name or "").strip().lower()
    with _lock:
        d = load()
        if n not in d["domains"]:
            return False
        d["domains"] = [x for x in d["domains"] if x != n]
        _save(d)
    return True


# ---- resources ----------------------------------------------------------------------------------
def resources() -> dict[str, dict]:
    return load()["resources"]


def declare(rid: str, **fields) -> dict:
    """Record a resource made by a recipe (merged with what was there)."""
    with _lock:
        d = load()
        cur = d["resources"].get(rid, {})
        cur.update({k: v for k, v in fields.items() if v is not None})
        cur.setdefault("created", int(time.time()))
        cur["declared"] = True
        d["resources"][rid] = cur
        _save(d)
    return cur


def annotate(rid: str, project: str | None = None, note: str | None = None, hidden: bool | None = None) -> dict:
    with _lock:
        d = load()
        cur = d["resources"].get(rid, {})
        if project is not None:
            cur["project"] = project.strip().strip("/") or None
        if note is not None:
            cur["note"] = note.strip()[:500]
        if hidden is not None:
            cur["hidden"] = bool(hidden)
        cur = {k: v for k, v in cur.items() if v not in (None, "", False) or k == "declared"}
        if cur:
            d["resources"][rid] = cur
        else:
            d["resources"].pop(rid, None)
        _save(d)
    return cur


def forget(rid: str) -> bool:
    with _lock:
        d = load()
        if d["resources"].pop(rid, None) is None:
            return False
        _save(d)
    return True
