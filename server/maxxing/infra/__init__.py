"""Infra: where every site, database, bucket, domain and server is, its status and its links (Settings -> Features ->
Infra page). Read-only: the recipes that create things on this server are in `actions.py` / `caddy.py` (CLI
`maxxing infra`, skill `maxxing-infra`).

refresh() gathers, in the background (never on a page load):
  - the probe of this server (`probe.py` as a subprocess) and of each registered server (`ssh ... python3 -`),
  - Cloudflare and Hostinger through the vault keys, RDAP for the other domains (once a day),
  - an HTTP check of every URL and the TLS expiry of every host,
then builds the resources (`build.py`), posts alerts to the notifications feed and saves
`<state>/infra/snapshot.json`. See docs/dev/INTERNALS.md#infra.
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import socket
import ssl
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from .. import config
from . import build, connect, dnsinfo, platforms, providers, registry

log = logging.getLogger("maxxing.infra")

PROBE = Path(__file__).with_name("probe.py")
PROBE_TIMEOUT = 90
RDAP_EVERY_S = 86400
RDAP_RETRY_S = 3600                                      # after a failed lookup (RDAP down, odd answer)
RDAP_PER_REFRESH = 25
LOCAL_SQLITE_ROOTS = ("/srv", "/var/www", "/opt", "/home")
REMOTE_SQLITE_ROOTS = ["/srv", "/var/www", "/opt", "/home", "/root"]
CERT_WARN_DAYS = 14
DOMAIN_ALERT_DAYS = (7, 30)              # the closest threshold crossed, once each

_lock = threading.Lock()
snapshot_lock = threading.Lock()        # read-modify-write of snapshot.json (annotate) vs the refresh's write
_running = threading.Event()
_last_error: str | None = None


def enabled() -> bool:
    return bool(config.load_config().get("infra_page", False))


def _dir() -> Path:
    return config.state_dir("infra")


def snapshot_path() -> Path:
    return _dir() / "snapshot.json"


def load_snapshot() -> dict | None:
    d = config.read_json(snapshot_path(), None)
    return d if isinstance(d, dict) else None


def mark_stale() -> None:
    """Ask the server for a refresh within a minute (used by the CLI recipes: no wait in the terminal)."""
    (_dir() / "stale").touch()


def is_stale(snap: dict | None) -> bool:
    try:
        return (_dir() / "stale").stat().st_mtime > ((snap or {}).get("generated_at") or 0)
    except OSError:
        return False


def checks_enabled() -> bool:
    return os.environ.get("MAXXING_INFRA_CHECKS", "1") != "0"


# ---- probes -------------------------------------------------------------------------------------
def probe_local(opts: dict) -> dict:
    try:
        r = subprocess.run([sys.executable, str(PROBE), json.dumps(opts)], capture_output=True, text=True,
                           timeout=PROBE_TIMEOUT, errors="replace")
        return json.loads(r.stdout) if r.stdout.strip() else {"error": (r.stderr.strip().splitlines() or ["probe failed"])[-1][:300]}
    except subprocess.TimeoutExpired:
        return {"error": f"the probe took more than {PROBE_TIMEOUT} s"}
    except ValueError:
        return {"error": "the probe printed something that is not JSON"}


def _result(f, base: dict | None = None) -> dict:
    """A probe or a provider that fails costs its own section, never the whole refresh (and its alerts)."""
    try:
        return f.result()
    except Exception as e:  # noqa: BLE001
        log.warning("infra: %s failed: %s", getattr(f, "name", "a check"), e)
        return {**(base or {}), "error": "failed", "message": type(e).__name__}


def ssh_command(s: dict, *remote: str) -> list[str]:
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new",
           "-o", "ServerAliveInterval=10", "-p", str(s.get("port") or 22)]
    if s.get("key"):
        cmd += ["-i", s["key"], "-o", "IdentitiesOnly=yes"]
    # `--`: whatever infra.json says, the destination is never read as an ssh option (-oProxyCommand=...)
    return cmd + ["--", f"{s.get('user') or 'root'}@{s['host']}", *remote]


def probe_remote(s: dict, opts: dict) -> dict:
    try:
        r = subprocess.run(ssh_command(s, "python3", "-", shlex.quote(json.dumps(opts))), input=PROBE.read_text(),
                           capture_output=True, text=True, timeout=PROBE_TIMEOUT, errors="replace")
    except subprocess.TimeoutExpired:
        return {"error": f"no answer in {PROBE_TIMEOUT} s"}
    except OSError as e:
        return {"error": f"ssh: {e}"}
    if r.returncode != 0 and not r.stdout.strip():
        err = (r.stderr.strip().splitlines() or [f"ssh exited with {r.returncode}"])[-1]
        if r.returncode == 127 or "python3: not found" in r.stderr or "command not found" in r.stderr:
            err = "python3 is not installed on that server"
        return {"error": err[:300]}
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {"error": "the server answered something that is not JSON"}


# ---- checks -------------------------------------------------------------------------------------
CHECK_TOTAL_S = 10.0            # a whole URL check (connect + TLS + status line + headers), however the site dribbles


def check_url(url: str) -> dict:
    """Status line and headers only: the response is streamed and closed before its body (audit F17: a site answering
    an endless body cost memory and time, 16 checks at once). h11 caps the header block (16 KiB); a watchdog shuts the
    socket down after CHECK_TOTAL_S, since httpx timeouts are per read and a 1-byte-per-second answer never trips them."""
    t0 = time.time()
    sock: list = [None]
    expired = threading.Event()

    def trace(event: str, info: dict) -> None:
        # the latest socket (plain, then the TLS one) is the one the watchdog must shut down
        if event.endswith((".connect_tcp.complete", ".start_tls.complete")) and info.get("return_value") is not None:
            try:
                sock[0] = info["return_value"].get_extra_info("socket")
            except Exception:
                pass
            if expired.is_set():
                _shutdown(sock[0])

    def watchdog() -> None:
        expired.set()
        _shutdown(sock[0])

    timer = threading.Timer(CHECK_TOTAL_S, watchdog)
    timer.daemon = True
    timer.start()
    try:
        # connect=3: a dead address (often an IPv6 one) is given up fast, the next one is tried
        with httpx.Client(timeout=httpx.Timeout(8, connect=3), follow_redirects=False, headers={"User-Agent": "harness-maxxing-infra"}) as c:
            with c.stream("GET", url, extensions={"trace": trace}) as r:      # left without reading the body
                code, location = r.status_code, r.headers.get("location", "")[:300]
        out = {"code": code, "ms": int((time.time() - t0) * 1000)}
        if code < 400 or code in (401, 403):
            out["status"] = "ok"
        elif code < 500:
            out["status"], out["detail"] = "warn", f"http_{code}"
        else:
            out["status"], out["detail"] = "down", f"http_{code}"
        if 300 <= code < 400:
            out["location"] = location
        return out
    except httpx.ConnectError as e:
        if expired.is_set():
            return {"status": "down", "detail": "timeout", "ms": int((time.time() - t0) * 1000)}
        bad_tls = "CERTIFICATE" in str(e).upper() or "SSL" in str(e).upper()
        return {"status": "down", "detail": "tls_invalid" if bad_tls else "unreachable", "ms": int((time.time() - t0) * 1000)}
    except httpx.TimeoutException:
        return {"status": "down", "detail": "timeout", "ms": int((time.time() - t0) * 1000)}
    except httpx.HTTPError as e:
        detail = "timeout" if expired.is_set() else type(e).__name__
        return {"status": "down", "detail": detail, "ms": int((time.time() - t0) * 1000)}
    except (httpx.InvalidURL, ValueError):            # `.example.com`, a label over 63 characters, `a..b`
        return {"status": "unknown", "detail": "invalid_url", "ms": 0}
    except OSError:                                   # the watchdog closed the socket under a raw read
        return {"status": "down", "detail": "timeout" if expired.is_set() else "unreachable", "ms": int((time.time() - t0) * 1000)}
    finally:
        timer.cancel()


def _shutdown(s) -> None:
    if s is None:
        return
    try:
        s.shutdown(socket.SHUT_RDWR)                  # wakes a blocked recv (close() alone does not)
    except OSError:
        pass


def cert_expiry(host: str) -> dict:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=3) as sock:      # per address: a dead one costs 3 s
            sock.settimeout(6)
            with ctx.wrap_socket(sock, server_hostname=host) as s:
                cert = s.getpeercert()
        exp = int(ssl.cert_time_to_seconds(cert["notAfter"]))
        issuer = dict(x[0] for x in cert.get("issuer", ()))
        return {"expires": exp, "issuer": issuer.get("organizationName") or issuer.get("commonName")}
    except ssl.SSLCertVerificationError as e:
        return {"error": "invalid", "message": str(e.verify_message or e)[:120]}
    except (OSError, ValueError, KeyError):
        return {"error": "unreachable"}


WORST = {"unknown": 0, "ok": 1, "warn": 2, "down": 3}


def _worse(r: dict, status: str, detail: str = "") -> None:
    if WORST.get(status, 0) > WORST.get(r["status"], 0) or r["status"] == "unknown":
        r["status"] = status
        if detail:
            r["status_detail"] = detail


def run_checks(resources: list[dict]) -> None:
    targets = [r for r in resources if r["kind"] in ("site", "worker", "pages") and r["urls"] and not r["missing"]]
    urls = sorted({u for r in targets for u in r["urls"][:3]})
    hosts = sorted({u.split("/")[2] for u in urls if u.startswith("https://") and not build.is_ip(u.split("/")[2])})
    with ThreadPoolExecutor(max_workers=16) as ex:
        # both kinds of checks in flight together (not the certificates after every URL): about half the time
        fu, fc = ex.map(check_url, urls), ex.map(cert_expiry, hosts)
        url_res, cert_res = dict(zip(urls, fu)), dict(zip(hosts, fc))
    now = time.time()
    for r in targets:
        checks = [{"url": u, **url_res[u]} for u in r["urls"][:3] if u in url_res]
        r["details"]["checks"] = checks
        if checks:
            best = min(checks, key=lambda c: WORST[c["status"]])
            status, detail = best["status"], best.get("detail", "")
            # an app (proxy, Worker) that answers 4xx is alive: APIs often have nothing at "/"
            if status == "warn" and (r["kind"] == "worker" or r["details"].get("kind") == "proxy"):
                status, detail = "ok", ""
            if status == "down" and best.get("code") and best["code"] < 500 and r["details"].get("kind") == "proxy":
                status, detail = "ok", ""
            _worse(r, status, detail)
        if r["kind"] == "site" and r["urls"][0].startswith("https://"):
            c = cert_res.get(r["urls"][0].split("/")[2])
            if c:
                r["details"]["cert"] = c
                if c.get("expires"):
                    days = (c["expires"] - now) / 86400
                    r["details"]["cert"]["days_left"] = int(days)
                    if days < CERT_WARN_DAYS:
                        _worse(r, "warn" if days > 0 else "down", "cert_expiring" if days > 0 else "cert_expired")
                elif c.get("error") == "invalid":
                    _worse(r, "warn", "tls_invalid")
        if r["details"].get("dns_elsewhere"):
            _worse(r, "warn", "dns_elsewhere")


# ---- alerts -------------------------------------------------------------------------------------
def _alerts(resources: list[dict], previous: dict | None) -> None:
    from .. import feed
    before = {r["id"]: r["status"] for r in (previous or {}).get("resources") or []}
    for r in resources:
        if r["hidden"] or (r["kind"] == "database" and r["details"].get("system")):
            continue
        old = before.get(r["id"])
        url = f"/infra?id={r['id']}"
        try:
            if r["kind"] in ("site", "worker", "pages", "server") and r["status"] == "down" and old in ("ok", "warn"):
                feed.post(f"Down: {r['name']}", _why(r), "error", "infra", url, group=f"down:{r['id']}")
            elif r["kind"] in ("site", "worker", "pages", "server") and r["status"] == "ok" and old == "down":
                feed.post(f"Back up: {r['name']}", "", "success", "infra", url, group=f"up:{r['id']}")
            cert = r["details"].get("cert") or {}
            if cert.get("days_left") is not None and cert["days_left"] < CERT_WARN_DAYS:
                feed.post(f"Certificate of {r['name']} expires in {cert['days_left']} days", "", "warning", "infra", url,
                          dedupe=f"cert:{r['id']}:{cert.get('expires')}")
            days = r["details"].get("days_left") if r["kind"] == "domain" else None
            if days is not None and not r["details"].get("auto_renew"):
                for limit in DOMAIN_ALERT_DAYS:
                    if days < limit:
                        feed.post(f"Domain {r['name']} expires in {max(days, 0)} days", "", "warning" if days >= 0 else "error",
                                  "infra", url, dedupe=f"domain:{r['name']}:{r['details'].get('expires')}:{limit}")
                        break
        except Exception:  # noqa: BLE001 - an alert never breaks a refresh
            pass


def _why(r: dict) -> str:
    c = next((c for c in r["details"].get("checks") or [] if c.get("status") == "down"), None)
    if c:
        return f"{c['url']} - {c.get('detail') or c.get('code')}"
    return r.get("status_detail") or ""


# ---- refresh ------------------------------------------------------------------------------------
def _dns_cache() -> dict:
    d = config.read_json(_dir() / "dns.json", {})
    return d if isinstance(d, dict) else {}


def _rdap_cache() -> dict:
    d = config.read_json(_dir() / "rdap.json", {})
    return d if isinstance(d, dict) else {}


def _rdap_due(info: dict) -> bool:
    return time.time() - info.get("checked", 0) > (RDAP_RETRY_S if info.get("error") else RDAP_EVERY_S)


def _source_state(cf: dict, hst: dict) -> dict:
    def sections(d: dict, keys: tuple[str, ...]) -> dict:
        out = {}
        for k in keys:
            v = d.get(k)
            out[k] = v.get("error") if isinstance(v, dict) and v.get("error") else ("ok" if v is not None else None)
        return out
    cfs = {"connected": cf.get("connected", False), "key": cf.get("key"), "error": cf.get("error")}
    if cf.get("connected") and not cf.get("error"):
        cfs["sections"] = sections(cf, ("zones", "workers", "worker_domains", "pages", "r2", "d1", "registrar"))
        zs = cf.get("zones") if isinstance(cf.get("zones"), list) else []
        if any(z.get("dns_error") for z in zs):
            cfs["sections"]["dns"] = next(z["dns_error"] for z in zs if z.get("dns_error"))
        elif zs:
            cfs["sections"]["dns"] = "ok"
    hs = {"connected": hst.get("connected", False), "key": hst.get("key")}
    if hst.get("connected"):
        hs["sections"] = sections(hst, ("domains", "vps"))
    return {"cloudflare": cfs, "hostinger": hs}


def refresh() -> dict | None:
    """Gather everything and save the snapshot. Returns it (None when a refresh is already running)."""
    global _last_error
    if not _lock.acquire(blocking=False):
        return None
    _running.set()
    t0 = time.time()
    try:
        cfg = config.load_config()
        reg = registry.load()
        workspace = str(config.workspace())
        sqlite_files = [v.get("details", {}).get("path") for k, v in reg["resources"].items()
                        if k.startswith("db:local:sqlite:") and v.get("details", {}).get("path")]
        local_opts = {"sqlite_roots": [*LOCAL_SQLITE_ROOTS, str(config.files_root())], "sqlite_files": sqlite_files}
        remote_opts = {"sqlite_roots": REMOTE_SQLITE_ROOTS}
        with ThreadPoolExecutor(max_workers=8) as ex:
            f_local = ex.submit(probe_local, local_opts)
            f_remote = {s["name"]: ex.submit(probe_remote, s, remote_opts) for s in reg["servers"]}
            f_cf = ex.submit(providers.cloudflare)
            f_h = ex.submit(providers.hostinger)
            f_p = ex.submit(platforms.read_all)
            probes = {build.LOCAL: _result(f_local), **{n: _result(f) for n, f in f_remote.items()}}
            cf, hst = _result(f_cf, {"connected": True}), _result(f_h, {"connected": True})
            try:
                plat = f_p.result()
            except Exception as e:  # noqa: BLE001 - platforms.read_all guards each platform; never stop the refresh
                log.warning("infra: platforms failed: %s", e)
                plat = {}
            added = []
            if hst.get("connected") and isinstance(hst.get("vps"), list):
                try:
                    added = connect.auto_connect(hst["vps"])
                except Exception as e:  # noqa: BLE001 - a failed auto-connect never stops the refresh
                    log.warning("infra: auto-connect failed: %s", e)
            for s, p in zip(added, ex.map(lambda s: probe_remote(s, remote_opts), added)):
                probes[s["name"]] = p
        if added:
            reg = registry.load()
        rdap = _rdap_cache()
        host = build.harness_host(cfg.get("public_url"))
        watched = reg.get("domains") or []
        dns = _dns_cache()
        res = build.build(probes, reg["servers"], cf, hst, rdap, reg["resources"], workspace, host, plat, dns, watched)
        if checks_enabled():
            dns = dnsinfo.refresh_cache(dns, build.hosts_to_resolve(res))
            config.write_json(_dir() / "dns.json", dns)
            res = build.build(probes, reg["servers"], cf, hst, rdap, reg["resources"], workspace, host, plat, dns, watched)
            todo = [r["name"] for r in res if r["kind"] == "domain" and not r["details"].get("expires")
                    and _rdap_due(rdap.get(r["name"]) or {})][:RDAP_PER_REFRESH]
            if todo:
                with ThreadPoolExecutor(max_workers=6) as ex:
                    for name, info in zip(todo, ex.map(providers.rdap_expiry, todo)):
                        rdap[name] = info
                config.write_json(_dir() / "rdap.json", rdap)
                res = build.build(probes, reg["servers"], cf, hst, rdap, reg["resources"], workspace, host, plat, dns, watched)
            run_checks(res)
        backups = config.read_json(_dir() / "backups.json", {}) or {}
        for r in res:
            b = backups.get(r["id"])
            if b:
                r["details"]["backup"] = b
                if not b.get("ok"):
                    _worse(r, "warn", "backup_failed")
        prev = load_snapshot()
        snap = {"generated_at": int(time.time()), "took_ms": int((time.time() - t0) * 1000), "harness_host": host,
                "sources": {"servers": {n: {"ok": not p.get("error"), "error": p.get("error"), "took_ms": p.get("took_ms")}
                                        for n, p in probes.items()}, **_source_state(cf, hst),
                            **platforms.source_state(plat)},
                "resources": res}
        with snapshot_lock:
            config.write_json(snapshot_path(), snap)
        _alerts(res, prev)
        _last_error = None
        from .. import bus
        bus.invalidate("infra")
        return snap
    except Exception as e:  # noqa: BLE001
        _last_error = f"{type(e).__name__}: {e}"[:300]
        raise
    finally:
        _running.clear()
        _lock.release()


def refreshing() -> bool:
    return _running.is_set()


def refresh_in_background() -> bool:
    if refreshing():
        return False
    threading.Thread(target=lambda: _safe_refresh(), daemon=True, name="infra-refresh").start()
    return True


def _safe_refresh() -> None:
    try:
        refresh()
    except Exception:  # noqa: BLE001 - kept in _last_error, shown by the page
        pass


def last_error() -> str | None:
    return _last_error


def view() -> dict:
    snap = load_snapshot() or {}
    return {"enabled": enabled(), "refreshing": refreshing(), "error": _last_error,
            "refresh_min": max(5, int(config.load_config().get("infra_refresh_min") or 15)),
            "generated_at": snap.get("generated_at"), "took_ms": snap.get("took_ms"), "harness_host": snap.get("harness_host"),
            "sources": snap.get("sources") or {}, "resources": snap.get("resources") or [],
            "servers": [{k: s.get(k) for k in ("name", "label", "host", "user", "port", "note")} for s in registry.servers()]}
