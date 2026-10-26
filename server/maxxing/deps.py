"""External components of an install (uv, Python, Node.js, Claude Code, Caddy, Scrapling + Chromium, Remotion, the
Whisper models, Garage): what is installed against what this release pins in deps.toml, verification (checksums and
owners), side-by-side updates with a check before the switch, removal and cleanup, and the weekly OSV check.

`maxxing deps list|verify|update|remove|clean|check` (cmd_deps.py) and the doctor read this module; install.sh reads
the same deps.toml. Every download goes into a private work folder under <state>/tmp (0700, removed afterwards), is
checked against its pinned sha256 before anything is extracted or run, and nothing is left in /tmp.
Standard library only (the CLI stays fast); the network is used by `update` and `check` only.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import pwd
import re
import shutil
import stat
import subprocess
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any, Iterator

from . import config

MANIFEST = Path(__file__).with_name("deps.toml")
SYSTEM_PATH = tuple((os.environ.get("MAXXING_DEPS_SYSTEM_PATH") or            # tests point it elsewhere
                     "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin").split(os.pathsep))
LINK_DIR = Path(os.environ.get("MAXXING_DEPS_BIN") or "/usr/local/bin")   # tests point it elsewhere
NODE_LEGACY_PARTS = ("bin/node", "bin/npm", "bin/npx", "bin/corepack", "include/node", "lib/node_modules/npm",
                     "lib/node_modules/corepack", "share/doc/node", "share/man/man1/node.1",
                     "share/systemtap/tapsets/node.stp")
LOG_MAX = 5 * 1024 * 1024            # a log of the state dir above this is cut to its last LOG_KEEP bytes by `clean`
LOG_KEEP = 1024 * 1024
FAILED_LOGS_DAYS = 30


class DepError(Exception):
    pass


# ---- manifest ------------------------------------------------------------------------------------------------
def load() -> dict[str, dict]:
    data = tomllib.loads(MANIFEST.read_text())
    comps = {k: v for k, v in data.items() if isinstance(v, dict)}
    if "garage" in comps:
        comps["garage"] = {**comps["garage"], **_garage_pins()}
    return comps


def _garage_pins() -> dict:
    """Garage is downloaded by `maxxing infra bucket install`: its pins stay there (one source of truth)."""
    try:
        from .infra import actions
    except Exception:  # noqa: BLE001
        return {}
    v, url = getattr(actions, "GARAGE_VERSION", None), getattr(actions, "GARAGE_URL", None)
    out: dict[str, Any] = {}
    if v and url:
        out = {"version": v, "url": url.replace("{v}", "{version}"),
               "arch": {"x86_64": "x86_64", "aarch64": "aarch64"}}
    sha = getattr(actions, "GARAGE_SHA256", None)
    if isinstance(sha, dict):
        out["sha256"] = dict(sha)
    return out


def get(name: str) -> dict:
    comps = load()
    if name not in comps:
        raise DepError(f"unknown component {name!r} (one of: {', '.join(comps)})")
    return comps[name]


def machine() -> str:
    m = platform.machine().lower()
    return {"amd64": "x86_64", "arm64": "aarch64"}.get(m, m)


def root_home() -> Path:
    """HOME of the service (= root's, set by the unit and the installer)."""
    if os.environ.get("HOME"):
        return Path(os.environ["HOME"])
    try:
        return Path(pwd.getpwuid(os.geteuid()).pw_dir)
    except KeyError:
        return Path("/root")


def expand(p: str) -> Path:
    if p.startswith("/usr/local/bin/"):
        return LINK_DIR / p[len("/usr/local/bin/"):]
    return Path(p.replace("{state}", str(config.STATE)).replace("{home}", str(root_home())))


def url_of(c: dict, m: str | None = None) -> str:
    m = m or machine()
    arch = (c.get("arch") or {}).get(m)
    if not arch:
        raise DepError(f"{c.get('title')}: no build for {m}")
    return c["url"].replace("{version}", c["version"]).replace("{arch}", arch)


def sha_of(c: dict, m: str | None = None) -> str:
    s = (c.get("sha256") or {}).get(m or machine())
    if not s or not re.fullmatch(r"[0-9a-f]{64}", s):
        raise DepError(f"{c.get('title')}: no pinned sha256 for {m or machine()}")
    return s


def lock_path(c: dict) -> Path:
    return config.CODE / c["lock"]


def lock_hash(c: dict) -> str:
    return hashlib.sha256(lock_path(c).read_bytes()).hexdigest()[:12]


# ---- record of what was installed (checksums for `verify`) -----------------------------------------------------
def record_path() -> Path:
    return config.STATE / "tools" / "deps.json"


def read_record() -> dict:
    try:
        return json.loads(record_path().read_text())
    except (OSError, ValueError):
        return {}


def write_record(name: str, entry: dict | None) -> None:
    rec = read_record()
    if entry is None:
        rec.pop(name, None)
    else:
        rec[name] = {**entry, "at": int(time.time())}
    p = record_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(rec, indent=1, sort_keys=True))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def file_sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha_cache_path() -> Path:
    return config.STATE / "tools" / "deps-sha.json"


def _known_sha(p: Path, cache: dict) -> str:
    """file_sha(p), recomputed only when the file changed: same inode, size, mtime and ctime (a write, a chmod or a
    touch moves ctime, which cannot be set back) -> the hash of the last check. `cache` is updated in place."""
    st = p.stat()
    ident = [st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]
    hit = cache.get(str(p))
    if isinstance(hit, list) and hit[:4] == ident and isinstance(hit[-1], str):
        return hit[-1]
    sha = file_sha(p)
    cache[str(p)] = ident + [sha]
    return sha


def _load_sha_cache() -> dict:
    try:
        d = json.loads(_sha_cache_path().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_sha_cache(cache: dict) -> None:
    p = _sha_cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(cache, sort_keys=True))
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except OSError:
        pass                                            # a read-only state: hashes are just recomputed next time


# ---- helpers ---------------------------------------------------------------------------------------------------
def _run(cmd: list[str], timeout: float = 600, env: dict | None = None, cwd: Path | None = None) -> tuple[int, str]:
    tmp = config.STATE / "tmp"                         # temporary files of uv, npm, node: never the shared /tmp
    with contextlib.suppress(OSError):
        tmp.mkdir(parents=True, exist_ok=True)
        os.chmod(tmp, 0o700)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                           env={**os.environ, "TMPDIR": str(tmp), **(env or {})})
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]}: timed out after {timeout:.0f}s"


