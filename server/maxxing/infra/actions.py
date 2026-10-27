"""Recipes that create things on this server, the standard way (CLI `maxxing infra`, skill `maxxing-infra`):

- PostgreSQL: `db install` (apt, listens on localhost only), `db create NAME` (one role + one database per app, its
  URL in the vault as DB_<NAME>_URL), `db backup` (pg_dump of every database + the declared SQLite files into
  /var/backups/maxxing-db, 7 per database; the job "Infra: database backups" runs it every night).
- Garage (S3 storage): `bucket install` (static binary, single node, every port on 127.0.0.1), `bucket create NAME
  [--public]` (bucket + its own key in the vault as S3_<NAME>_*; public = a path site that serves its files).
- Other servers: `server add` (tests the SSH probe first).

Commands run without a shell and never put a secret on a command line (passwords go through stdin).
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import secrets
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import httpx

from .. import config

DB_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}\Z")
BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}\Z")
KEEP_BACKUPS = 7
GARAGE_VERSION = "v2.1.0"
GARAGE_URL = "https://garagehq.deuxfleurs.fr/_releases/{v}/{arch}-unknown-linux-musl/garage"
# sha256 of each official static build (audit F18: Garage publishes no checksum, so these were taken from
# GARAGE_URL and cross-checked against the binary inside the official Docker image dxflrs/garage:v2.1.0)
GARAGE_SHA256 = {
    "x86_64": "543b0414d1464ab855ebe9b843938a5e5361fd24436891ce3dff9e03d02839d8",
    "aarch64": "65a1bedc9b6d5a2df788b55e81cb0013129326478fd94cf83a844ab278e8055f",
}
GARAGE_BIN = "/usr/local/bin/garage"
GARAGE_CONF = "/etc/garage.toml"
BACKUP_JOB = "Infra: database backups"


class ActionError(Exception):
    def __init__(self, message: str, code: str = "failed"):
        super().__init__(message)
        self.code = code


def _run(args: list[str], input: str | None = None, timeout: int = 60) -> tuple[int, str, str]:
    try:
        r = subprocess.run(args, input=input, capture_output=True, text=True, timeout=timeout, errors="replace",
                           env={**os.environ, "LC_ALL": "C", "DEBIAN_FRONTEND": "noninteractive"})
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"{args[0]}: not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{args[0]} took more than {timeout} s"


def _err(out: str, err: str) -> str:
    lines = [ln for ln in (err or out).strip().splitlines() if ln.strip()]
    return (lines[-1] if lines else "failed")[:300]


def backup_dir() -> Path:
    return Path(os.environ.get("MAXXING_INFRA_BACKUP_DIR", "/var/backups/maxxing-db"))


# ---- PostgreSQL ---------------------------------------------------------------------------------
def _psql(sql: str, db: str = "postgres", timeout: int = 30) -> tuple[int, str, str]:
    return _run(["runuser", "-u", "postgres", "--", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-At", "-F", "|", "-d", db],
                input=sql, timeout=timeout)


def pg_installed() -> bool:
    return bool(shutil.which("psql")) and _run(["systemctl", "is-active", "postgresql"])[1].strip() == "active"


def pg_install() -> dict:
    if pg_installed():
        return {"installed": True, "already": True}
    code, out, err = _run(["apt-get", "install", "-y", "-q", "postgresql"], timeout=900)
    if code != 0:
        _run(["apt-get", "update", "-q"], timeout=300)
        code, out, err = _run(["apt-get", "install", "-y", "-q", "postgresql"], timeout=900)
    if code != 0:
        raise ActionError("apt-get install postgresql failed: " + _err(out, err), "install_failed")
    _run(["systemctl", "enable", "--now", "postgresql"], timeout=60)
    code, out, _ = _psql("show listen_addresses;")
    listen = out.strip()
    if listen not in ("localhost", "127.0.0.1", "", "localhost,127.0.0.1"):
        raise ActionError(f"PostgreSQL listens on '{listen}': set listen_addresses = 'localhost'", "exposed")
    ensure_backup_job()
    return {"installed": True, "already": False, "listen": listen or "localhost"}


def pg_databases() -> list[str]:
    code, out, err = _psql("select datname from pg_database where not datistemplate order by 1;")
    if code != 0:
        raise ActionError("cannot list the databases: " + _err(out, err), "psql_failed")
    return [x for x in out.split() if x]


def pg_create(name: str, project: str | None = None) -> dict:
    from .. import vault
    from . import registry
    if not DB_NAME_RE.match(name or ""):
        raise ActionError("database names use a-z, 0-9 and _, start with a letter (2-41 characters)", "invalid_name")
    if not pg_installed():
        raise ActionError("PostgreSQL is not installed: run `maxxing infra db install` first", "not_installed")
    if name in pg_databases():
        raise ActionError(f"a database named {name} already exists", "exists")
    code, out, err = _psql(f"select 1 from pg_roles where rolname = '{name}';")
    if out.strip():
        raise ActionError(f"a PostgreSQL role named {name} already exists (another app?): pick another name", "exists")
    pw = secrets.token_urlsafe(24)
    code, out, err = _psql(f'create role "{name}" login password \'{pw}\';')
    if code != 0:
        raise ActionError("cannot create the role: " + _err(out, err), "psql_failed")
    code, out, err = _psql(f'create database "{name}" owner "{name}";')
    if code != 0:
        raise ActionError("cannot create the database: " + _err(out, err), "psql_failed")
    key = f"DB_{name.upper()}_URL"
    vault.put(key, f"postgresql://{name}:{pw}@127.0.0.1:5432/{name}", note=f"PostgreSQL database {name} (maxxing infra)",
              expose=False)
    rid = f"db:local:postgres:native:{name}"
    registry.declare(rid, kind="database", name=name, server="local", project=project, vault_keys=[key],
                     recipe={"engine": "postgres"})
    ensure_backup_job()
    return {"id": rid, "name": name, "vault_key": key, "url_hint": f"postgresql://{name}:…@127.0.0.1:5432/{name}"}


def ensure_backup_job() -> dict | None:
    from .. import crons
    for j in crons.list_jobs():
        if j.get("kind") == "shell" and "maxxing infra db backup" in (j.get("command") or ""):
            return None
    return crons.create_job({"name": BACKUP_JOB, "schedule": "30 3 * * *", "kind": "shell",
                             "command": "maxxing infra db backup", "notify": "failure", "timeout_s": 3600})


def _rotate(prefix: str) -> None:
    files = sorted(backup_dir().glob(f"{prefix}-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP_BACKUPS:]:
        old.unlink(missing_ok=True)


def backup_all() -> list[dict]:
    """Dump every local PostgreSQL database (not the `postgres` one) and every declared SQLite file."""
    from . import registry
    d = backup_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    stamp = time.strftime("%Y%m%d-%H%M")
    results: list[dict] = []
    if pg_installed():
        for db in [x for x in pg_databases() if x != "postgres"]:
            rid = f"db:local:postgres:native:{db}"
            target = d / f"pg-{db}-{stamp}.dump"
            with open(target, "wb") as fh:
                try:
                    r = subprocess.run(["runuser", "-u", "postgres", "--", "pg_dump", "-Fc", db], stdout=fh,
                                       stderr=subprocess.PIPE, timeout=3000)
                    ok, err = r.returncode == 0, r.stderr.decode(errors="replace").strip()[-300:]
                except subprocess.TimeoutExpired:
                    ok, err = False, "pg_dump took too long"
            os.chmod(target, 0o600)
            if not ok:
                target.unlink(missing_ok=True)
            else:
                _rotate(f"pg-{db}")
            results.append({"id": rid, "name": db, "ok": ok, "file": str(target) if ok else None,
                            "size": target.stat().st_size if ok else None, "error": None if ok else err, "at": int(time.time())})
    for rid, r in registry.resources().items():
        p = (r.get("details") or {}).get("path")
        if not rid.startswith("db:local:sqlite:") or not p:
            continue
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(p).name)
        target = d / f"sqlite-{safe}-{stamp}.db"
        try:
            src = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
            dst = sqlite3.connect(target)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            os.chmod(target, 0o600)
            _rotate(f"sqlite-{safe}")
            results.append({"id": rid, "name": Path(p).name, "ok": True, "file": str(target), "size": target.stat().st_size,
                            "error": None, "at": int(time.time())})
        except (sqlite3.Error, OSError) as e:
            target.unlink(missing_ok=True)
            results.append({"id": rid, "name": Path(p).name, "ok": False, "file": None, "size": None, "error": str(e)[:300],
                            "at": int(time.time())})
    state = config.read_json(config.state_dir("infra") / "backups.json", {}) or {}
    for x in results:
        state[x["id"]] = {k: x[k] for k in ("ok", "at", "file", "size", "error")}
    config.write_json(config.state_dir("infra") / "backups.json", state)
    return results


def declare_sqlite(path: str, project: str | None = None) -> dict:
    from . import registry
    p = Path(path).expanduser().resolve()
    try:
        with open(p, "rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                raise ActionError(f"{p} is not a SQLite database", "invalid_file")
    except OSError:
        raise ActionError(f"no file at {p}", "invalid_file") from None
    rid = f"db:local:sqlite:{p}"
    registry.declare(rid, kind="database", name=p.name, server="local", project=project, details={"path": str(p)},
                     recipe={"engine": "sqlite"})
    ensure_backup_job()
    return {"id": rid, "path": str(p)}


# ---- Garage -------------------------------------------------------------------------------------
def garage_installed() -> bool:
    return Path(GARAGE_BIN).exists() and Path(GARAGE_CONF).exists()


def _garage(*args: str, timeout: int = 60) -> tuple[int, str, str]:
    return _run([GARAGE_BIN, "-c", GARAGE_CONF, *args], timeout=timeout)


def garage_install() -> dict:
    if garage_installed() and _garage("status")[0] == 0:
        return {"installed": True, "already": True}
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(platform.machine().lower())
    if not arch:
        raise ActionError(f"no Garage build for {platform.machine()}", "unsupported")
    if not Path(GARAGE_BIN).exists():
        url = GARAGE_URL.format(v=GARAGE_VERSION, arch=arch)
        tmp = Path(GARAGE_BIN + ".part")
        tmp.unlink(missing_ok=True)
        h = hashlib.sha256()
        try:
            with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
                if r.status_code != 200:
                    raise ActionError(f"download failed ({r.status_code}): {url}", "download_failed")
                # 0700 and exclusive: nobody runs or swaps the file before it is verified
                with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700), "wb") as f:
                    for chunk in r.iter_bytes():
                        h.update(chunk)
                        f.write(chunk)
        except httpx.HTTPError as e:
            tmp.unlink(missing_ok=True)
            raise ActionError(f"download failed: {type(e).__name__}", "download_failed") from None
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        if h.hexdigest() != GARAGE_SHA256[arch]:
            tmp.unlink(missing_ok=True)
            raise ActionError(f"the Garage download does not match its pinned sha256 ({url}): nothing was installed",
                              "checksum_mismatch")
        tmp.chmod(0o755)
        tmp.rename(GARAGE_BIN)
    if not Path(GARAGE_CONF).exists():
        conf = f"""# Garage (S3 storage) - written by `maxxing infra bucket install`; every port listens on 127.0.0.1
