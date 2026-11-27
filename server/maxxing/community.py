"""What a package from outside does, read before it is installed (`maxxing community check|install|list`).

A package is an extension (`manifest.json`, maybe an `api.py` that runs inside the server), a skill (`SKILL.md`,
maybe scripts) or a theme (`theme.json`), given as a folder or a zip. `report(path)` copies it into a fresh
temporary folder (a zip goes through importer's entry checks: caps, no absolute path, no `..`, no symbolic link),
reads the bytes and lists, with file and line: code that runs on the server, network calls and hosts, keys and
secret files it reads, processes it starts, downloads it runs, paths outside its folder. Nothing of the package is
ever imported or executed.

It is a reading aid, not a verdict: a pattern search finds what is written plainly and misses what is hidden on
purpose. An empty list never means a package is harmless; the owner (or Claude, for them) still reads the code.

Pinning: `install(path, sha256=...)` takes its own copy, computes the hash of that copy and refuses when it is not
the one the report was shown for; what is installed is the copy that was hashed. `<state>/installed.json` keeps
{kind, id, sha256, installed_sha256, source, installed_at} per package (`installed()`).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from . import config

KINDS = ("extension", "skill", "theme")
MAX_FILES = 2000
MAX_TOTAL = 50 * 1024 * 1024
SCAN_MAX = 1024 * 1024                 # a text file over it is listed as not read
LINE_MAX = 2000
PER_RULE_FILE = 6                      # findings of one rule in one file; the rest is counted
MAX_FINDINGS = 400
JUNK = {"__MACOSX", ".git", "node_modules", ".venv", "venv", "__pycache__", ".DS_Store", "Thumbs.db"}
OWN_FILES = {".css-check.json"}        # written by the product in an installed folder: not part of the package
SKILL_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")

TEXT_EXT = {".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".htm", ".md",
            ".json", ".css", ".yaml", ".yml", ".toml", ".txt", ".cfg", ".ini", ".rb", ".pl", ".php", ".ps1", ".svg",
            ".xml", ".env"}
SCRIPT_EXT = {".py", ".sh", ".bash", ".zsh", ".rb", ".pl", ".php", ".ps1"}
JS_EXT = {".js", ".mjs", ".cjs", ".ts"}
QUIET_EXT = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".mp4",
             ".webm", ".mp3", ".pdf"}
BROWSER_FILES = {"page.js", "widget.html", "agents-view.html"}
_NODE = re.compile(r"\brequire\s*\(|\bprocess\.(?:env|argv|exit|cwd)|from\s+['\"]node:|child_process|^#!.*\bnode\b",
                   re.M)

INFO, WARN, DANGER = "info", "warn", "danger"


class PackageError(Exception):
    pass


class PackageChanged(PackageError):
    """The content is not the one the report was shown for."""


class NeedsConfirmation(PackageError):
    """Danger findings: the owner has to say they read the report."""


# ---------------------------------------------------------------------------------------------- the copy

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _base_name(path: Path) -> str:
    n = path.stem if path.is_file() else path.name
    return n if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", n) else "package"


def _copy_zip(path: Path, dest: Path) -> list[dict]:
    from . import importer
    try:
        with importer._open(path) as zf:
            entries, skipped = importer._entries(zf)
            if len(entries) > MAX_FILES:
                raise PackageError(f"more than {MAX_FILES} files")
            if sum(i.file_size for i, _ in entries) > MAX_TOTAL:
                raise PackageError(f"more than {MAX_TOTAL // 1024 // 1024} MB once unzipped")
            total = 0
            for info, rel in entries:
                out = dest.joinpath(*rel.parts)
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(out, "xb") as dst:
                    while chunk := src.read(1 << 16):
                        total += len(chunk)
                        if total > MAX_TOTAL:
                            raise PackageError(f"more than {MAX_TOTAL // 1024 // 1024} MB once unzipped")
                        dst.write(chunk)
            return skipped
    except importer.ImportFailed as e:
        raise PackageError(e.message) from None
    except importer._UNREADABLE:
        raise PackageError("a file of the zip cannot be read (encrypted or damaged)") from None


def _copy_folder(src: Path, dest: Path) -> list[dict]:
    skipped: list[dict] = []
    count = total = 0
    for cur, dirs, names in os.walk(src, followlinks=False):
        rel_dir = Path(cur).relative_to(src)
        keep = []
        for d in sorted(dirs):
            if d in JUNK:
                continue
            if (Path(cur) / d).is_symlink():
                skipped.append({"file": str(rel_dir / d), "reason": "symbolic link"})
                continue
            keep.append(d)
        dirs[:] = keep
        for n in sorted(names):
            if n in JUNK or n in OWN_FILES:
                continue
            f, rel = Path(cur) / n, rel_dir / n
            try:
                fd = os.open(f, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            except OSError:
                skipped.append({"file": str(rel), "reason": "symbolic link" if f.is_symlink() else "unreadable"})
                continue
            with os.fdopen(fd, "rb") as fh:
                if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                    skipped.append({"file": str(rel), "reason": "not a regular file"})
                    continue
                count += 1
                if count > MAX_FILES:
                    raise PackageError(f"more than {MAX_FILES} files")
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                with open(out, "xb") as dst:
                    while chunk := fh.read(1 << 16):
                        total += len(chunk)
                        if total > MAX_TOTAL:
                            raise PackageError(f"more than {MAX_TOTAL // 1024 // 1024} MB")
                        dst.write(chunk)
    return skipped


@contextlib.contextmanager
def snapshot(path: Path) -> Iterator[tuple[Path, list[dict]]]:
    """A private copy of the package in a fresh temporary folder (removed on exit): (its root, entries left out)."""
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise PackageError(f"{path}: no such folder or zip")
    tmp = Path(tempfile.mkdtemp(prefix="mx-pkg-"))
    try:
        root = tmp / _base_name(path)
        root.mkdir()
        try:
            skipped = _copy_folder(path, root) if path.is_dir() else _copy_zip(path, root)
        except OSError as e:
            raise PackageError(f"cannot read the package: {e.strerror or e}") from None
        yield root, skipped
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _files(root: Path) -> list[str]:
    out = []
    for cur, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in JUNK and not (Path(cur) / d).is_symlink())
        for n in names:
            f = Path(cur) / n
            if n not in JUNK and n not in OWN_FILES and f.is_file() and not f.is_symlink():
                out.append(f.relative_to(root).as_posix())
    return sorted(out)


def tree_hash(root: Path) -> str:
    """sha256 of the content: every relative path (sorted) with the sha256 of its bytes. No date, no mode."""
    h = hashlib.sha256()
    for rel in _files(root):
        h.update(rel.encode("utf-8", "surrogateescape") + b"\0" + _sha((root / rel).read_bytes()).encode() + b"\n")
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------- the rules

_HOST = re.compile(r"\b(?:https?|wss?|ftp)://(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)")
_IP = re.compile(r"\[.*\]|\d{1,3}(?:\.\d{1,3}){3}")
_LOCAL = {"localhost", "127.0.0.1", "0.0.0.0", "[::1]"}
_QUIET_HOSTS = {"www.w3.org", "json-schema.org", "schema.org", "example.com", "www.example.com"}
_ENV_PLAIN = {"HOME", "PATH", "LANG", "LC_ALL", "TZ", "USER", "PWD", "TMPDIR", "SHELL", "TERM", "NODE_ENV"}

_SECRET_NAME = [
    re.compile(r"""ctx\s*\[\s*["']secret["']\s*\]\s*\(\s*["']([^"'\n]{1,80})["']"""),
    re.compile(r"""ctx\s*\.\s*secret\s*\(\s*["']([^"'\n]{1,80})["']"""),
]
_SECRET_ANY = re.compile(r"""ctx\s*(?:\[\s*["']secret["']\s*\]|\.\s*secret\b)""")
_ENV_NAME = [
    re.compile(r"""os\.environ(?:\.get|\.pop)?\s*[\[(]\s*["']([A-Za-z_][A-Za-z0-9_]*)["']"""),
    re.compile(r"""os\.getenv\s*\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']"""),
    re.compile(r"""process\.env\.([A-Za-z_][A-Za-z0-9_]*)"""),
    re.compile(r"""process\.env\s*\[\s*["']([A-Za-z_][A-Za-z0-9_]*)["']"""),
]
_ENV_ALL = re.compile(r"os\.environ\b(?!\s*(?:\.get|\.pop)?\s*[\[(]\s*[\"'])|\bprocess\.env\b(?!\s*[.\[])"
                      r"|(?:^|[\s;|&(`])printenv\b|(?:^|[;|&(`]\s*)env\s*(?:$|[|>])")

# (code, level, what, pattern): every one is tried on every line of every text file
_LINE_RULES: list[tuple[str, str, str, re.Pattern[str]]] = [
    ("network", INFO, "network call", re.compile(
        r"\burllib\.request\b|\burllib3\b|\burlopen\s*\(|\brequests\.(?:get|post|put|patch|delete|head|request|Session)\b"
        r"|\bhttpx\b|\baiohttp\b|\bhttp\.client\b|\bsocket\.(?:socket|create_connection)\b|\bimport\s+socket\b"
        r"|\bimport\s+requests\b|\bwebsockets?\.connect\b|\bsmtplib\b|\bftplib\b|\bparamiko\b|\btelnetlib\b"
        r"|(?<![.\w])fetch\s*\(|\bXMLHttpRequest\b|\bnew\s+WebSocket\b|\bnew\s+EventSource\b|\bsendBeacon\s*\("
        r"|\baxios\b|\brequire\s*\(\s*['\"](?:node:)?(?:https?|net|dgram|tls)['\"]"
        r"|(?:^|[\s;&|`(\"'])(?:curl|wget)\s+\S|\bnc\s+-|\bInvoke-WebRequest\b")),
    ("secret-file", DANGER, "refers to a file that holds secrets", re.compile(
        r"secrets\.json|\.credentials\.json|\.claude\.json|claude_oauth|(?<![\w.])\.ssh\b|\bid_(?:rsa|ed25519|ecdsa)\b"
        r"|authorized_keys|\.netrc\b|\.aws/credentials|\.git-credentials|/etc/shadow|\.config/gh\b|vault\.json"
        r"|/var/lib/claude-maxxing|\.gnupg\b|\.kube/config|\.docker/config\.json")),
    ("secret-file", WARN, "refers to a .env file", re.compile(r"(?<![\w.])\.env\b(?![\w(])")),
    ("download-run", DANGER, "downloads a script and runs it", re.compile(
        r"(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:(?:ba|z|da|k)?sh|python[0-9.]*|node|perl|ruby)\b"
        r"|(?:(?:ba|z)?sh|python[0-9.]*|source|\.)\s+<\(\s*(?:curl|wget)"
        r"|(?:(?:ba|z)?sh|python[0-9.]*)\s+-c\s+[\"']?\$\(\s*(?:curl|wget)"
        r"|\b(?:iex|Invoke-Expression)\b.*(?:DownloadString|Invoke-WebRequest|iwr)", re.I)),
    ("encoded-run", DANGER, "decodes text and runs it", re.compile(
        r"(?:b(?:64|32|85)decode|fromhex|atob\s*\(|base64\s+(?:-d|--decode|-D)\b|codecs\.decode|zlib\.decompress"
        r"|Buffer\.from\([^)\n]*base64).*(?:(?<![.\w])(?:exec|eval)\s*\(|\|\s*(?:ba|z)?sh\b|Function\s*\(|subprocess"
        r"|os\.system|child_process)"
        r"|(?:(?<![.\w])(?:exec|eval)\s*\(|Function\s*\(|os\.system|subprocess).*(?:b(?:64|32|85)decode|fromhex"
        r"|atob\s*\(|codecs\.decode|zlib\.decompress|marshal\.loads)")),
    ("process", WARN, "starts a process", re.compile(
        r"\bsubprocess\b|\bos\.(?:system|popen|exec[lv]p?e?|spawn[lv]p?e?|fork)\s*\(|\bpty\.spawn\b|child_process"
        r"|\bexecSync\b|\bspawnSync\b|\bshell\s*=\s*True\b|\bPopen\s*\(|\bStart-Process\b")),
    ("dynamic-code", WARN, "runs code built at run time", re.compile(
        r"(?<![.\w])(?:eval|exec)\s*\(|\bnew\s+Function\s*\(|\b__import__\s*\(|\bimportlib\b|\bmarshal\.loads\b"
        r"|\bpickle\.loads?\b|\bctypes\b|\bcompile\s*\([^)\n]*['\"]exec['\"]")),
    ("install", WARN, "downloads and installs more code", re.compile(
        r"\bpip[0-9.]*\s+install\b|\buv\s+(?:pip\s+install|add|tool\s+install)\b|\buvx\s|\bnpm\s+(?:install|i|ci|add|exec)\b"
        r"|\bnpx\s|\byarn\s+(?:add|install|dlx)\b|\bpnpm\s+(?:add|install|dlx)\b|\bapt(?:-get)?\s+(?:-\w+\s+)*install\b"
        r"|\bbrew\s+install\b|\b(?:go|cargo|gem)\s+install\b|\bgit\s+clone\b|\bdocker\s+(?:run|pull)\b")),
    ("privilege", WARN, "asks for root or keeps something running", re.compile(
        r"(?:^|[\s;&|`(])sudo\s+\S|\bcrontab\b|/etc/cron|\bsystemctl\s+(?:enable|start|daemon-reload)\b"
        r"|/etc/systemd|\.bashrc\b|\.profile\b|\.zshrc\b|\bnohup\s|\bchmod\s+(?:-\w+\s+)*(?:\+s|[0-7]?[4-7]7{2})\b")),
    ("outside-path", WARN, "path outside its own folder", re.compile(
        r"""(?:["'`\s=(:]|^)(/(?:etc|root|home|var|usr|opt|srv|boot|bin|sbin|lib|tmp|dev|proc|sys)(?:/[^\s"'`)<>]*)?)(?=["'`\s),;]|$)"""
        r"""|(?:^|["'`\s=(])(\.\./[^\s"'`)]*)|(?:^|["'`\s=(])(~/[^\s"'`)]*)|\$\{?HOME\b|\bexpanduser\s*\(|\bPath\.home\s*\("""
        r"""|\bos\.homedir\s*\(|\bconfig\.(?:workspace|state_dir|claude_dir|files_root)\s*\(""")),
    ("destroy", DANGER, "deletes outside its folder", re.compile(
        r"\brm\s+(?:-\w+\s+)*(?:/|~|\$\{?HOME\}?)(?:[\s/*]|$)|\bmkfs\b|\bdd\s+[^\n]*\bof=/dev/|\bshutil\.rmtree\s*\(\s*[\"']/")),
]
_BLOB = re.compile(r"[A-Za-z0-9+/=_-]{400,}")
_CSS_REMOTE = re.compile(r"url\s*\(\s*[\"']?\s*(?:https?:)?//|@import\b|image-set\s*\(|src\s*\(", re.I)
_HOOK_LINE = re.compile(r"^\s*[\"']?hooks[\"']?\s*:", re.I)
_TOOLS_LINE = re.compile(r"^\s*allowed-tools\s*:\s*(.*)$", re.I)


def _excerpt(line: str) -> str:
    s = " ".join(line.strip().split())
    return s if len(s) <= 160 else s[:157] + "..."


class _Findings:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.seen: dict[tuple, int] = {}
        self.more: dict[tuple, int] = {}

    def add(self, level: str, code: str, what: str, file: str, line: int = 0, excerpt: str = "",
            key: Any = None) -> None:
        """`key`: a finding with the same key in the same file is kept once (a host, a key name)."""
        if key is not None:
            k = (code, file, key)
            if k in self.seen:
                return
            self.seen[k] = 1
        else:
            k = (code, file, level, what)
            n = self.seen[k] = self.seen.get(k, 0) + 1
            if n > PER_RULE_FILE:
                self.more[k] = self.more.get(k, 0) + 1
                return
        if len(self.items) < MAX_FINDINGS:
            self.items.append({"level": level, "code": code, "what": what, "file": file, "line": line,
                               "excerpt": _excerpt(excerpt)})

    def done(self) -> list[dict]:
        for (code, file, level, what), n in self.more.items():
            if len(self.items) < MAX_FINDINGS:
                self.items.append({"level": level, "code": code, "what": f"{what}: {n} more line(s) in this file",
                                   "file": file, "line": 0, "excerpt": ""})
        order = {DANGER: 0, WARN: 1, INFO: 2}
        return sorted(self.items, key=lambda f: (order[f["level"]], f["file"], f["line"]))


def _role(kind: str, rel: str, text: str | None) -> str:
    """server | script | browser | text: where the file's code would run."""
    p = PurePosixPath(rel)
    ext = p.suffix.lower()
    shebang = bool(text and text.startswith("#!"))
    if kind == "extension" and rel == "api.py":
        return "server"
    if ext in SCRIPT_EXT or (shebang and ext not in JS_EXT):
        return "script"
    if ext in JS_EXT:
        if kind == "extension" and p.name in BROWSER_FILES:
            return "browser"
        return "script" if kind == "skill" or shebang or (text and _NODE.search(text)) else "browser"
    if ext in (".html", ".htm"):
        return "browser"
    return "text"


def _scan_text(fs: _Findings, kind: str, rel: str, text: str, role: str) -> None:
    code = role != "text"
    for n, raw in enumerate(text.split("\n"), 1):
        if not raw.strip():
            continue
        if len(raw) > LINE_MAX:
            if code:
                fs.add(WARN, "unreadable", "very long line (minified or packed code): not readable by eye", rel, n,
                       raw[:120])
            line = raw[:LINE_MAX]
        else:
            line = raw
        for m in _HOST.finditer(line):
            host = m.group(1).lower()
            if host in _QUIET_HOSTS:
                continue
            if host in _LOCAL:
                fs.add(INFO, "host", f"address on this server: {host}", rel, n, line, key=host)
            elif _IP.fullmatch(host):
                fs.add(WARN, "host", f"network destination by raw IP address: {host}", rel, n, line, key=host)
            elif role == "browser" and kind == "extension":
                fs.add(WARN, "host", f"code in your browser (signed in to Harness) names the host {host}", rel, n,
                       line, key=host)
            else:
                fs.add(INFO, "host", f"network destination: {host}", rel, n, line, key=host)
        named = False
        for rx in _SECRET_NAME:
            for m in rx.finditer(line):
                named = True
                fs.add(INFO, "vault-key", f"reads the key {m.group(1)} from the vault", rel, n, line, key=m.group(1))
        if not named and _SECRET_ANY.search(line) and code:
            fs.add(WARN, "vault-key", "reads a key from the vault whose name is not written plainly", rel, n, line)
        for rx in _ENV_NAME:
            for m in rx.finditer(line):
                name = m.group(1)
                fs.add(INFO if name in _ENV_PLAIN else WARN, "env", f"reads the environment variable {name}", rel, n,
                       line, key=name)
        if _ENV_ALL.search(line) and (code or "os.environ" in line or "process.env" in line):
            fs.add(WARN, "env", "reads the whole environment (the keys exposed to sessions are in it)", rel, n, line)
        for rcode, level, what, rx in _LINE_RULES:
            if rx.search(line):
                fs.add(level, rcode, what, rel, n, line)
        if code and _BLOB.search(line):
            fs.add(WARN, "unreadable", "long encoded text: not readable by eye", rel, n, line[:120])


def _front_matter(fs: _Findings, rel: str, text: str) -> None:
    from . import importer
    lines = text.removeprefix("\ufeff").split("\n")
    if not lines or lines[0].strip() != "---":
        return
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), len(lines))
    hook = next((i for i in range(1, end) if _HOOK_LINE.match(lines[i])), None)
    if hook is not None:
        fs.add(DANGER, "skill-hooks", "hooks in the front matter: commands that run by themselves in a session", rel,
               hook + 1, lines[hook])
    elif importer._strip_skill_hooks(text) != text.removeprefix("\ufeff"):
        fs.add(DANGER, "skill-hooks", "front matter written in a way that can hide a hooks field", rel, 1, lines[0])
    for i in range(1, end):
        m = _TOOLS_LINE.match(lines[i])
        if m:
            fs.add(WARN, "skill-tools", "allows tools without asking (allowed-tools)", rel, i + 1, lines[i])