@contextlib.contextmanager
def work_dir() -> Iterator[Path]:
    """A private folder for downloads and extraction under <state>/tmp (not the shared /tmp), always removed."""
    base = config.STATE / "tmp"
    base.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    d = Path(tempfile.mkdtemp(prefix="deps.", dir=base))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def fetch_verified(url: str, sha256: str, dest: Path, timeout: float = 600) -> Path:
    """Download url (HTTPS only) to dest and check its sha256 before returning; a mismatch deletes it."""
    import urllib.request
    if not url.startswith("https://"):
        raise DepError(f"refused: {url} is not HTTPS")
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "harness-maxxing-deps"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:   # noqa: S310 - https checked
            t0 = time.time()
            for chunk in iter(lambda: r.read(1 << 20), b""):
                h.update(chunk)
                f.write(chunk)
                if time.time() - t0 > timeout:
                    raise DepError(f"download of {url} took more than {timeout:.0f}s")
    except DepError:
        part.unlink(missing_ok=True)
        raise
    except Exception as e:  # noqa: BLE001 - network errors are reported, not raised raw
        part.unlink(missing_ok=True)
        raise DepError(f"download of {url} failed: {e}") from e
    if h.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise DepError(f"checksum mismatch for {url}: got {h.hexdigest()[:16]}…, expected {sha256[:16]}…")
    os.replace(part, dest)
    return dest


def _replace_file(src: Path, dest: Path, mode: int = 0o755) -> None:
    """Install src at dest atomically (a running program keeps its old file)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.new")
    shutil.copyfile(src, tmp)
    os.chmod(tmp, mode)
    with contextlib.suppress(PermissionError):
        os.chown(tmp, 0, 0)
    os.replace(tmp, dest)


def _symlink(target: Path, link: Path) -> None:
    tmp = link.with_name(f".{link.name}.lnk")
    with contextlib.suppress(FileNotFoundError):
        tmp.unlink()
    tmp.symlink_to(target)
    os.replace(tmp, link)


def _version_from(text: str) -> str | None:
    m = re.search(r"v?(\d+\.\d+\.\d+(?:[-.]?\w+)?)", text or "")
    return m.group(1) if m else None


def _venv_python() -> Path:
    return config.CODE / "server" / ".venv" / "bin" / "python"


def uv_env() -> dict[str, str]:
    """uv keeps the Pythons it manages in <state>/tools/python (not ~/.local, which a cleanup could wipe)."""
    return {"UV_PYTHON_INSTALL_DIR": str(expand(get("python")["path"])), "UV_PYTHON_PREFERENCE": "only-managed"}


def uv_bin() -> str | None:
    for p in (LINK_DIR / "uv",):
        if p.exists():
            return str(p)
    return shutil.which("uv")


def node_dir() -> Path:
    return expand(get("node")["path"])


def node_bin() -> Path | None:
    """Our Node.js in use: <state>/tools/nodejs/current, else the one of an older installer (/usr/local or
    <state>/tools/node), else whatever is on PATH."""
    for p in (node_dir() / "current" / "bin" / "node", config.STATE / "tools" / "node" / "bin" / "node"):
        if p.exists():
            return p
    found = shutil.which("node", path=f"{LINK_DIR}:/usr/local/bin:/usr/bin:/bin")
    return Path(found) if found else None


def _node_env() -> dict[str, str]:
    n = node_bin()
    return {"PATH": f"{n.parent}:{os.environ.get('PATH', '/usr/bin:/bin')}"} if n else {}


def node_required() -> tuple[int, ...]:
    """The strictest `>=x.y.z` the lockfiles ask of Node.js (web build and Remotion) - F15."""
    best: tuple[int, ...] = (0, 0, 0)
    for lock in (config.CODE / "web" / "package-lock.json", config.CODE / "templates" / "remotion" / "package-lock.json"):
        try:
            pkgs = json.loads(lock.read_text()).get("packages") or {}
        except (OSError, ValueError):
            continue
        for v in pkgs.values():
            eng = (v.get("engines") or {}).get("node") if isinstance(v, dict) and isinstance(v.get("engines"), dict) else None
            if not isinstance(eng, str):
                continue
            for alt in eng.split("||"):
                m = re.match(r"\s*>=\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?\s*$", alt)
                if not m:
                    break                       # a range with another form: not a plain floor
            else:
                floors = [tuple(int(x or 0) for x in re.match(r"\s*>=\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", a).groups())
                          for a in eng.split("||")]
                best = max(best, min(floors))
    return best


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


# ---- what is installed -----------------------------------------------------------------------------------------
def scrapling_dir() -> Path:
    return expand(get("scrapling")["path"])


def scrapling_python() -> Path | None:
    for p in (scrapling_dir() / "current" / "bin" / "python", config.STATE / "tools" / "uv" / "scrapling" / "bin" / "python"):
        if p.exists():
            return p
    return None


def browsers_dir() -> Path:
    return expand(get("chromium")["path"])


def playwright_revisions(py: Path | None = None) -> dict[str, str]:
    """{"playwright": "1243", "patchright": "1243"}: the Chromium revision each driver of the Scrapling venv needs."""
    py = py or scrapling_python()
    out: dict[str, str] = {}
    if not py:
        return out
    root = py.parent.parent
    for mod in ("playwright", "patchright"):
        for f in root.glob(f"lib/python*/site-packages/{mod}/driver/package/browsers.json"):
            try:
                for b in json.loads(f.read_text()).get("browsers", []):
                    if b.get("name") == "chromium":
                        out[mod] = str(b.get("revision"))
            except (OSError, ValueError):
                pass
    return out


def chromium_bin(rev: str | None = None) -> Path | None:
    """Playwright's Chromium (Scrapling, Remotion renders and PDFs all use this one)."""
    revs = [rev] if rev else sorted(set(playwright_revisions().values()), reverse=True)
    base = browsers_dir()
    if not revs and base.is_dir():
        revs = sorted((d.name.split("-", 1)[1] for d in base.glob("chromium-*")), reverse=True)
    for r in revs:
        for p in (base / f"chromium-{r}" / "chrome-linux64" / "chrome", base / f"chromium-{r}" / "chrome-linux" / "chrome"):
            if p.is_file():
                return p
    return None


