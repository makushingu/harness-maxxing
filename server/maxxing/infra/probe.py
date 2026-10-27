"""Infra probe: a read-only inventory of ONE server, printed as JSON. Standalone and stdlib-only (Python >= 3.8): the
Infra page runs it on this server as a subprocess and on the other servers through `ssh host python3 - '<opts>'`
(the script on stdin), so the same code reads every machine. It never writes anything and never outputs a secret
(a Docker container's environment is only read for POSTGRES_USER / POSTGRES_DB, the Garage admin token is only used
to call the local admin API).

Output: {"version", "collected_at", "took_ms", "server": {...}, "sites": [...], "listeners": [...], "containers": [...],
"databases": [...], "buckets": [...], "errors": {section: message}}. See docs/dev/INTERNALS.md#infra.

Options (argv[1], JSON): {"sqlite_roots": [dirs], "sqlite_files": [paths], "budget_s": 25}.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

VERSION = 1
CADDY_API = os.environ.get("MAXXING_CADDY_API", "http://127.0.0.1:2019")
CADDYFILE = os.environ.get("MAXXING_CADDYFILE", "/etc/caddy/Caddyfile")
PRUNE = {"node_modules", ".git", "__pycache__", "venv", ".venv", "site-packages", "proc", "sys", "dev", "snap",
         "attachments", "trash", ".cache", ".npm", ".local", "dist", "build", "target", "vendor"}
SQLITE_EXT = (".db", ".sqlite", ".sqlite3")
SQLITE_MAGIC = b"SQLite format 3\x00"
VIRTUAL_IF = ("docker", "br-", "veth", "lo", "virbr", "cni", "flannel", "kube")
DB_IMAGES = {"postgres": "postgres", "postgis": "postgres", "timescale": "postgres", "pgvector": "postgres",
             "mysql": "mysql", "mariadb": "mariadb", "redis": "redis", "valkey": "redis", "mongo": "mongodb",
             "clickhouse": "clickhouse", "minio": "minio", "garage": "garage"}
PG_SQL = ("select datname, pg_database_size(datname), pg_get_userbyid(datdba) from pg_database "
          "where not datistemplate order by 1")


def run(args, timeout=8, env=None):
    """(returncode, stdout) of a fixed command; (-1, '') when missing or too slow."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, errors="replace",
                           env={**os.environ, "LC_ALL": "C", **(env or {})})
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""


def read(path, limit=65536):
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def http_json(url, headers=None, timeout=3):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - local admin APIs only
        return json.loads(r.read().decode() or "null")


# ---- server -------------------------------------------------------------------------------------
def server():
    out = {"hostname": socket.gethostname(), "kernel": os.uname().release, "cpus": os.cpu_count()}
    m = re.search(r'^PRETTY_NAME="?([^"\n]+)', read("/etc/os-release"), re.M)
    out["os"] = m.group(1) if m else ""
    try:
        out["uptime_s"] = int(float(read("/proc/uptime").split()[0]))
    except (IndexError, ValueError):
        out["uptime_s"] = None
    mem = dict(re.findall(r"^(\w+):\s+(\d+) kB", read("/proc/meminfo"), re.M))
    out["mem_total"] = int(mem.get("MemTotal", 0)) * 1024
    out["mem_available"] = int(mem.get("MemAvailable", 0)) * 1024
    try:
        du = shutil.disk_usage("/")
        out["disk_total"], out["disk_free"] = du.total, du.free
    except OSError:
        out["disk_total"] = out["disk_free"] = None
    try:
        out["load"] = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        out["load"] = None
    ips = []
    for fam in ("-4", "-6"):
        code, txt = run(["ip", "-j", fam, "addr"], timeout=4)
        try:
            for itf in json.loads(txt) if code == 0 else []:
                if itf.get("ifname", "").startswith(VIRTUAL_IF):
                    continue
                for a in itf.get("addr_info", []):
                    if a.get("scope") == "global" and a.get("local"):
                        ips.append({"ip": a["local"], "iface": itf.get("ifname")})
        except ValueError:
            pass
    out["ips"] = ips
    return out


