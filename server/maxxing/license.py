"""License: activation, updates from signed archives, daily ping (api.harness-maxxing.com).

Fair source (2.0.0a87): a licensed install moves to the public git repository by itself (`move_to_git`, right
after an update and once a day), so the archives below only matter until then.

A licensed install has no GitHub remote. Each published version is a .tar.gz of the code, signed
with ed25519 (message "harness-maxxing|<version>|<sha256>", public keys below: a release names the key
that signed it with `kid`, none = "k1"; an unknown key id is refused, so the key can be rotated by shipping
the new one first). A version older than the one installed is refused (`maxxing update --allow-downgrade`). `fetch_latest()`
downloads the newest version the license may get, checks the sha256 and the signature, then
imports the files as a commit on refs/remotes/origin/<branch>: from there `maxxing update`
works exactly as with git (customizations are rebased on top, rollback, …).

The license is only checked when installing and updating: a server whose license ended keeps
working on its version. The daily ping sends the version, whether the service runs and a few
health codes (never file names, prompts or keys), so the seller can see installs and help.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import __version__, config

API = os.environ.get("MAXXING_LICENSE_API", "https://api.harness-maxxing.com").rstrip("/")
PUBKEYS = {                  # key id -> ed25519 public key that signs releases (same list in install.sh)
    "k1": """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAfg3vG94nEzS93VB0zGtE2RH+1VF317mLumbHgMMkOPY=