def installed(name: str) -> dict:
    """-> {"version": str|None, "where": str, "managed": bool, "detail": str}"""
    c = get(name)
    out: dict[str, Any] = {"version": None, "where": "", "managed": True, "detail": ""}
    if name == "uv":
        b = uv_bin()
        if b:
            code, txt = _run([b, "--version"], timeout=20)
            out.update(version=_version_from(txt) if code == 0 else None, where=b,
                       managed=Path(b).parent == LINK_DIR)
    elif name == "python":
        py = _venv_python()
        if py.exists():
            real = py.resolve()
            out["where"] = str(real)
            m = re.search(r"python(\d+\.\d+)", real.name) or re.search(r"cpython-(\d+\.\d+)", str(real))
            out["version"] = m.group(1) if m else None
            out["managed"] = real.is_relative_to(expand(c["path"]).resolve()) if expand(c["path"]).exists() else False
            if not out["managed"]:
                out["detail"] = "the server's Python is outside the state dir (a cleanup of ~/.local would break it)"
    elif name == "node":
        cur = node_dir() / "current"
        if cur.exists():
            out.update(version=cur.resolve().name, where=str(cur.resolve()))
        else:
            n = node_bin()
            if n:
                code, txt = _run([str(n), "--version"], timeout=20)
                out.update(version=_version_from(txt) if code == 0 else None, where=str(n), managed=False,
                           detail="not in the managed folder yet (`maxxing deps update node`)")
    elif name == "claude":
        b = next((str(p) for p in (expand(c["path"]), LINK_DIR / "claude") if p.exists()), None) or shutil.which("claude")
        if b:
            code, txt = _run([b, "--version"], timeout=30)
            out.update(version=_version_from(txt) if code == 0 else None, where=b)
    elif name == "caddy":
        b = shutil.which("caddy")
        if b:
            code, txt = _run([b, "version"], timeout=20)
            out.update(version=_version_from(txt) if code == 0 else None, where=b)
    elif name == "scrapling":
        py = scrapling_python()
        if py:
            code, txt = _run([str(py), "-c", "import importlib.metadata as m; print(m.version('scrapling'))"], timeout=60)
            out.update(version=txt.strip() if code == 0 else None, where=str(py.parent.parent.resolve()))
            out["managed"] = py.is_relative_to(scrapling_dir())
            if not out["managed"]:
                out["detail"] = "installed by an older installer without hash pinning (`maxxing deps update scrapling`)"
    elif name == "chromium":
        b = chromium_bin()
        if b:
            out.update(version=b.parent.parent.name.split("-", 1)[-1], where=str(b))
    elif name == "remotion":
        f = expand(c["path"]) / "node_modules" / "remotion" / "package.json"
        try:
            out.update(version=json.loads(f.read_text()).get("version"), where=str(f.parent.parent.parent))
        except (OSError, ValueError):
            pass
    elif name == "whisper":
        d = expand(c["path"])
        models = sorted(p.name for p in d.iterdir() if (p / "model.bin").is_file()) if d.is_dir() else []
        if models:
            out.update(version=", ".join(models), where=str(d))
    elif name == "garage":
        p = expand(c["path"])
        if p.exists():
            try:
                same = file_sha(p) == sha_of(c)
            except (OSError, DepError):
                same = False
            out.update(version=c["version"] if same else "other build", where=str(p))
    return out


def expected(name: str) -> str | None:
    c = get(name)
    if name == "chromium":
        revs = sorted(set(playwright_revisions().values()))
        return ", ".join(revs) or None
    if name == "whisper":
        return "pinned revisions"
    return c.get("version")


def wanted(name: str) -> bool:
    """Should this install have it? (the tools are part of every install; the rest only when used)"""
    if name in ("uv", "python", "claude", "node", "scrapling", "chromium", "remotion"):
        return True
    if name == "whisper":
        try:
            from . import voice
            return voice.settings().get("engine") == "local"
        except Exception:  # noqa: BLE001
            return False
    return False                                      # caddy (domain mode), garage (buckets): when installed


def _same(name: str, have: str | None, want: str | None) -> bool:
    if not have or not want:
        return have == want or not want
    if name == "python":
        return have.startswith(want)
    if name == "whisper":
        return True                                   # models: their revision is checked by update
    if name == "chromium":
        return set(want.split(", ")) <= {have} or have in want.split(", ")
    return have.lstrip("v") == want.lstrip("v")


def status() -> list[dict]:
    out = []
    for name, c in load().items():
        inst = installed(name)
        want = expected(name)
        have = inst["version"]
        if have is None:
            state = "missing" if wanted(name) else "not installed"
        elif c.get("update") == "self":
            state = "ok"                                # Claude Code updates itself: any version is fine
        elif name == "chromium" and want:
            revs = set(want.split(", "))
            ok = all((browsers_dir() / f"chromium-{r}").is_dir() for r in revs)
            state = "ok" if ok else "outdated"
        elif not _same(name, have, want) or not inst["managed"]:
            state = "outdated"
        else:
            state = "ok"
        out.append({"name": name, "title": c.get("title", name), "kind": c.get("kind"), "update": c.get("update"),
                    "expected": want, "installed": have, "state": state, "where": inst["where"],
                    "detail": inst["detail"]})
    return out


# ---- verify ----------------------------------------------------------------------------------------------------
def foreign_owned(root: Path, owner: str = "root", limit: int = 20) -> list[str]:
    """Files under root not owned by `owner`, or writable by group/others (they could replace code root runs)."""
    try:
        uid = pwd.getpwnam(owner).pw_uid
    except KeyError:
        uid = 0
    bad: list[str] = []
    todo = [root]
    while todo and len(bad) < limit:
        p = todo.pop()
        try:
            st = p.lstat()
        except OSError:
            continue
        harmless = stat.S_ISREG(st.st_mode) and p.name.endswith(".lock") and not st.st_mode & 0o111   # lock files
        if st.st_uid != uid or (not stat.S_ISLNK(st.st_mode) and st.st_mode & 0o022 and not harmless and not
                                (stat.S_ISDIR(st.st_mode) and st.st_mode & stat.S_ISVTX)):
            bad.append(str(p))
        if stat.S_ISDIR(st.st_mode):
            try:
                todo.extend(p.iterdir())
            except OSError:
                pass
    return bad