def _theme_checks(fs: _Findings, root: Path) -> None:
    from . import themes
    try:
        raw = (root / "theme.json").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    lines = raw.split("\n")
    for n, line in enumerate(lines, 1):
        if _CSS_REMOTE.search(line):
            fs.add(WARN, "theme-remote", "remote url() or @import in the CSS (the interface refuses such CSS)",
                   "theme.json", n, line)
    try:
        data = json.loads(raw)
    except ValueError:
        fs.add(WARN, "theme-invalid", "theme.json is not valid JSON", "theme.json", 1, "")
        return
    if not isinstance(data, dict):
        return
    css = data.get("css")
    if css:
        warn: list[str] = []
        themes._css(css, warn)
        n = next((i for i, ln in enumerate(lines, 1) if re.search(r'"css"\s*:', ln)), 1)
        for w in warn:
            fs.add(WARN, "theme-css", f"advanced CSS refused by the interface ({w})", "theme.json", n, "")
        if not warn:
            fs.add(INFO, "theme-css", "has advanced CSS (applied to the whole interface once verified)", "theme.json",
                   n, lines[n - 1] if n <= len(lines) else "")


# ---------------------------------------------------------------------------------------------- the report

MARKER = {"extension": "manifest.json", "skill": "SKILL.md", "theme": "theme.json"}