-----END PUBLIC KEY-----
""",
}
DEFAULT_KID = "k1"           # a release without `kid` is checked with this key
PUBKEY = PUBKEYS[DEFAULT_KID]
KEY = "license_key"          # secrets.json
TOKEN = "license_token"      # secrets.json (activation token of this server)
PING_EVERY = 24 * 3600
USER_AGENT = f"harness-maxxing/{__version__}"


class LicenseError(RuntimeError):
    def __init__(self, message: str, code: str = "error", data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.data = data or {}


def enabled() -> bool:
    """This install gets its updates through a license (not from a git remote)."""
    return bool(config.get_secret(TOKEN))


def pubkey(kid: str | None = None) -> str | None:
    """Public key of a key id (None = the default one); None for an unknown id."""
    kid = kid or DEFAULT_KID
    p = os.environ.get("MAXXING_RELEASE_PUBKEY")      # tests only: replaces the default key
    if p and kid == DEFAULT_KID:
        return Path(p).read_text()
    return PUBKEYS.get(kid)


def _url_ok(url: str) -> bool:
    """Releases come over HTTPS (plain HTTP only from this machine, for tests)."""
    from urllib.parse import urlparse
    u = urlparse(url or "")
    return u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1"))


def machine_id() -> str:
    """One-way fingerprint of this machine (the raw id never leaves the server)."""
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            raw = Path(p).read_text().strip()
            if raw:
                break
        except OSError:
            continue
    else:
        f = config.state_dir() / "machine-id"
        if not f.exists():
            f.write_text(uuid.uuid4().hex)
        raw = f.read_text().strip()
    return hashlib.sha256(f"harness-maxxing:{raw}".encode()).hexdigest()


def os_name() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.platform()


def _post(path: str, body: dict, timeout: float = 25) -> dict:
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", "user-agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read() or b"{}")
        except ValueError:
            j = {}
        raise LicenseError(j.get("message") or f"license server answered HTTP {e.code}", j.get("error") or f"http_{e.code}", j) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LicenseError(f"cannot reach the license server ({API}): {e}", "network") from None


def _save_info(lic: dict | None = None, **extra) -> dict:
    cur = config.load_config().get("license") or {}
    if lic:
        cur.update({k: lic.get(k) for k in ("email", "kind", "status", "max_servers", "updates_until", "expires_at", "channel")})
    cur.update(extra)
    config.update_config(license=cur)
    return cur


def status() -> dict:
    """What the UI / doctor show (no secret)."""
    info = dict(config.load_config().get("license") or {})
    key = config.get_secret(KEY)
    info.update(enabled=enabled(), key_hint=(key[:7] + "…" + key[-4:]) if key else "", api=API)
    return info


def disk_version(code: Path | None = None) -> str:
    try:
        src = ((code or config.CODE) / "server" / "maxxing" / "__init__.py").read_text()
        for line in src.splitlines():
            if line.startswith("__version__"):
                return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return __version__


def activate(key: str, version: str | None = None) -> dict:
    """Activate this server with a license key -> server answer (license, release manifest)."""
    r = _post("/v1/activate", {"key": key.strip(), "machine_id": machine_id(), "hostname": socket.gethostname(),
                               "os": os_name(), "version": version or disk_version()})
    config.set_secret(KEY, key.strip().upper())
    config.set_secret(TOKEN, r["token"])
    _save_info(r.get("license"), activation_id=r.get("activation_id"), activated_at=time.time(),
               latest=r.get("latest"), message=r.get("message") or "")
    return r


def _rotate(r: dict) -> None:
    """The license server may hand out a new activation token in any answer: keep it."""
    tok = r.get("token") if isinstance(r, dict) else None
    if isinstance(tok, str) and tok.strip() and tok != config.get_secret(TOKEN):
        config.set_secret(TOKEN, tok.strip())


def check(version: str | None = None) -> dict:
    """Ask for updates -> {latest, available, allowed, message, release?, license}."""
    tok = config.get_secret(TOKEN)
    if not tok:
        raise LicenseError("this server has no license: run `maxxing license activate <key>`", "no_license")
    r = _post("/v1/update", {"token": tok, "machine_id": machine_id(), "version": version or disk_version()})
    _rotate(r)
    _save_info(r.get("license"), latest=r.get("latest"), available=r.get("available"), allowed=r.get("allowed"),
               message=r.get("message") or "", checked_at=time.time())
    return r


def ping(health: dict | None = None) -> dict:
    tok = config.get_secret(TOKEN)
    if not tok:
        return {"ok": False, "error": "no_license"}
    r = _post("/v1/ping", {"token": tok, "machine_id": machine_id(), "version": disk_version(), "ok": True,
                           "health": health or {}}, timeout=15)
    _rotate(r)
    _save_info(r.get("license"), latest=r.get("latest"), available=r.get("available"), allowed=r.get("allowed"),
               message=r.get("message") or "", pinged_at=time.time())
    return r


def release() -> dict:
    """Free this server's place on the license (moving to another server)."""
    tok = config.get_secret(TOKEN)
    if not tok:
        raise LicenseError("this server has no license", "no_license")
    r = _post("/v1/release", {"token": tok, "machine_id": machine_id()})
    config.set_secret(TOKEN, None)
    _save_info(released_at=time.time())
    return r


# ---- archives ---------------------------------------------------------------------------------
def signed_message(version: str, sha256: str) -> bytes:
    return f"harness-maxxing|{version}|{sha256}".encode()


def verify_signature(version: str, sha256: str, signature_b64: str, kid: str | None = None) -> bool:
    """With a key id, only that key is tried (an unknown id is refused); without one, every known key is (same rule
    as the license server's verifySignature: a release signed by a new key verifies before it names its kid)."""
    if kid:
        keys = [pubkey(kid)]
    else:
        keys = [pubkey(None)] + [v for k, v in PUBKEYS.items() if k != DEFAULT_KID]
    return any(k and _verify_with(k, version, sha256, signature_b64) for k in keys)


def _verify_with(key: str, version: str, sha256: str, signature_b64: str) -> bool:
    import base64
    with tempfile.TemporaryDirectory(prefix="hm-verify-") as d:
        dp = Path(d)
        (dp / "msg").write_bytes(signed_message(version, sha256))
        try:
            (dp / "sig").write_bytes(base64.b64decode(signature_b64))
        except ValueError:
            return False
        (dp / "pub.pem").write_text(key)
        try:
            p = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(dp / "pub.pem"), "-rawin",
                                "-in", str(dp / "msg"), "-sigfile", str(dp / "sig")], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return p.returncode == 0 and "Verified Successfully" in p.stdout