def legacy_node_prefixes() -> list[Path]:
    """Where older installers extracted Node.js: /usr/local (install-manifest "node /usr/local") or <state>/tools/node."""
    out = [config.STATE / "tools" / "node"]
    try:
        for ln in (config.STATE / "install-manifest").read_text().splitlines():
            if ln.startswith("node "):
                out.append(Path(ln[5:].strip()))
    except OSError:
        pass
    return [p for p in dict.fromkeys(out) if (p / "bin" / "node").exists()]


def owned_paths(name: str) -> list[Path]:
    """The files of a component to check for their owner."""
    c = get(name)
    if name == "node":
        paths = [node_dir()] + [pre / part for pre in legacy_node_prefixes() for part in NODE_LEGACY_PARTS]
    elif name == "uv":
        paths = [LINK_DIR / f for f in c.get("files", [])]
    elif name == "claude":
        paths = [expand(c["path"]), root_home() / ".local" / "share" / "claude"]
    elif name in ("caddy",):
        paths = [Path(c["keyring"]), Path(c["apt_list"])]
    else:
        paths = [expand(c["path"])]
    return [p for p in paths if os.path.lexists(p)]


def verify(names: list[str] | None = None, versions: dict[str, str | None] | None = None, fresh: bool = False) -> list[dict]:
    """-> [{"name", "level": "ok"|"warn"|"fail", "text"}]: checksums and owners of what is installed. `versions`:
    the installed versions when the caller already has them (status() rows: no second round of `--version` runs).
    `fresh`: every file hashed again (`maxxing deps verify`: asked for, it trusts no cache)."""
    out: list[dict] = []
    rec = read_record()
    comps = load()
    shas = {} if fresh else _load_sha_cache()
    before = json.dumps(shas, sort_keys=True)
    for name in names or list(comps):
        c = comps[name]
        version = versions[name] if versions is not None and name in versions else installed(name)["version"]
        if version is None:
            if wanted(name):
                out.append({"name": name, "level": "warn", "text": "not installed (`maxxing deps update`)"})
            continue
        problems: list[str] = []
        bad = [f for p in owned_paths(name) for f in foreign_owned(p, c.get("owner", "root"))]
        if bad:
            problems.append("not owned by root or writable by others: " + ", ".join(bad[:3]) + (" ..." if len(bad) > 3 else ""))
        for path, want in (rec.get(name) or {}).get("files", {}).items():
            try:
                if _known_sha(Path(path), shas) != want:
                    problems.append(f"{path} changed since it was installed (sha256)")
            except OSError:
                problems.append(f"{path} is missing")
        if name == "garage" and c.get("sha256"):
            try:
                if _known_sha(expand(c["path"]), shas) != sha_of(c):
                    problems.append("the binary is not the pinned build (sha256)")
            except (OSError, DepError) as e:
                problems.append(str(e))
        if name == "caddy" and Path(c["keyring"]).exists():
            fpr = keyring_fingerprint(Path(c["keyring"]))
            if fpr and fpr != c["key_fingerprint"]:
                problems.append(f"apt key {fpr} is not Caddy's pinned key {c['key_fingerprint']}")
        if name == "remotion":
            mf = expand(c["path"]) / "node_modules" / ".package-lock.json"
            if (rec.get(name) or {}).get("lock") not in (None, lock_hash(c)):
                problems.append("installed from another lockfile (`maxxing deps update remotion`)")
            elif not mf.exists():
                problems.append("node_modules incomplete")
        if problems:
            out.append({"name": name, "level": "fail", "text": "; ".join(problems)})
        else:
            out.append({"name": name, "level": "ok", "text": f"{version} verified"})
    if json.dumps(shas, sort_keys=True) != before:
        _save_sha_cache(shas)
    return out


def keyring_fingerprint(path: Path) -> str | None:
    if not shutil.which("gpg"):
        return None
    with work_dir() as w:
        code, txt = _run(["gpg", "--batch", "--show-keys", "--with-colons", str(path)], timeout=20,
                         env={"GNUPGHOME": str(w)})
    if code != 0:
        return None
    m = re.search(r"^fpr:+([0-9A-F]{40}):", txt, re.M)
    return m.group(1) if m else None


# ---- update ----------------------------------------------------------------------------------------------------
PYTHON_FLOOR = (3, 11)       # requires-python of server/pyproject.toml
UPDATE_ORDER = ("uv", "python", "node", "claude", "scrapling", "chromium", "remotion", "whisper", "garage")


def update(names: list[str] | None = None, log=print, explicit: bool | None = None) -> list[dict]:
    """Bring components to the versions of this release (side by side, checked, then switched).
    `explicit` (default: names given) = the user asked for these: foreign copies may be replaced, the venv moved.
    -> [{"name", "result": "ok"|"updated"|"installed"|"skipped"|"failed", "text"}]"""
    todo = [n for n in UPDATE_ORDER if (names is None or n in names)]
    explicit = (names is not None) if explicit is None else explicit
    report = []
    for name in todo:
        c = get(name)
        if names is None and c.get("update") not in ("auto", "self"):
            continue
        try:
            res, text = _UPDATERS[name](c, explicit=explicit)
        except DepError as e:
            res, text = "failed", str(e)
        except Exception as e:  # noqa: BLE001 - one component never stops the others
            res, text = "failed", f"{type(e).__name__}: {e}"
        report.append({"name": name, "result": res, "text": text})
        log(f"{name}: {res}{' - ' + text if text else ''}")
    return report


def _up_uv(c: dict, explicit: bool = False) -> tuple[str, str]:
    inst = installed("uv")
    if inst["version"] == c["version"] and inst["managed"]:
        return "ok", c["version"]
    if not explicit and (LINK_DIR / "uv").exists() and not _uv_is_ours():
        return "skipped", f"{inst['version'] or '?'} in {LINK_DIR} is not ours: kept (`maxxing deps update uv` replaces it)"
    with work_dir() as w:
        tb = fetch_verified(url_of(c), sha_of(c), w / "uv.tar.gz")
        code, out = _run(["tar", "-xzf", str(tb), "-C", str(w), "--strip-components=1", "--no-same-owner"], timeout=120)
        if code != 0:
            raise DepError("cannot extract uv: " + out[-200:])
        code, out = _run([str(w / "uv"), "--version"], timeout=20)
        if code != 0 or _version_from(out) != c["version"]:
            raise DepError(f"the downloaded uv does not run ({out.strip()[:100]})")
        files = {}
        for f in c.get("files", ["uv"]):
            _replace_file(w / f, LINK_DIR / f)
            files[str(LINK_DIR / f)] = file_sha(LINK_DIR / f)
    write_record("uv", {"version": c["version"], "files": files})
    return ("updated" if inst["version"] else "installed"), f"{inst['version'] or '-'} -> {c['version']}"