def detect_kind(root: Path) -> str:
    for kind, name in MARKER.items():
        if (root / name).is_file():
            return kind
    raise PackageError("not a package: no manifest.json (extension), SKILL.md (skill) or theme.json (theme) at its "
                       "top; give the folder that holds it")


def _json(path: Path) -> dict:
    try:
        if path.stat().st_size > SCAN_MAX:
            return {}
        d = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _label(v: Any, fallback: str) -> str:
    if isinstance(v, dict):
        v = v.get("en") or next((x for x in v.values() if isinstance(x, str)), "")
    return (v if isinstance(v, str) and v.strip() else fallback)[:120]


def _identity(kind: str, root: Path) -> tuple[str, str, str]:
    """(id, name, version) as the package itself states them: text from outside, only shown and checked."""
    if kind == "skill":
        from . import skills
        try:
            front = skills._front((root / "SKILL.md").read_text(encoding="utf-8", errors="replace")[:6000])
        except OSError:
            front = {}
        pid = front.get("name") or root.name
        return pid, pid[:120], str(front.get("version") or "")[:40]
    d = _json(root / ("manifest.json" if kind == "extension" else "theme.json"))
    pid = d.get("id") if isinstance(d.get("id"), str) else root.name
    return pid, _label(d.get("name"), pid), (str(d["version"])[:40] if isinstance(d.get("version"), (str, int, float)) else "")