def download(manifest: dict, dest: Path) -> Path:
    """Download + check sha256 + signature -> path of the archive (raises LicenseError)."""
    if not _url_ok(manifest.get("url", "")):
        raise LicenseError("the release is not served over HTTPS: refused", "insecure_url")
    if manifest.get("kid") and pubkey(manifest["kid"]) is None:
        raise LicenseError(f"the release is signed with an unknown key ({manifest['kid']}): refused - "
                           "update this server's code first", "unknown_key")
    req = urllib.request.Request(manifest["url"], headers={"user-agent": USER_AGENT})
    h = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
            while chunk := r.read(1 << 16):
                h.update(chunk)
                f.write(chunk)
    except (urllib.error.URLError, OSError) as e:
        raise LicenseError(f"download failed: {e}", "download") from None
    if h.hexdigest() != manifest["sha256"]:
        raise LicenseError("the downloaded archive is corrupted (sha256 mismatch)", "bad_archive")
    if not verify_signature(manifest["version"], manifest["sha256"], manifest["signature"], manifest.get("kid")):
        raise LicenseError("the downloaded archive is not signed by Harness Maxxing: refused", "bad_signature")
    return dest


def _extract(archive: Path, into: Path) -> None:
    with tarfile.open(archive, "r:gz") as t:
        for m in t.getmembers():
            n = Path(m.name)
            bad_link = (m.issym() or m.islnk()) and (m.linkname.startswith("/") or ".." in Path(m.linkname).parts)
            if n.is_absolute() or ".." in n.parts or bad_link or m.isdev():
                raise LicenseError(f"unsafe entry in archive: {m.name}", "bad_archive")
        try:
            t.extractall(into, filter="data")
        except TypeError:                                   # Python without extraction filters (checked above)
            t.extractall(into)


def _git(code: Path, *args: str, env: dict | None = None, timeout: float = 120) -> str:
    p = subprocess.run(["git", "-C", str(code), *args], capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, **(env or {})})
    if p.returncode != 0:
        raise LicenseError(f"git {args[0]} failed: {(p.stderr or p.stdout).strip()[-300:]}", "git")
    return p.stdout.strip()


def import_release(archive: Path, version: str, published_at: float | None = None, branch: str = "main",
                   code: Path | None = None) -> str:
    """Files of the archive -> a commit on refs/remotes/origin/<branch> (parent: the previous one)."""
    code = code or config.CODE
    ref = f"refs/remotes/origin/{branch}"
    with tempfile.TemporaryDirectory(prefix="hm-release-") as d:
        tree_dir = Path(d) / "tree"
        tree_dir.mkdir()
        _extract(archive, tree_dir)
        index = Path(d) / "index"
        genv = {"GIT_INDEX_FILE": str(index), "GIT_WORK_TREE": str(tree_dir)}
        _git(code, "--work-tree", str(tree_dir), "add", "-A", "-f", ".", env=genv, timeout=300)
        tree = _git(code, "write-tree", env=genv)
    try:
        parent = _git(code, "rev-parse", "--verify", "-q", ref)
    except LicenseError:
        parent = ""
    if parent and _git(code, "rev-parse", f"{parent}^{{tree}}") == tree:
        return parent                                         # same files: nothing new
    when = str(int(published_at or time.time()))
    ident = {"GIT_AUTHOR_NAME": "Harness Maxxing", "GIT_AUTHOR_EMAIL": "releases@harness-maxxing.com",
             "GIT_COMMITTER_NAME": "Harness Maxxing", "GIT_COMMITTER_EMAIL": "releases@harness-maxxing.com",
             "GIT_AUTHOR_DATE": f"{when} +0000", "GIT_COMMITTER_DATE": f"{when} +0000"}
    args = ["commit-tree", tree, "-m", f"Harness Maxxing {version}"]
    if parent:
        args[2:2] = ["-p", parent]
    commit = _git(code, *args, env=ident)
    _git(code, "update-ref", ref, commit)
    return commit