# ---- processes, ports, containers ---------------------------------------------------------------
def unit_of(pid):
    """systemd unit (or docker container id) of a process, from its cgroup."""
    cg = read(f"/proc/{pid}/cgroup", 4096)
    m = re.search(r"docker[-/]([0-9a-f]{12,64})(?:\.scope)?", cg)
    if m:
        return {"container": m.group(1)[:12]}
    m = re.search(r"/([^/\n]+\.service)", cg)
    return {"unit": m.group(1)} if m else {}


def repo_of(path):
    """The git clone holding `path` (walks up 6 levels): {path, remote (no credentials), branch}."""
    p = os.path.abspath(path or "")
    for _ in range(7):
        if not p or p == "/":
            return None
        if os.path.isdir(os.path.join(p, ".git")):
            cfg = read(os.path.join(p, ".git", "config"))
            m = re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)', cfg, re.S)
            head = read(os.path.join(p, ".git", "HEAD")).strip()
            return {"path": p, "remote": re.sub(r"//[^/?#]*@", "//", m.group(1)) if m else None,
                    "branch": head[16:] if head.startswith("ref: refs/heads/") else None}
        p = os.path.dirname(p)
    return None


def listeners():
    code, txt = run(["ss", "-ltnpH"], timeout=5)
    out, seen = [], set()
    for line in txt.splitlines() if code == 0 else []:
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[3]
        addr, _, port = local.rpartition(":")
        try:
            port = int(port)
        except ValueError:
            continue
        addr = addr.strip("[]").split("%")[0]
        procs = re.findall(r'\("([^"]+)",pid=(\d+)', line)
        name, pid = (procs[0][0], int(procs[0][1])) if procs else (None, None)
        if name == "systemd" and len(procs) > 1:             # socket activation: the real server is next
            name, pid = procs[1][0], int(procs[1][1])
        key = (port, name)
        if key in seen:
            for x in out:
                if (x["port"], x["process"]) == key and addr not in x["addrs"]:
                    x["addrs"].append(addr)
            continue
        seen.add(key)
        item = {"port": port, "addrs": [addr], "process": name, "pid": pid}
        if pid:
            item.update(unit_of(pid))
            try:
                cwd = os.readlink(f"/proc/{pid}/cwd")
                if cwd != "/":
                    item["cwd"] = cwd
                    item["repo"] = repo_of(cwd)
            except OSError:
                pass
        out.append(item)
    return sorted(out, key=lambda x: x["port"])


def engine_of(image):
    base = image.split("@")[0].rsplit("/", 1)[-1].split(":")[0].lower()
    for k, v in DB_IMAGES.items():
        if k in base:
            return v
    return None


def containers():
    if not shutil.which("docker"):
        return []
    code, txt = run(["docker", "ps", "--no-trunc", "--format", "{{json .}}"], timeout=8)
    out = []
    for line in txt.splitlines() if code == 0 else []:
        try:
            c = json.loads(line)
        except ValueError:
            continue
        ports = []
        for m in re.finditer(r"(?:([\d.:\[\]a-f]+):)?(\d+)->(\d+)/(tcp|udp)", c.get("Ports", "")):
            ports.append({"host_ip": (m.group(1) or "").strip("[]"), "host": int(m.group(2)), "container": int(m.group(3)),
                          "proto": m.group(4)})
        labels = dict(kv.split("=", 1) for kv in (c.get("Labels") or "").split(",") if "=" in kv)
        item = {"id": c.get("ID", "")[:12], "name": c.get("Names", ""), "image": c.get("Image", ""),
                "status": c.get("Status", ""), "state": c.get("State", ""), "ports": ports,
                "engine": engine_of(c.get("Image", "")),
                "compose_project": labels.get("com.docker.compose.project"),
                "compose_dir": labels.get("com.docker.compose.project.working_dir")}
        if item["compose_dir"]:
            item["repo"] = repo_of(item["compose_dir"])
        out.append(item)
    return out