def _scan(kind: str, root: Path, skipped: list[dict]) -> dict:
    from . import backup, importer
    fs = _Findings()
    files = _files(root)
    total = 0
    runs = False
    h = hashlib.sha256()
    for s in skipped:
        fs.add(WARN, "left-out", f"not read and not installed: {s.get('reason')}", str(s.get("file"))[:200])
    for rel in files:
        f = root / rel
        size = f.stat().st_size
        total += size
        ext = PurePosixPath(rel).suffix.lower()
        data = f.read_bytes() if size <= SCAN_MAX else None
        if data is None:
            dig = hashlib.sha256()
            with open(f, "rb") as fh:
                while chunk := fh.read(1 << 20):
                    dig.update(chunk)
            digest = dig.hexdigest()
        else:
            digest = _sha(data)
        h.update(rel.encode("utf-8", "surrogateescape") + b"\0" + digest.encode() + b"\n")
        if importer._claude_config(PurePosixPath(rel)):
            fs.add(DANGER, "claude-config", "Claude Code settings, hooks, sub-agent or MCP file: commands that run "
                   "in sessions", rel, 1, "")
        if data is None:
            if ext not in QUIET_EXT:
                fs.add(WARN, "unreadable", f"not read: over {SCAN_MAX // 1024} KB", rel)
            continue
        is_text = b"\0" not in data[:8192]
        if not is_text:
            if ext not in QUIET_EXT:
                fs.add(WARN, "unreadable", "binary file: not readable", rel)
            elif ext in TEXT_EXT:
                fs.add(WARN, "unreadable", "binary content under a text name", rel)
            continue
        text = data.decode("utf-8", errors="replace")
        role = _role(kind, rel, text)
        if ext not in TEXT_EXT and role == "text" and ext not in QUIET_EXT and PurePosixPath(rel).name not in ("LICENSE", "Makefile", "Dockerfile"):
            fs.add(INFO, "other-file", "file of an unusual type (read as text)", rel)
        if role == "server":
            runs = True
            fs.add(WARN, "server-code", "runs inside the Harness server, with its rights (root on a standard "
                   "install): it can read your files, keys and sessions", rel, 1, "")
        elif role == "script":
            runs = runs or kind != "theme"
            fs.add(INFO if kind == "theme" else WARN, "server-code",
                   {"skill": "script on the server: Claude runs it with the session's rights when the skill says so",
                    "theme": "script in a theme folder (a theme is data: the install does not copy it)"}.get(
                       kind, "script on the server, started by the extension or by hand"), rel, 1, "")
        for leak in backup.scan_bytes(data):
            fs.add(WARN, "secret-inside", f"holds something shaped like a secret ({leak})", rel)
        _scan_text(fs, kind, rel, text, role)
        if PurePosixPath(rel).name == "SKILL.md":
            before = len(fs.items)
            _front_matter(fs, rel, text)
            runs = runs or any(x["code"] == "skill-hooks" for x in fs.items[before:])
    if kind == "theme":
        _theme_checks(fs, root)
    if kind == "extension" and any(PurePosixPath(r).name == "SKILL.md" for r in files):
        fs.add(INFO, "ships-skill", "ships a skill: Claude follows it only once linked into .claude/skills",
               next(r for r in files if PurePosixPath(r).name == "SKILL.md"), 1, "")
    pid, name, version = _identity(kind, root)
    findings = fs.done()
    counts = {lv: sum(1 for x in findings if x["level"] == lv) for lv in (DANGER, WARN, INFO)}
    out: dict[str, Any] = {"kind": kind, "id": pid, "name": name, "files": len(files), "bytes": total,
                           "sha256": h.hexdigest(), "runs_on_server": runs, "findings": findings, "counts": counts}
    if version:
        out["version"] = version
    out["summary"] = _summary(out)
    return out