def _uv_is_ours() -> bool:
    """/usr/local/bin/uv was put there by us (deps.json, or the installer's manifest), not by another tool."""
    if "uv" in read_record():
        return True
    try:
        return "uv installed" in (config.STATE / "install-manifest").read_text().splitlines()
    except OSError:
        return False


def _up_python(c: dict, explicit: bool = False) -> tuple[str, str]:
    """The pinned Python in <state>/tools/python; the server's venv moves onto it when it used another one."""
    inst = installed("python")
    if (not explicit and not inst["managed"] and inst["version"] and vtuple(inst["version"]) >= PYTHON_FLOOR
            and (config.CODE / "server" / "pyproject.toml").exists()):
        # a working venv on another Python stays: rebuilding it in place while the service and the crons use it
        # breaks them for minutes (`maxxing update` runs this with --auto)
        return "ok", f"{inst['version']} kept ({inst['where']}) - `maxxing deps update python` moves the venv"
    uv = uv_bin()
    if not uv:
        raise DepError("uv is missing (`maxxing deps update uv`)")
    env = uv_env()
    code, out = _run([uv, "python", "install", c["version"]], timeout=900, env=env)
    if code != 0:
        raise DepError("uv python install failed: " + out.strip()[-300:])
    root = expand(c["path"])
    found = sorted((p for p in root.glob(f"cpython-{c['version']}.*/bin/python{c['version']}") if p.is_file()),
                   key=lambda p: vtuple(p.parts[-3].split("-")[1]))
    if not found:
        raise DepError(f"Python {c['version']} not found in {root}")
    managed = found[-1]
    inst = installed("python")
    if inst["managed"] and inst["version"] and inst["version"].startswith(c["version"]):
        return "ok", f"{c['version']} ({expand(c['path'])})"
    if not (config.CODE / "server" / "pyproject.toml").exists():
        return "installed", f"{c['version']} (no server venv here)"
    old = inst["where"]
    venv = _venv_python().parent.parent
    backup = venv.with_name(".venv.pre-python")     # uv recreates the venv in place: keep the one that works
    shutil.rmtree(backup, ignore_errors=True)
    if venv.is_dir():
        shutil.copytree(venv, backup, symlinks=True)
    if _sync_venv(uv, str(managed), env):
        shutil.rmtree(backup, ignore_errors=True)
        return "updated", f"server venv moved to {managed.parent.parent}"
    if backup.is_dir():                              # back to the exact venv that ran, not a rebuild that may fail
        shutil.rmtree(venv, ignore_errors=True)
        os.rename(backup, venv)
    elif old:
        _sync_venv(uv, old, env)                     # back on the interpreter that worked
    raise DepError("the server venv does not work on the managed Python - kept on " + (old or "?"))


def _sync_venv(uv: str, python: str, env: dict) -> bool:
    try:
        from .voice import sync_extras
        extras = sync_extras()
    except Exception:  # noqa: BLE001
        extras = []
    code, _ = _run([uv, "sync", "--frozen", "--no-dev", "--quiet", "--python", python, *extras], timeout=900, env=env,
                   cwd=config.CODE / "server")
    if code != 0:
        return False
    code, _ = _run([str(_venv_python()), "-I", "-c", "import maxxing, fastapi, uvicorn"], timeout=60)
    return code == 0


def _may_link(link: Path, ours: Path) -> bool:
    """/usr/local/bin/<x> may point to our copy: free (and no other <x> on the standard PATH, which the link would
    shadow for every program of the server), already ours, or left by an older installer of ours."""
    if not os.path.lexists(link):
        others = os.pathsep.join(d for d in SYSTEM_PATH if Path(d) != LINK_DIR)
        return shutil.which(link.name, path=others) is None
    if link.is_symlink():
        t = os.readlink(link)
        return t.startswith(str(ours)) or t.startswith(str(config.STATE / "tools"))
    return any(p == link.parent.parent for p in legacy_node_prefixes())


def _up_node(c: dict, explicit: bool = False) -> tuple[str, str]:
    base = node_dir()
    final = base / c["version"]
    cur = base / "current"
    if cur.exists() and cur.resolve() == final.resolve() and (final / "bin" / "node").exists():
        _node_links(c, final)
        return "ok", c["version"]
    before = installed("node")["version"]
    if not (final / "bin" / "node").exists():
        base.mkdir(parents=True, exist_ok=True)
        with work_dir() as w:
            tb = fetch_verified(url_of(c), sha_of(c), w / "node.tar.xz")
            tmp = base / f".{c['version']}.new"
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir()
            # --no-same-owner: the tarball's files belong to uid 1000 - kept as is, that user could replace node
            code, out = _run(["tar", "-xJf", str(tb), "-C", str(tmp), "--strip-components=1", "--no-same-owner",
                              "--no-same-permissions"], timeout=300)
            if code != 0:
                shutil.rmtree(tmp, ignore_errors=True)
                raise DepError("cannot extract Node.js: " + out[-200:])
            code, out = _run([str(tmp / "bin" / "node"), "--version"], timeout=20)
            if code != 0 or out.strip() != f"v{c['version']}":
                shutil.rmtree(tmp, ignore_errors=True)
                raise DepError(f"the downloaded Node.js does not run ({out.strip()[:100]})")
            os.replace(tmp, final)
    if vtuple(c["version"]) < node_required():
        raise DepError(f"Node.js {c['version']} is older than the {'.'.join(map(str, node_required()))} the lockfiles need")
    _symlink(final, cur)
    write_record("node", {"version": c["version"], "files": {str(final / "bin" / "node"): file_sha(final / "bin" / "node")}})
    _node_links(c, final)
    _drop_legacy_node()
    for old in base.iterdir():                        # the previous version once the new one runs
        if old.name not in (c["version"], "current") and old.is_dir() and not old.is_symlink():
            shutil.rmtree(old, ignore_errors=True)
    return ("updated" if before else "installed"), f"{before or '-'} -> {c['version']}"


def _node_links(c: dict, final: Path) -> None:
    cur = node_dir() / "current"
    for n in c.get("links", []):
        link = LINK_DIR / n
        if (final / "bin" / n).exists() and _may_link(link, node_dir()):
            if os.path.lexists(link) and not link.is_symlink():
                link.unlink()                         # a file of the old /usr/local extraction
            _symlink(cur / "bin" / n, link)