# ---- web servers --------------------------------------------------------------------------------
def _caddy_config():
    try:
        return http_json(CADDY_API.rstrip("/") + "/config/"), "api"
    except Exception:  # noqa: BLE001 - admin API off: adapt the Caddyfile instead
        pass
    if shutil.which("caddy") and os.path.exists(CADDYFILE):
        code, txt = run(["caddy", "adapt", "--config", CADDYFILE, "--adapter", "caddyfile"], timeout=10)
        if code == 0:
            try:
                return json.loads(txt), "caddyfile"
            except ValueError:
                pass
    return None, None


def _walk_routes(routes, ctx, found):
    ctx = dict(ctx)
    for route in routes or []:
        matches = route.get("match") or [{}]
        for m in matches:
            sub = dict(ctx)
            if m.get("host"):
                sub["hosts"] = m["host"]
            if m.get("path"):
                sub["paths"] = m["path"]
            for h in route.get("handle") or []:
                kind = h.get("handler")
                if kind == "vars" and h.get("root"):
                    sub["root"] = h["root"]
                    if not route.get("match"):
                        ctx["root"] = h["root"]                # a bare `root` applies to the next routes too
                elif kind == "headers":
                    hdr = ((h.get("response") or {}).get("set") or {})
                    if any("sandbox" in v for v in hdr.get("Content-Security-Policy", [])):
                        sub["sandbox"] = True
                        if not route.get("match"):
                            ctx["sandbox"] = True
                elif kind == "rewrite" and h.get("strip_path_prefix"):
                    sub["strip"] = True
                    if not route.get("match"):
                        ctx["strip"] = True
                elif kind == "subroute":
                    _walk_routes(h.get("routes"), sub, found)
                elif kind == "reverse_proxy":
                    ups = [u.get("dial", "") for u in h.get("upstreams") or [] if u.get("dial")]
                    php = (h.get("transport") or {}).get("protocol") == "fastcgi"
                    found.append({**sub, "kind": "php" if php else "proxy", "upstreams": ups})
                elif kind == "file_server":
                    found.append({**sub, "kind": "static", "root": h.get("root") or sub.get("root"), "strip": sub.get("strip")})
                elif kind == "static_response":
                    loc = (h.get("headers") or {}).get("Location")
                    if loc:
                        found.append({**sub, "kind": "redirect", "redirect": loc[0]})
                    else:
                        found.append({**sub, "kind": "respond", "status": h.get("status_code")})


RANK = {"proxy": 4, "static": 3, "php": 3, "redirect": 2, "respond": 1}


def _merge_sites(found, server_name):
    sites = {}
    for f in found:
        for host in f.get("hosts") or ["*"]:
            for path in f.get("paths") or [""]:
                path = re.sub(r"/?\*$", "", path)
                key = (host, path)
                cur = sites.get(key)
                if cur is None or RANK.get(f["kind"], 0) > RANK.get(cur["kind"], 0):
                    cur = {"host": host, "path": path, "kind": f["kind"], "upstreams": [], "root": None,
                           "redirect": None, "sandbox": False, "server": "caddy", "block": server_name}
                    sites[key] = cur
                for u in f.get("upstreams") or []:
                    if u not in cur["upstreams"]:
                        cur["upstreams"].append(u)
                if f["kind"] == "static" and f.get("root") and not cur["root"] and cur["kind"] == "static":
                    root = f["root"].replace("{http.vars.root}", "")
                    # without handle_path, Caddy serves <root><path>: that is the folder of a path site
                    cur["root"] = root if f.get("strip") or not path else root.rstrip("/") + path
                cur["redirect"] = cur["redirect"] or f.get("redirect")
                cur["sandbox"] = cur["sandbox"] or bool(f.get("sandbox"))
    out = []
    for s in sites.values():
        if s["kind"] == "respond" and any(k[0] == s["host"] and k[1] != s["path"] for k in sites):
            continue                                          # a bare 404 next to real routes of the same host
        out.append(s)
    return out