def _summary(r: dict) -> str:
    c = r["counts"]
    where = {"extension": "Runs code on the server." if r["runs_on_server"] else "No code that runs on the server was found.",
             "skill": "Has scripts or hooks that run on the server." if r["runs_on_server"] else "No script was found: instructions Claude follows.",
             "theme": "A theme is data: only theme.json and its images are installed."}[r["kind"]]
    found = (f"{c[DANGER]} to read first, {c[WARN]} to check, {c[INFO]} for information."
             if r["findings"] else "Nothing on the list was found.")
    return (f"{r['kind'].capitalize()} {r['name']}" + (f" {r['version']}" if r.get("version") else "")
            + f": {r['files']} file(s), {max(1, r['bytes'] // 1024)} KB. {where} {found} "
            "A reading aid, not a verdict: it only finds what is written plainly. Read the code before installing.")


def _report_at(root: Path, skipped: list[dict], kind: str | None) -> dict:
    if kind and kind not in KINDS:
        raise PackageError(f"unknown kind {kind} (extension, skill or theme)")
    kind = kind or detect_kind(root)
    if not (root / MARKER[kind]).is_file():
        raise PackageError(f"not a usable {kind}: {MARKER[kind]} is missing at its top (or is a link)")
    r = _scan(kind, root, skipped)
    prev = _records().get(f"{kind}:{r['id']}")
    if prev:
        r["installed"] = {k: prev.get(k) for k in ("sha256", "version", "source", "installed_at")}
        r["changed"] = prev.get("sha256") != r["sha256"]
    return r