def _drop_legacy_node() -> None:
    """Node.js extracted into /usr/local (or <state>/tools/node) by an older installer: removed once ours runs."""
    for pre in legacy_node_prefixes():
        for part in NODE_LEGACY_PARTS:
            p = pre / part
            if p.parent == LINK_DIR and p.is_symlink() and os.readlink(p).startswith(str(node_dir())):
                continue                              # our new link
            if p.is_symlink() or p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        if pre == config.STATE / "tools" / "node":
            shutil.rmtree(pre, ignore_errors=True)
    mf = config.STATE / "install-manifest"
    try:
        lines = mf.read_text().splitlines()
        keep = [ln for ln in lines if not ln.startswith("node ")]
        if keep != lines:
            mf.write_text("".join(ln + "\n" for ln in keep))
    except OSError:
        pass


def _up_claude(c: dict, explicit: bool = False) -> tuple[str, str]:
    """Claude Code updates itself (Settings -> Claude): installed here only when missing, from the pinned build."""
    inst = installed("claude")
    if inst["version"]:
        return "ok", f"{inst['version']} (updates itself)"
    home = root_home()
    with work_dir() as w:
        b = fetch_verified(url_of(c), sha_of(c), w / "claude")
        os.chmod(b, 0o700)
        code, out = _run([str(b), "install", c["version"]], timeout=600,
                         env={"HOME": str(home), "CLAUDE_INSTALL_ALLOW_SUDO": "1"}, cwd=w)
        if code != 0:
            raise DepError("claude install failed: " + out.strip()[-300:])
    target = expand(c["path"])
    if target.exists() and not os.path.lexists(LINK_DIR / "claude"):
        _symlink(target, LINK_DIR / "claude")
    return "installed", c["version"]


def _scrapling_wrappers(venv: Path) -> None:
    cur = scrapling_dir() / "current"
    texts = {
        "scrapling": ("Scrapling with its browser", cur / "bin" / "scrapling"),
        "scrapling-python": ("Python with Scrapling installed (for scraping scripts)", cur / "bin" / "python"),
    }
    for name, (what, target) in texts.items():
        dest = LINK_DIR / name
        body = (f"#!/bin/bash\n# Harness Maxxing wrapper: {what} (written by `maxxing deps update`)\n"
                f"export PLAYWRIGHT_BROWSERS_PATH={browsers_dir()}\nexec {target} \"$@\"\n")
        tmp = dest.with_name(f".{name}.new")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(body)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)


def _up_scrapling(c: dict, explicit: bool = False) -> tuple[str, str]:
    uv = uv_bin()
    if not uv:
        raise DepError("uv is missing")
    base = scrapling_dir()
    final = base / f"{c['version']}-{lock_hash(c)}"
    cur = base / "current"
    before = installed("scrapling")["version"]
    if not (cur.exists() and cur.resolve() == final.resolve() and (final / "bin" / "scrapling").exists()):
        base.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(final, ignore_errors=True)
        env = uv_env()
        py = get("python")["version"]
        code, out = _run([uv, "venv", "--quiet", "--python", py, str(final)], timeout=600, env=env)
        if code == 0:
            code, out = _run([uv, "pip", "install", "--quiet", "--require-hashes", "-r", str(lock_path(c)),
                              "--python", str(final / "bin" / "python")], timeout=1200, env=env)
        if code == 0:
            code, out = _run([str(final / "bin" / "python"), "-I", "-c", "import scrapling.fetchers"], timeout=120)
        if code != 0:
            shutil.rmtree(final, ignore_errors=True)
            raise DepError("Scrapling install failed (kept the previous one): " + out.strip()[-300:])
        _symlink(final, cur)
        for old in base.iterdir():
            if old.name not in (final.name, "current") and old.is_dir() and not old.is_symlink():
                shutil.rmtree(old, ignore_errors=True)
        legacy = config.STATE / "tools" / "uv" / "scrapling"
        shutil.rmtree(legacy, ignore_errors=True)
        for d in (config.STATE / "tools" / "uv", config.STATE / "tools" / "bin"):
            shutil.rmtree(d, ignore_errors=True)
        write_record("scrapling", {"version": c["version"], "lock": lock_hash(c)})
        res = "updated" if before else "installed"
    else:
        res = "ok"
    _scrapling_wrappers(final)
    return res, f"{before or '-'} -> {c['version']}" if res != "ok" else c["version"]


def missing_libs(binary: Path) -> list[str]:
    code, out = _run(["ldd", str(binary)], timeout=30)
    return sorted({ln.split()[0] for ln in out.splitlines() if "not found" in ln})


def _up_chromium(c: dict, explicit: bool = False) -> tuple[str, str]:
    py = scrapling_python()
    if not py:
        raise DepError("Scrapling is not installed (its Playwright brings the browser)")
    revs = playwright_revisions(py)
    if not revs:
        raise DepError("no Playwright driver in the Scrapling venv")
    env = {"PLAYWRIGHT_BROWSERS_PATH": str(browsers_dir())}
    done = []
    for mod, rev in sorted(revs.items()):
        d = browsers_dir() / f"chromium-{rev}"
        if (d / "INSTALLATION_COMPLETE").exists() and chromium_bin(rev):
            continue
        code, out = _run([str(py), "-m", mod, "install", "--no-shell", "chromium"], timeout=1800, env=env)
        if code != 0 or not chromium_bin(rev):
            raise DepError(f"{mod} could not download Chromium {rev}: {out.strip()[-300:]}")
        done.append(rev)
    b = chromium_bin(max(revs.values()))
    if b and missing_libs(b):
        code, out = _run([str(py), "-m", "playwright", "install-deps", "chromium"], timeout=1800, env=env)
        if missing_libs(b):
            raise DepError("Chromium misses system libraries: " + ", ".join(missing_libs(b)[:5]))
    if b:
        write_record("chromium", {"version": b.parent.parent.name, "files": {str(b): file_sha(b)}})
    return ("installed" if done else "ok"), ", ".join(sorted(set(revs.values())))