metadata_dir = "/var/lib/garage/meta"
data_dir = "/var/lib/garage/data"
db_engine = "sqlite"
replication_factor = 1
rpc_bind_addr = "127.0.0.1:3901"
rpc_public_addr = "127.0.0.1:3901"
rpc_secret = "{secrets.token_hex(32)}"

[s3_api]
s3_region = "garage"
api_bind_addr = "127.0.0.1:3900"
root_domain = ".s3.garage.localhost"

[s3_web]
bind_addr = "127.0.0.1:3902"
root_domain = ".web.garage.localhost"
index = "index.html"

[admin]
api_bind_addr = "127.0.0.1:3903"
admin_token = "{secrets.token_urlsafe(32)}"
"""
        # created 600 (secrets inside): never readable by others, not even between a write and a chmod
        fd = os.open(GARAGE_CONF, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(conf)
        os.chmod(GARAGE_CONF, 0o600)
    for sub in ("meta", "data"):
        Path("/var/lib/garage", sub).mkdir(parents=True, exist_ok=True)
    unit = Path("/etc/systemd/system/garage.service")
    if not unit.exists():
        unit.write_text("[Unit]\nDescription=Garage S3 storage (maxxing infra)\nAfter=network-online.target\n\n"
                        f"[Service]\nEnvironment=RUST_LOG=garage=warn\nExecStart={GARAGE_BIN} -c {GARAGE_CONF} server\n"
                        "Restart=always\n\n[Install]\nWantedBy=multi-user.target\n")
    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", "--now", "garage"])
    node = ""
    for _ in range(30):
        code, out, _ = _garage("node", "id", "-q", timeout=10)
        if code == 0 and out.strip():
            node = out.strip().split("@")[0]
            break
        time.sleep(1)
    if not node:
        raise ActionError("Garage did not start: journalctl -u garage -n 50", "start_failed")
    code, out, _ = _garage("layout", "show")
    if "No nodes" in out or node[:16] not in out or "Current cluster layout version: 0" in out:
        free_gb = max(1, int(shutil.disk_usage("/var/lib/garage").free / 1e9 * 0.8))
        code, out, err = _garage("layout", "assign", "-z", "dc1", "-c", f"{free_gb}G", node[:16])
        if code != 0:
            raise ActionError("garage layout assign failed: " + _err(out, err), "layout_failed")
        code, out, err = _garage("layout", "apply", "--version", "1")
        if code != 0 and "version" not in (out + err):
            raise ActionError("garage layout apply failed: " + _err(out, err), "layout_failed")
    return {"installed": True, "already": False, "node": node[:16], "version": GARAGE_VERSION}


def bucket_create(name: str, public: bool = False, project: str | None = None) -> dict:
    from .. import vault
    from . import registry
    if not BUCKET_RE.match(name or ""):
        raise ActionError("bucket names use a-z, 0-9 and -, 3 to 63 characters", "invalid_name")
    if not garage_installed():
        raise ActionError("Garage is not installed: run `maxxing infra bucket install` first", "not_installed")
    code, out, err = _garage("bucket", "create", name)
    if code != 0:
        raise ActionError("garage bucket create failed: " + _err(out, err), "garage_failed")
    code, out, err = _garage("key", "create", f"{name}-key")
    if code != 0:
        raise ActionError("garage key create failed: " + _err(out, err), "garage_failed")
    kid = re.search(r"Key ID:\s*(\S+)", out)
    sec = re.search(r"Secret key:\s*(\S+)", out)
    if not (kid and sec):
        raise ActionError("could not read the new key from garage's output", "garage_failed")
    code, out, err = _garage("bucket", "allow", "--read", "--write", "--owner", name, "--key", f"{name}-key")
    if code != 0:
        raise ActionError("garage bucket allow failed: " + _err(out, err), "garage_failed")
    up = name.upper().replace("-", "_")
    keys = {f"S3_{up}_ACCESS_KEY_ID": kid.group(1), f"S3_{up}_SECRET_ACCESS_KEY": sec.group(1),
            f"S3_{up}_ENDPOINT": "http://127.0.0.1:3900", f"S3_{up}_BUCKET": name, f"S3_{up}_REGION": "garage"}
    for k, v in keys.items():
        vault.put(k, v, note=f"Garage bucket {name} (maxxing infra)", expose=False)
    urls: list[str] = []
    if public:
        code, out, err = _garage("bucket", "website", "--allow", name)
        if code != 0:
            raise ActionError("garage bucket website failed: " + _err(out, err), "garage_failed")
        from . import caddy
        site = caddy.add_site(name, port=3902, upstream_host=f"{name}.web.garage.localhost", project=project, kind="bucket")
        urls.append(site["url"])
    rid = f"bucket:local:garage:{name}"
    registry.declare(rid, kind="bucket", name=name, server="local", project=project, urls=urls, vault_keys=sorted(keys),
                     recipe={"engine": "garage", "public": public})
    return {"id": rid, "name": name, "vault_keys": sorted(keys), "endpoint": "http://127.0.0.1:3900", "public_url": urls[0] if urls else None}


# ---- servers ------------------------------------------------------------------------------------
def server_add(name: str, host: str, user: str = "root", port: int = 22, key: str = "", note: str = "",
               force: bool = False, label: str = "") -> dict:
    from . import probe_remote, registry
    s = {"name": name, "host": host, "user": user, "port": port, "key": key}
    registry.check_server(name, host, user, port, key)
    res = probe_remote(s, {"sqlite_roots": []})
    if res.get("error") and not force:
        raise ActionError(f"cannot read {user}@{host}: {res['error']}", "unreachable")
    registry.add_server(name, host, user, port, key, note, label)
    sv = res.get("server") or {}
    return {"name": name, "ok": not res.get("error"), "error": res.get("error"), "hostname": sv.get("hostname"),
            "os": sv.get("os"), "sites": len(res.get("sites") or []), "databases": len(res.get("databases") or [])}