def caddy_sites():
    cfg, source = _caddy_config()
    return None if cfg is None else parse_caddy(cfg, source)


def parse_caddy(cfg, source="api"):
    out = []
    for name, srv in (((cfg.get("apps") or {}).get("http") or {}).get("servers") or {}).items():
        found = []
        _walk_routes(srv.get("routes"), {}, found)
        for s in _merge_sites(found, name):
            s["listen"] = srv.get("listen") or []
            s["source"] = source
            out.append(s)
    return out


def _blocks(text, keyword):
    """Top-level `keyword ... { ... }` blocks of an nginx config (comments removed)."""
    text = re.sub(r"#[^\n]*", "", text)
    out, i = [], 0
    pat = re.compile(r"\b" + keyword + r"\b[^{;]*\{")
    while True:
        m = pat.search(text, i)
        if not m:
            return out
        depth, j = 1, m.end()
        while j < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        out.append((text[m.start():m.end() - 1], text[m.end():j - 1]))
        i = j


def nginx_sites():
    if not shutil.which("nginx"):
        return None
    code, txt = run(["nginx", "-T"], timeout=8)
    return parse_nginx(txt) if code == 0 else None


def parse_nginx(txt):
    out = []
    for _, body in _blocks(txt, "server"):
        names = []
        for m in re.finditer(r"\bserver_name\s+([^;]+);", body):
            # `.example.com` = example.com and its subdomains; `~regex` names are not hosts
            names += [n.lstrip(".") for n in m.group(1).split() if n != "_" and not n.startswith("~") and n.strip(".")]
        listen = re.findall(r"\blisten\s+([^;]+);", body)
        root = re.search(r"^\s*root\s+([^;]+);", body, re.M)
        locs = _blocks(body, "location")
        entries = []
        for head, lbody in locs:
            path = head.split()[-1] if len(head.split()) > 1 else "/"
            pp = re.search(r"\bproxy_pass\s+([^;]+);", lbody)
            lr = re.search(r"\b(?:root|alias)\s+([^;]+);", lbody)
            ret = re.search(r"\breturn\s+30[12]\s+([^;]+);", lbody)
            if pp:
                entries.append((path, "proxy", re.sub(r"^https?://", "", pp.group(1)), None, None))
            elif lr:
                entries.append((path, "static", None, lr.group(1), None))
            elif ret:
                entries.append((path, "redirect", None, None, ret.group(1)))
        if not entries:
            ret = re.search(r"\breturn\s+30[12]\s+([^;]+);", body)
            entries.append(("/", "redirect" if ret else "static", None, root.group(1) if root else None,
                            ret.group(1) if ret else None))
        for host in names or ["*"]:
            for path, kind, up, r, red in entries:
                out.append({"host": host, "path": "" if path == "/" else path.rstrip("/"), "kind": kind,
                            "upstreams": [up] if up else [], "root": r or (root.group(1) if root and kind == "static" else None),
                            "redirect": red, "sandbox": False, "server": "nginx", "listen": listen, "source": "nginx -T"})
    return out


# ---- databases ----------------------------------------------------------------------------------
def _pg_rows(txt):
    dbs = []
    for line in txt.splitlines():
        parts = line.split("|")
        if len(parts) >= 3:
            try:
                dbs.append({"name": parts[0], "size": int(parts[1]), "owner": parts[2]})
            except ValueError:
                pass
    return dbs


def _procs():
    names = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            comm = read(f"/proc/{d}/comm", 64).strip()
            if comm:
                names.setdefault(comm, []).append(int(d))
    return names