def report(path: Path | str, kind: str | None = None) -> dict:
    """What the package at `path` (a folder or a zip) would do, read without running anything.

    {kind, id, name, version?, files, bytes, sha256, runs_on_server, findings: [{level: info|warn|danger, code,
    what, file, line, excerpt}], counts, summary, installed?: {sha256, version, source, installed_at}, changed?}.
    `installed` / `changed` are there when a package of that kind and id was installed by `install`.
    A reading aid, not a verdict: nothing here says a package is harmless.
    """
    with snapshot(Path(path)) as (root, skipped):
        return _report_at(root, skipped, kind)


# ---------------------------------------------------------------------------------------------- installed.json

def _records_path() -> Path:
    return config.STATE / "installed.json"


def _records() -> dict[str, dict]:
    d = config.read_json(_records_path(), {})
    p = d.get("packages") if isinstance(d, dict) else None
    return {k: v for k, v in p.items() if isinstance(v, dict)} if isinstance(p, dict) else {}


def _dest(kind: str, pid: str) -> Path:
    if kind == "extension":
        from . import extensions
        return extensions.root() / pid
    if kind == "theme":
        from . import themes
        return themes.root() / pid
    return config.workspace() / ".claude" / "skills" / pid


def installed() -> list[dict]:
    """The packages installed by `install`: the record + `state`: ok | modified (its files changed since) | removed."""
    out = []
    for rec in _records().values():
        kind, pid = str(rec.get("kind")), str(rec.get("id"))
        row = {k: rec.get(k) for k in ("kind", "id", "name", "version", "sha256", "source", "installed_at", "counts",
                                       "runs_on_server")}
        ok_id = kind in KINDS and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", pid)
        d = _dest(kind, pid) if ok_id else None
        if d is None or not d.is_dir():
            row["state"] = "removed"
        else:
            try:
                row["state"] = "ok" if tree_hash(d) == rec.get("installed_sha256") else "modified"
            except OSError:
                row["state"] = "modified"
        out.append(row)
    return sorted(out, key=lambda r: (str(r["kind"]), str(r["id"])))


