"""Harness Link downloads: the app for each system, its install scripts and the phone's pairing page.

The binaries come from `MAXXING_LINK_BIN_DIR` (a local build: tests, trials), else the GitHub release named in
`maxxing/link.json` ({version, url, files: {name: sha256}}), downloaded once into `<state>/devices/bin/` and always
checked against its SHA-256. A desktop binary is sent with a trailer - `<json {server, code}><uint32 BE len>HMLINK01` -
so downloading it is pairing it; the APK is sent as it is (the phone pairs by its link or by hand).
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import struct
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

from . import DevicesError, home, store

TRAILER_MAGIC = b"HMLINK01"
TARGETS = {                                           # download target -> file name in the release
    "linux-amd64": "harness-link-linux-amd64", "linux-arm64": "harness-link-linux-arm64",
    "darwin-amd64": "harness-link-darwin-amd64", "darwin-arm64": "harness-link-darwin-arm64",
    "windows-amd64": "HarnessLink-windows-amd64.exe", "windows-arm64": "HarnessLink-windows-arm64.exe",
    "android": "harness-link.apk",
}
SAVE_AS = {"linux": "harness-link", "darwin": "harness-link", "windows": "HarnessLink.exe", "android": "harness-link.apk"}
_download_lock = threading.Lock()


def manifest() -> dict:
    try:
        d = json.loads(Path(__file__).resolve().parent.parent.joinpath("link.json").read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def latest_version() -> str:
    return str(manifest().get("version") or "")


def available() -> list[str]:
    """The targets this server can hand out now."""
    local = os.environ.get("MAXXING_LINK_BIN_DIR")
    if local:
        return [t for t, n in TARGETS.items() if (Path(local) / n).is_file()]
    files = manifest().get("files") or {}
    return [t for t, n in TARGETS.items() if n in files]


def _replace_bytes(path: Path, data: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def app_file(target: str) -> Path:
    """The generic app for `target` (blocking: may download it; call it in a thread)."""
    name = TARGETS.get(target)
    if not name:
        raise DevicesError(404, "not_found", "unknown target")
    local = os.environ.get("MAXXING_LINK_BIN_DIR")
    if local:
        f = Path(local) / name
        if f.is_file():
            return f
        raise DevicesError(404, "not_found", f"{name} is not built")
    man = manifest()
    want = (man.get("files") or {}).get(name)
    if not want:
        raise DevicesError(404, "not_available", "Harness Link is not available for this system yet")
    cache = home() / "bin" / f"{man.get('version')}-{name}"
    with _download_lock:                               # two downloads at once: the second one finds the cache
        if cache.is_file():
            with cache.open("rb") as f:
                if hashlib.file_digest(f, "sha256").hexdigest() == want:
                    return cache
        import httpx
        url = str(man.get("url") or "").format(version=man.get("version"), name=name)
        r = httpx.get(url, follow_redirects=True, timeout=120)
        r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest() != want:
            raise DevicesError(502, "checksum", "The downloaded app does not match its checksum")
        cache.parent.mkdir(parents=True, exist_ok=True)
        _replace_bytes(cache, r.content)
        return cache


def trailer(server_url: str, code: str) -> bytes:
    body = json.dumps({"server": server_url, "code": store.normalize_code(code)}).encode()
    return body + struct.pack(">I", len(body)) + TRAILER_MAGIC


def personalised(target: str, code: str, server_url: str) -> tuple[str, Path, bytes]:
    """(file name to save as, the generic app, the trailer to send after it - b"" for the APK). The code must be
    valid (an invitation not used yet)."""
    store.invite(code)
    f = app_file(target)
    os_name = target.split("-", 1)[0]
    return SAVE_AS[os_name], f, (b"" if target == "android" else trailer(server_url, code))


def install_script(kind: str, code: str, server_url: str) -> str:
    """The script the pasted command (`commands()`) runs: download the app (with its pairing trailer), start it."""
    store.invite(code)
    c = store.normalize_code(code)
    base = f"{server_url}/api/devices/download"
    if kind == "ps1":
        return ("$ErrorActionPreference = 'Stop'\n"
                "$arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }\n"
                "$dir = Join-Path $env:LOCALAPPDATA 'HarnessLink'\n"
                "New-Item -ItemType Directory -Force -Path $dir | Out-Null\n"
                "$exe = Join-Path $dir 'HarnessLink.exe'\n"
                "Get-Process -Name HarnessLink -ErrorAction SilentlyContinue | Stop-Process -Force\n"
                "Start-Sleep -Milliseconds 500\n"
                f"Invoke-WebRequest -UseBasicParsing -Uri \"{base}/windows-$arch?code={c}\" -OutFile $exe\n"
                "Start-Process -FilePath $exe\n"
                "Write-Host 'Harness Link started. Accept this computer in Harness Maxxing (Settings -> Devices).'\n")
    return ("#!/bin/sh\nset -e\n"
            'case "$(uname -s)" in Linux) os=linux ;; Darwin) os=darwin ;; '
            '*) echo "Harness Link: this system is not supported" >&2; exit 1 ;; esac\n'
            'case "$(uname -m)" in x86_64|amd64) arch=amd64 ;; arm64|aarch64) arch=arm64 ;; '
            '*) echo "Harness Link: this processor is not supported" >&2; exit 1 ;; esac\n'
            'dir="$HOME/.local/bin"; mkdir -p "$dir"; f="$dir/harness-link"\n'
            f'curl -fsSL "{base}/$os-$arch?code={c}" -o "$f.tmp"\n'
            'chmod 755 "$f.tmp" && mv -f "$f.tmp" "$f"\n'
            '[ "$os" = darwin ] && xattr -d com.apple.quarantine "$f" 2>/dev/null || true\n'
            'nohup "$f" >/dev/null 2>&1 &\n'
            "echo 'Harness Link started. Accept this computer in Harness Maxxing (Settings -> Devices).'\n")


def commands(server_url: str, code: str) -> dict:
    c = store.normalize_code(code)
    return {"sh": f"curl -fsSL {server_url}/api/devices/install/{c}.sh | sh",
            "ps1": f"irm {server_url}/api/devices/install/{c}.ps1 | iex"}


def deeplink(server_url: str, code: str) -> str:
    return f"harnesslink://pair?s={quote(server_url, safe='')}&c={store.normalize_code(code)}"


TEXTS = {
    "en": {"title": "Connect this phone to Harness", "apk": "1. Download the app (APK)",
           "apk_help": "Allow your browser to install apps when Android asks, then open the file.",
           "open": "2. Open in Harness Link", "manual": "Or type these in the app:", "server": "Server",
           "code": "Code", "secret": "This code is for you only: do not share it. It works once, for 15 minutes.",
           "expired": "This link expired or was already used. Add the device again in Harness Maxxing.",
           "no_apk": "The app is not available on this server yet."},
    "fr": {"title": "Connecter ce téléphone à Harness", "apk": "1. Télécharger l’application (APK)",
           "apk_help": "Autorisez votre navigateur à installer des applications quand Android le demande, puis "
                       "ouvrez le fichier.",
           "open": "2. Ouvrir dans Harness Link", "manual": "Ou saisissez-les dans l’application :",
           "server": "Serveur", "code": "Code",
           "secret": "Ce code est pour vous seul : ne le partagez pas. Il sert une fois, pendant 15 minutes.",
           "expired": "Ce lien a expiré ou a déjà servi. Ajoutez l’appareil de nouveau dans Harness Maxxing.",
           "no_apk": "L’application n’est pas encore disponible sur ce serveur."},
}


def link_page(code: str, server_url: str, lang: str = "en") -> tuple[int, str]:
    """The page the phone opens from the QR code: download the APK, open the app with the pairing link, or type."""
    w = TEXTS.get(lang, TEXTS["en"])
    e = html.escape
    try:
        store.invite(code)
        ok = True
    except DevicesError:
        ok = False
    head = ('<!doctype html><html lang="' + e(lang) + '"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
            f'<title>{e(w["title"])}</title><style>'
            'body{font-family:system-ui,sans-serif;margin:0;padding:24px;background:#111;color:#eee;line-height:1.45}'
            'main{max-width:420px;margin:0 auto}h1{font-size:1.3rem}a.b{display:block;text-align:center;padding:14px;'
            'margin:12px 0;border-radius:10px;background:#3b82f6;color:#fff;text-decoration:none;font-weight:600}'
            'a.s{background:#333}p.h{font-size:.85rem;color:#aaa}code{font-size:1.05rem;word-break:break-all;'
            'background:#222;padding:2px 6px;border-radius:4px}dl{margin:8px 0}dt{color:#aaa;font-size:.85rem}'
            'dd{margin:0 0 10px}</style></head><body><main>'
            f'<h1>{e(w["title"])}</h1>')
    if not ok:
        return 410, head + f'<p>{e(w["expired"])}</p></main></body></html>'
    c = store.normalize_code(code)
    apk = "android" in available()
    body = (f'<a class="b s" href="{e(server_url)}/api/devices/download/android?code={e(c)}">{e(w["apk"])}</a>'
            f'<p class="h">{e(w["apk_help"])}</p>' if apk else f'<p class="h">{e(w["no_apk"])}</p>')
    body += (f'<a class="b" href="{e(deeplink(server_url, c))}">{e(w["open"])}</a>'
             f'<p>{e(w["manual"])}</p><dl><dt>{e(w["server"])}</dt><dd><code>{e(server_url)}</code></dd>'
             f'<dt>{e(w["code"])}</dt><dd><code>{e(c)}</code></dd></dl><p class="h">{e(w["secret"])}</p>')
    return 200, head + body + "</main></body></html>"