def databases(conts, ports, opts):
    out, errors = [], {}
    procs = _procs()

    def native(comms):
        for c in comms:
            for pid in procs.get(c, []):
                if "container" not in unit_of(pid):
                    return pid
        return None

    def port_of(pid):
        for p in ports:
            if p.get("pid") == pid:
                return p["port"]
        return None

    pid = native(("postgres",))
    if pid:
        item = {"engine": "postgres", "where": "native", "port": port_of(pid) or 5432, "databases": None}
        if shutil.which("psql"):
            runner = ["runuser", "-u", "postgres", "--"] if os.geteuid() == 0 else []
            code, txt = run(runner + ["psql", "-XAt", "-F", "|", "-c", PG_SQL], timeout=10)
            if code == 0:
                item["databases"] = _pg_rows(txt)
                _, v = run(runner + ["psql", "-XAtc", "show server_version"], timeout=5)
                item["version"] = v.strip().split(" ")[0] or None
            else:
                item["error"] = "psql could not list the databases"
        out.append(item)
    pid = native(("mysqld", "mariadbd"))
    if pid:
        item = {"engine": "mariadb" if procs.get("mariadbd") else "mysql", "where": "native", "port": port_of(pid) or 3306,
                "databases": None}
        if shutil.which("mysql"):
            code, txt = run(["mysql", "-N", "-B", "-e",
                             "select s.schema_name, coalesce(sum(t.data_length+t.index_length),0) from information_schema.schemata s "
                             "left join information_schema.tables t on t.table_schema=s.schema_name group by s.schema_name"], timeout=10)
            if code == 0:
                item["databases"] = [{"name": a, "size": int(float(b))} for a, b in (ln.split("\t")[:2] for ln in txt.splitlines() if "\t" in ln)
                                     if a not in ("mysql", "sys", "performance_schema", "information_schema")]
            else:
                item["error"] = "mysql could not list the databases (no socket access for root?)"
        out.append(item)
    for comm, eng in (("redis-server", "redis"), ("valkey-server", "redis"), ("mongod", "mongodb")):
        pid = native((comm,))
        if pid:
            out.append({"engine": eng, "where": "native", "port": port_of(pid), "databases": None})
    for c in conts:
        eng = c.get("engine")
        if eng not in ("postgres", "mysql", "mariadb", "redis", "mongodb", "clickhouse"):
            continue
        item = {"engine": eng, "where": "docker", "container": c["name"], "image": c["image"],
                "port": next((p["host"] for p in c["ports"]), None), "databases": None,
                "compose_project": c.get("compose_project"), "repo": c.get("repo")}
        if eng == "postgres":
            code, env = run(["docker", "inspect", "--format", "{{json .Config.Env}}", c["id"]], timeout=6)
            user = "postgres"
            try:
                for kv in json.loads(env) if code == 0 else []:
                    if kv.startswith("POSTGRES_USER="):
                        user = kv.split("=", 1)[1] or user
            except ValueError:
                pass
            code, txt = run(["docker", "exec", c["id"], "psql", "-U", user, "-d", "postgres", "-XAt", "-F", "|", "-c", PG_SQL], timeout=10)
            if code == 0:
                item["databases"] = _pg_rows(txt)
            else:
                item["error"] = "psql inside the container could not list the databases"
        out.append(item)
    sq = sqlite_files(opts)
    out.extend(sq)
    return out, errors


def sqlite_files(opts):
    files = {}
    deadline = time.time() + float(opts.get("sqlite_budget_s", 6))
    for f in opts.get("sqlite_files") or []:
        _add_sqlite(f, files, declared=True)
    stack = [(r, 0) for r in opts.get("sqlite_roots") or [] if os.path.isdir(r)]
    dirs = 0
    while stack and time.time() < deadline and dirs < 30000:
        d, depth = stack.pop()
        dirs += 1
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if depth < 7 and e.name not in PRUNE and not e.name.startswith("."):
                        stack.append((e.path, depth + 1))
                elif e.name.endswith(SQLITE_EXT) and e.is_file(follow_symlinks=False):
                    _add_sqlite(e.path, files)
            except OSError:
                continue
    out = list(files.values())
    if stack:
        for x in out:
            x["scan_incomplete"] = True
    return out