def _record(r: dict, dest: Path, source: str) -> dict:
    rec = {"kind": r["kind"], "id": r["id"], "name": r["name"], "version": r.get("version", ""), "sha256": r["sha256"],
           "installed_sha256": tree_hash(dest), "source": source[:300], "installed_at": int(time.time()),
           "counts": r["counts"], "runs_on_server": r["runs_on_server"]}
    with config._lock:
        recs = _records()
        recs[f"{r['kind']}:{r['id']}"] = rec
        config.write_json(_records_path(), {"version": 1, "packages": recs}, mode=0o600)
    return rec


def _swap(src: Path, dest: Path, force: bool) -> None:
    """Puts the checked copy at `dest` (a replaced folder leaves only once the new one is in place)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(dir=dest.parent, prefix=f".{dest.name}."))
    try:
        new = stage / "new"
        shutil.copytree(src, new, symlinks=False)
        if dest.is_symlink():
            raise PackageError(f"{dest} is a link: remove it first")
        if dest.exists():
            if not force:
                raise PackageError(f"{dest.name} is already installed (--force replaces it)")
            dest.rename(stage / "old")
        try:
            new.rename(dest)
        except BaseException:
            if (stage / "old").exists() and not dest.exists():
                (stage / "old").rename(dest)
            raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def install(path: Path | str, sha256: str, *, read_it: bool = False, force: bool = False, source: str = "",
            kind: str | None = None) -> dict:
    """Installs the package only if its content is the one of the report `sha256` comes from.

    Takes a new private copy, reports on it, refuses (PackageChanged) when its hash differs, refuses
    (NeedsConfirmation) danger findings without `read_it`, then installs that same copy: an extension to
    <workspace>/extensions/<id>/, a skill to <workspace>/.claude/skills/<name>/, a theme through themes.install.
    -> the report, with `record` (the line of installed.json).
    """
    with snapshot(Path(path)) as (root, skipped):
        r = _report_at(root, skipped, kind)
        if not sha256 or r["sha256"] != sha256.strip().lower():
            raise PackageChanged(f"the content is not the one that was checked (now sha256 {r['sha256']}): nothing "
                                 "installed. Read the report again.")
        if r["counts"][DANGER] and not read_it:
            raise NeedsConfirmation(f"{r['counts'][DANGER]} finding(s) to read first: the owner has to confirm having "
                                    "read what it does")
        pid = r["id"]
        if r["kind"] == "theme":
            from . import themes
            try:
                t, _ = themes.install(root, force=force)
            except themes.ThemeError as e:
                raise PackageError(str(e)) from None
            r["id"] = pid = t["id"]
            dest = themes.root() / pid
        elif r["kind"] == "extension":
            from . import extensions
            if not isinstance(pid, str) or not extensions.ID_RE.match(pid) or pid in extensions.RESERVED_IDS:
                raise PackageError("its manifest has no usable id (lowercase letters, digits and dashes, not a "
                                   "built-in widget)")
            dest = extensions.root() / pid
            with extensions.publishing():
                _swap(root, dest, force)
        else:
            if not isinstance(pid, str) or not SKILL_ID.fullmatch(pid):
                raise PackageError("its SKILL.md has no usable name (lowercase letters, digits and dashes)")
            dest = _dest("skill", pid)
            _swap(root, dest, force)
        r["record"] = _record(r, dest, source)
        return r