def remote_version(branch: str = "main", code: Path | None = None) -> str | None:
    """Version in refs/remotes/origin/<branch> (what `maxxing update` would install)."""
    try:
        src = _git(code or config.CODE, "show", f"refs/remotes/origin/{branch}:server/maxxing/__init__.py")
    except LicenseError:
        return None
    for line in src.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return None


def is_downgrade(offered: str, *installed: str) -> bool:
    """`offered` is not newer than every installed / fetched version (unparsable = refused)."""
    from .cmd_core import version_key
    k = version_key(offered or "")
    floor = [x for x in (version_key(v or "") for v in installed) if x is not None]
    return k is None or any(k <= f for f in floor)


def fetch_latest(branch: str = "main", allow_downgrade: bool = False) -> dict:
    """Bring the newest allowed version into origin/<branch> -> {ok, version?, latest, message}.
    Plays the role of `git fetch` for licensed installs. A version that is not newer than the installed one is
    refused (a replayed old release with known holes) unless `allow_downgrade`."""
    have = remote_version(branch) or disk_version()
    r = check(disk_version())
    rel = r.get("release")
    if not rel:
        return {"ok": True, "version": None, "latest": r.get("latest"), "message": r.get("message") or ""}
    if have and rel["version"] == have:
        return {"ok": True, "version": None, "latest": r.get("latest"), "message": ""}   # already fetched
    # against the installed version only: a newer one fetched but never installed (failed health check, rolled
    # back) and then withdrawn must not block the version the license server offers now
    if not allow_downgrade and is_downgrade(rel["version"], disk_version()):
        newest = disk_version()
        raise LicenseError(f"the license server offers {rel['version']}, not newer than {newest} "
                           "installed here: refused (maxxing update --allow-downgrade to accept it)", "downgrade")
    with tempfile.TemporaryDirectory(prefix="hm-dl-") as d:
        arch = download(rel, Path(d) / "release.tar.gz")
        commit = import_release(arch, rel["version"], rel.get("published_at"), branch)
    return {"ok": True, "version": rel["version"], "commit": commit, "latest": r.get("latest"), "message": r.get("message") or ""}


# ---- move to git (fair source) -----------------------------------------------------------------
GIT_URL = os.environ.get("MAXXING_GIT_URL", "https://github.com/makushingu/harness-maxxing.git")
GIT_BRANCH = "stable"
PRE_GIT_REF = "refs/maxxing/pre-git"          # HEAD before the move (to inspect or go back by hand)


def _version_at(code: Path, rev: str) -> str | None:
    try:
        src = _git(code, "show", f"{rev}:server/maxxing/__init__.py")
    except LicenseError:
        return None
    for line in src.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return None


_move_lock = threading.Lock()


def move_to_git(code: Path | None = None) -> dict:
    """Harness Maxxing is fair source: a licensed install leaves the signed archives for the public repository.
    The code directory gets `origin` = GIT_URL, its branch becomes `stable` at the same version (the GitHub commit
    with the same files, else the same version number) with the customizations rebased on top, and the activation
    token is forgotten (the key stays: Settings -> License). Then `maxxing update` works as on any git install.
    Never raises: {ok, moved?, skipped?, error?}. Nothing changes until the very end; a failure is retried later."""
    if not _move_lock.acquire(blocking=False):
        return {"ok": False, "error": "already moving"}
    try:
        return _move_to_git(code)
    finally:
        _move_lock.release()