def _add_sqlite(path, files, declared=False):
    try:
        st = os.stat(path)
        with open(path, "rb") as f:
            if f.read(16) != SQLITE_MAGIC:
                return
    except OSError:
        if declared:
            files[path] = {"engine": "sqlite", "where": "file", "path": path, "size": None, "missing": True}
        return
    files[path] = {"engine": "sqlite", "where": "file", "path": path, "size": st.st_size, "modified": int(st.st_mtime),
                   "repo": repo_of(os.path.dirname(path))}


# ---- buckets ------------------------------------------------------------------------------------
def garage_buckets():
    cfg_path = next((p for p in ("/etc/garage.toml", "/etc/garage/garage.toml") if os.path.exists(p)), None)
    if not cfg_path:
        return None
    cfg = read(cfg_path)
    m = re.search(r"\[admin\][^\[]*?api_bind_addr\s*=\s*\"([^\"]+)\"", cfg, re.S)
    t = re.search(r"\[admin\][^\[]*?admin_token\s*=\s*\"([^\"]+)\"", cfg, re.S)
    s3 = re.search(r"\[s3_api\][^\[]*?api_bind_addr\s*=\s*\"([^\"]+)\"", cfg, re.S)
    web = re.search(r"\[s3_web\][^\[]*?root_domain\s*=\s*\"([^\"]+)\"", cfg, re.S)
    if not (m and t):
        return {"engine": "garage", "error": "no [admin] api_bind_addr / admin_token in " + cfg_path, "buckets": []}
    base = "http://" + m.group(1).replace("0.0.0.0", "127.0.0.1").replace("[::]", "127.0.0.1")
    hdr = {"Authorization": "Bearer " + t.group(1)}
    out = {"engine": "garage", "s3_endpoint": s3.group(1) if s3 else None, "web_root_domain": web.group(1) if web else None,
           "buckets": []}
    try:
        lst = http_json(base + "/v2/ListBuckets", hdr, timeout=4)
        for b in lst or []:
            info = http_json(base + "/v2/GetBucketInfo?id=" + b["id"], hdr, timeout=4) or {}
            out["buckets"].append({"id": b["id"], "name": (b.get("globalAliases") or [b["id"][:12]])[0],
                                   "aliases": b.get("globalAliases") or [], "bytes": info.get("bytes"),
                                   "objects": info.get("objects"), "website": bool(info.get("websiteAccess")),
                                   "created": b.get("created")})
    except Exception as e:  # noqa: BLE001
        out["error"] = "Garage admin API: " + type(e).__name__
    return out


# ---- main ---------------------------------------------------------------------------------------
def collect(opts=None):
    opts = opts or {}
    t0 = time.time()
    out = {"version": VERSION, "collected_at": int(t0), "errors": {}}

    def section(name, fn, default):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - one broken section never hides the others
            out["errors"][name] = f"{type(e).__name__}: {e}"[:300]
            return default
    out["server"] = section("server", server, {})
    out["listeners"] = section("listeners", listeners, [])
    out["containers"] = section("containers", containers, [])
    sites = []
    web = {}
    for name, fn in (("caddy", caddy_sites), ("nginx", nginx_sites)):
        got = section(name, fn, None)
        web[name] = got is not None
        sites += got or []
    out["web_servers"] = [k for k, v in web.items() if v]
    out["sites"] = sites
    dbs = section("databases", lambda: databases(out["containers"], out["listeners"], opts), ([], {}))
    out["databases"] = dbs[0]
    g = section("buckets", garage_buckets, None)
    out["buckets"] = [g] if g else []
    out["took_ms"] = int((time.time() - t0) * 1000)
    return out


if __name__ == "__main__":
    try:
        o = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except ValueError:
        o = {}
    sys.stdout.write(json.dumps(collect(o)))