def _up_remotion(c: dict, explicit: bool = False) -> tuple[str, str]:
    dest = expand(c["path"])
    have = installed("remotion")["version"]
    rec = read_record().get("remotion") or {}
    if have == c["version"] and rec.get("lock") in (None, lock_hash(c)) and (dest / "node_modules" / ".package-lock.json").exists():
        if rec.get("lock") is None:
            write_record("remotion", {"version": c["version"], "lock": lock_hash(c)})
        return "ok", c["version"]
    n = node_bin()
    if not n:
        raise DepError("Node.js is missing (`maxxing deps update node`)")
    new = dest.with_name(dest.name + ".new")
    old = dest.with_name(dest.name + ".old")
    shutil.rmtree(new, ignore_errors=True)
    shutil.copytree(config.CODE / "templates" / "remotion", new, ignore=shutil.ignore_patterns("node_modules", "out"))
    npm = n.parent / "npm"
    code, out = _run([str(npm), "ci", "--no-audit", "--no-fund", "--loglevel=error"], timeout=1800, cwd=new,
                     env={**_node_env(), "PUPPETEER_SKIP_DOWNLOAD": "1"})
    if code == 0:
        code, out = _run([str(n), "-p", "require('remotion/package.json').version"], timeout=60, cwd=new)
    if code != 0 or out.strip() != c["version"]:
        shutil.rmtree(new, ignore_errors=True)
        raise DepError("npm ci of Remotion failed (kept the previous one): " + out.strip()[-300:])
    shutil.rmtree(old, ignore_errors=True)
    if dest.exists():
        os.replace(dest, old)
    os.replace(new, dest)
    shutil.rmtree(old, ignore_errors=True)
    write_record("remotion", {"version": c["version"], "lock": lock_hash(c)})
    return ("updated" if have else "installed"), f"{have or '-'} -> {c['version']}"


def _up_whisper(c: dict, explicit: bool = False) -> tuple[str, str]:
    from . import voice
    s = voice.settings()
    if s.get("engine") != "local" and not explicit:
        return "skipped", "voice is not local"
    if not voice.local_installed():
        return "skipped", "faster-whisper is not installed (Settings -> Voice)"
    model = s.get("model") or "base"
    rec = read_record().get("whisper") or {}
    pinned = (c.get("revisions") or {}).get(model)
    if voice.model_present(model) and rec.get(model) in (None, pinned):
        if rec.get(model) is None:
            write_record("whisper", {**rec, model: pinned})
        return "ok", model
    if voice.model_present(model):                     # another revision: download the pinned one next to it
        shutil.rmtree(voice.model_path(model), ignore_errors=True)
    voice.download_model(model)
    write_record("whisper", {**rec, model: pinned})
    return "installed", f"{model} @ {str(pinned)[:8]}"


def _up_garage(c: dict, explicit: bool = False) -> tuple[str, str]:
    p = expand(c["path"])
    if not p.exists():
        return "skipped", "not installed (maxxing infra bucket install)"
    if file_sha(p) == sha_of(c):
        return "ok", c["version"]
    if not explicit:
        return "skipped", "another build is installed (`maxxing deps update garage` replaces it)"
    with work_dir() as w:
        b = fetch_verified(url_of(c), sha_of(c), w / "garage")
        _replace_file(b, p)
    _run(["systemctl", "try-restart", "garage"], timeout=60)
    return "updated", c["version"]


def _up_noop(c: dict, explicit: bool = False) -> tuple[str, str]:
    return "skipped", "system package (security updates: unattended-upgrades)"


_UPDATERS = {"uv": _up_uv, "python": _up_python, "node": _up_node, "claude": _up_claude, "caddy": _up_noop,
             "scrapling": _up_scrapling, "chromium": _up_chromium, "remotion": _up_remotion, "whisper": _up_whisper,
             "garage": _up_garage}


# ---- remove ----------------------------------------------------------------------------------------------------
ESSENTIAL = ("uv", "python", "claude")


def remove(name: str, force: bool = False) -> list[str]:
    """Delete what the manifest lists for a component -> the paths removed."""
    c = get(name)
    if name in ESSENTIAL and not force:
        raise DepError(f"{name} is needed by Harness Maxxing itself (only `maxxing uninstall --purge` removes it)")
    if name == "caddy" and not force:
        raise DepError("Caddy serves the domain: remove it with apt (`apt-get purge caddy`) after `maxxing uninstall`")
    gone = []
    for p in [expand(x) for x in c.get("remove", [])]:
        if name == "claude" and p.parent == LINK_DIR and p.is_symlink() and not os.readlink(p).startswith(str(root_home())):
            continue
        if p.is_symlink() or p.is_file():
            p.unlink()
            gone.append(str(p))
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            gone.append(str(p))
    if name == "node":
        for n in c.get("links", []):
            link = LINK_DIR / n
            if link.is_symlink() and os.readlink(link).startswith(str(node_dir())):
                link.unlink()
                gone.append(str(link))
    write_record(name, None)
    return gone


# ---- clean -----------------------------------------------------------------------------------------------------
def _size(p: Path) -> int:
    if p.is_symlink() or p.is_file():
        try:
            return p.lstat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            with contextlib.suppress(OSError):
                total += os.lstat(os.path.join(root, f)).st_size
    return total


def _drop(p: Path, why: str, out: list[dict], dry: bool) -> None:
    if not os.path.lexists(p):
        return
    size = _size(p)
    if not dry:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)
    out.append({"path": str(p), "why": why, "bytes": size})