def _move_to_git(code: Path | None) -> dict:
    from . import customs
    code = code or config.CODE
    if not enabled():
        return {"ok": True, "moved": False, "skipped": "not a licensed install"}
    if not (code / ".git").exists():
        return {"ok": False, "error": "no git directory in the code folder"}
    if customs.rebase_in_progress() or customs.pending():
        return {"ok": False, "error": "an update is being finished (customizations being adapted): later"}
    if customs.dirty_files():
        return {"ok": False, "error": "uncommitted changes in the code folder: `maxxing update` saves them first"}
    try:
        cur = _git(code, "rev-parse", "--abbrev-ref", "HEAD")
        if cur == "HEAD":
            return {"ok": False, "error": "detached HEAD (a version under test): later"}
        head = _git(code, "rev-parse", "HEAD")
        # the licensed version that runs (a newer archive may be fetched but not installed): customizations = base..HEAD
        base = _git(code, "merge-base", head, f"refs/remotes/origin/{cur}")
        try:
            _git(code, "remote", "get-url", "origin")
            _git(code, "remote", "set-url", "origin", GIT_URL)
        except LicenseError:
            _git(code, "remote", "add", "origin", GIT_URL)
        _git(code, "fetch", "-q", "origin", "--", f"+refs/heads/{GIT_BRANCH}:refs/remotes/origin/{GIT_BRANCH}",
             env={"GIT_TERMINAL_PROMPT": "0"}, timeout=300)
        tree, version = _git(code, "rev-parse", f"{base}^{{tree}}"), _version_at(code, base)
        target = None
        for rec in _git(code, "log", "--format=%H %T", "-n", "500", f"refs/remotes/origin/{GIT_BRANCH}").splitlines():
            sha, t = rec.split()
            if t == tree:
                target = sha
                break
            if target is None and version and _version_at(code, sha) == version:
                target = sha                                   # same version, keep looking for the same files
        if not target:
            return {"ok": False, "error": f"{version or 'this version'} is not on {GIT_BRANCH} yet: later"}
        _git(code, "update-ref", PRE_GIT_REF, head)
        if _git(code, "branch", "--list", GIT_BRANCH):
            _git(code, "branch", "-m", GIT_BRANCH, f"{GIT_BRANCH}-before-git-{int(time.time())}")
        _git(code, "checkout", "-q", "-b", GIT_BRANCH)
        customs.ensure_identity()
        p = subprocess.run(["git", "-C", str(code), "rebase", "-q", "--onto", target, base, GIT_BRANCH],
                           capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            subprocess.run(["git", "-C", str(code), "rebase", "--abort"], capture_output=True, timeout=60)
            _git(code, "checkout", "-q", "-f", cur)
            _git(code, "branch", "-D", GIT_BRANCH)
            return {"ok": False, "error": "a customization does not apply on the git version: "
                                          + (p.stderr or p.stdout).strip()[-300:]}
        _git(code, "branch", "--set-upstream-to", f"origin/{GIT_BRANCH}", GIT_BRANCH)
        _git(code, "branch", "-D", cur)
        _git(code, "update-ref", "-d", f"refs/remotes/origin/{cur}")
    except (LicenseError, OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e)[-300:]}
    config.set_secret(TOKEN, None)
    _save_info(moved_to_git=time.time(), move_error="")
    return {"ok": True, "moved": True, "branch": GIT_BRANCH, "commit": target, "version": version}


def try_move_to_git() -> dict:
    """move_to_git() + the outcome kept in config.json "license" (move_error), for doctor and the UI."""
    r = move_to_git()
    if not r.get("ok"):
        _save_info(move_error=r.get("error") or "?", move_tried_at=time.time())
    return r


# ---- daily ping (started by the web server) ----------------------------------------------------
def health_summary() -> dict:
    """A few health codes for the seller (no paths, prompts, names or keys)."""
    try:
        from . import health
        h = health.collect()
        return {"ok": h["ok"], "issues": sorted({i["code"] for i in h["issues"]}), "disk_pct": round(h["disk"]["pct"]),
                "mem_avail_mb": h["mem"]["avail"] // (1024 * 1024), "uptime_d": round(h["uptime_s"] / 86400, 1),
                "claude_auth": h["claude_auth"], "backup_age_h": h["backup_age_h"], "os": os_name()}
    except Exception as e:  # noqa: BLE001 - the ping must never fail because of the health probe
        return {"error": type(e).__name__}


def move_due() -> bool:
    last = (config.load_config().get("license") or {}).get("move_tried_at") or 0
    return time.time() - float(last) > 6 * 3600


def ping_due() -> bool:
    last = (config.load_config().get("license") or {}).get("pinged_at") or 0
    return time.time() - float(last) > PING_EVERY - 600