def clean(dry: bool = False, caches: bool = False) -> list[dict]:
    """Caches (`caches`: root's uv/npm/pip/npx caches, shared with every other tool of the server - MCP servers run
    from ~/.npm/_npx - so only on request), old versions, orphan browsers, leftovers and oversized logs -> what went."""
    out: list[dict] = []
    home = root_home()
    tools = config.STATE / "tools"
    # caches (re-downloaded when needed)
    for p, why in ((home / ".cache" / "uv", "uv cache"), (home / ".npm" / "_cacache", "npm cache"),
                   (home / ".cache" / "pip", "pip cache"), (home / ".npm" / "_npx", "npx cache"),
                   (home / ".claude" / "downloads", "Claude Code installer downloads")) if caches else ():
        _drop(p, why, out, dry)
    # old versions next to the one in use
    for base in (node_dir(), scrapling_dir()):
        cur = base / "current"
        if cur.exists() and base.is_dir():
            for d in base.iterdir():
                if d.name != "current" and d.resolve() != cur.resolve():
                    _drop(d, "old version", out, dry)
    used_py = {p.resolve() for p in (_venv_python(), scrapling_python()) if p and p.exists()}
    pyroot = expand(get("python")["path"])
    if pyroot.is_dir() and used_py:
        for d in pyroot.iterdir():
            if d.is_dir() and d.name.startswith("cpython-") and not any(u.is_relative_to(d.resolve()) for u in used_py):
                _drop(d, "Python no longer used", out, dry)
    # browsers no Playwright of the venv needs (and the second browser older installs had for Remotion)
    revs = set(playwright_revisions().values())
    if revs and browsers_dir().is_dir():
        for d in browsers_dir().iterdir():
            if d.is_dir() and d.name.startswith(("chromium-", "chromium_headless_shell-")) and d.name.split("-", 1)[1] not in revs:
                _drop(d, "browser no longer used", out, dry)
            if d.is_dir() and d.name.startswith("chromium_headless_shell-"):
                _drop(d, "headless shell (the full Chromium is used)", out, dry)
    if chromium_bin():
        _drop(expand(get("remotion")["path"]) / "node_modules" / ".remotion", "Remotion's own browser (renders use Chromium)", out, dry)
    # leftovers of interrupted runs
    for p in (tools / "remotion.new", tools / "remotion.old"):
        _drop(p, "leftover of an interrupted run", out, dry)
    tmp = config.STATE / "tmp"
    if tmp.is_dir():
        for p in tmp.iterdir():                         # a day old: no run of ours still uses it
            with contextlib.suppress(OSError):
                if time.time() - p.lstat().st_mtime > 86400:
                    _drop(p, "temporary file of an earlier run", out, dry)
    if scrapling_dir().joinpath("current").exists():
        _drop(tools / "uv", "Scrapling of an older installer", out, dry)
        _drop(tools / "bin", "Scrapling of an older installer", out, dry)
    for d in (node_dir(), scrapling_dir()):
        if d.is_dir():
            for x in d.glob(".*.new"):
                _drop(x, "leftover of an interrupted run", out, dry)
    # logs
    logs = config.STATE / "logs"
    if logs.is_dir():
        now = time.time()
        for d in logs.glob("install-failed-*"):
            with contextlib.suppress(OSError):
                if now - d.stat().st_mtime > FAILED_LOGS_DAYS * 86400:
                    _drop(d, "old installer log", out, dry)
        for f in logs.glob("*.log"):
            with contextlib.suppress(OSError):
                size = f.stat().st_size
                if size > LOG_MAX:
                    if not dry:
                        with open(f, "rb") as fh:
                            fh.seek(-LOG_KEEP, os.SEEK_END)
                            tail = fh.read()
                        f.write_bytes(tail)
                    out.append({"path": str(f), "why": "log cut to its last 1 MB", "bytes": size - LOG_KEEP})
    return out


# ---- vulnerabilities (OSV) -------------------------------------------------------------------------------------
def requirement_pins(lock: Path) -> list[tuple[str, str]]:
    try:
        text = lock.read_text()
    except OSError:
        return []
    return [(m.group(1), m.group(2)) for m in re.finditer(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", text, re.M)]


def check(timeout: float = 30) -> dict:
    """Known vulnerabilities in what this install runs: the lockfiles (server, web, Remotion, Scrapling) and the
    installed versions of the components. Raises on network errors."""
    from . import depcheck
    r = depcheck.osv_scan(timeout)
    queries: list[tuple[str, str, str, str]] = []
    for name, eco, pkgs in (("scrapling", "PyPI", requirement_pins(lock_path(get("scrapling")))),):
        queries += [(name, eco, n, v) for n, v in pkgs]
    for name, c in load().items():
        osv = c.get("osv")
        if not osv:
            continue
        v = installed(name)["version"]
        if v and re.match(r"^\d", v.lstrip("v")):
            queries.append((name, osv["ecosystem"], osv["name"], v.lstrip("v")))
    found = list(r["vulnerable"])
    for i in range(0, len(queries), 500):
        chunk = queries[i:i + 500]
        res = depcheck._post_json(depcheck.OSV_BATCH, {"queries": [
            {"package": {"ecosystem": e, "name": n}, "version": v} for _, e, n, v in chunk]}, timeout)
        for (where, eco, name, version), q in zip(chunk, res.get("results") or []):
            if q.get("vulns"):
                found.append({"where": where, "ecosystem": eco, "name": name, "version": version,
                              "ids": [x.get("id") for x in q["vulns"]][:5]})
    return {"checked": r["checked"] + len(queries), "vulnerable": found}


def notify_vulnerable(result: dict) -> bool:
    """Feed (+ the Telegram alerts thread) when something has a known vulnerability; once per set of advisories."""
    vul = result.get("vulnerable") or []
    if not vul:
        return False
    from . import feed
    lines = [f"{v['where']}: {v['name']} {v['version']} ({', '.join(x for x in v['ids'] if x)})" for v in vul]
    key = hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()[:16]
    body = ("\n".join(lines[:20]) + ("\n..." if len(lines) > 20 else "")
            + "\n\nA newer Harness Maxxing release may already fix it: maxxing update --check")
    try:
        ev = feed.post(f"{len(lines)} dependency(ies) with a known vulnerability", body, "warning", "system",
                       "/settings", dedupe=f"deps-check:{key}")
    except Exception:  # noqa: BLE001 - never break the job for the feed
        ev = None
    if ev is None:
        return False                                   # already reported (same advisories)
    try:
        from .telegram import gateway
        gateway.system_alert(f"Known vulnerability in {len(lines)} dependency(ies) of Harness Maxxing:\n" + "\n".join(lines[:10]))
    except Exception:  # noqa: BLE001 - Telegram is optional
        pass
    return True


# ---- default jobs ----------------------------------------------------------------------------------------------
def default_jobs(mx: str) -> list[tuple[str, dict]]:
    """Weekly cleanup and vulnerability check (created once by `maxxing init`, like the other default jobs)."""
    return [
        ("deps-clean", {"name": "Clean caches and old versions", "schedule": "30 4 * * 0", "kind": "shell",
                        "command": f"{mx} deps clean --quiet", "enabled": True, "notify": "failure",
                        "timeout_s": 600}),
        ("deps-check", {"name": "Check dependencies for vulnerabilities", "schedule": "0 10 * * 1", "kind": "shell",
                        "command": f"{mx} deps check --notify", "enabled": True, "notify": "never",
                        "timeout_s": 300}),
    ]
