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
    "windows-amd64": "harness-link-windows-amd64.exe", "windows-arm64": "harness-link-windows-arm64.exe",
    "android": "harness-link.apk",
}
SAVE_AS = {"linux": "harness-link", "darwin": "harness-link", "windows": "harness-link.exe", "android": "harness-link.apk"}
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


# "LINK" in big letters, as the Harness Maxxing installer writes "MAXXING" (same blues, top to bottom); the app
# prints it too when it starts (link/console.go), except right after the install (HARNESS_LINK_NO_LOGO).
LOGO = ('██╗     ██╗███╗   ██╗██╗  ██╗',
        '██║     ██║████╗  ██║██║ ██╔╝',
        '██║     ██║██╔██╗ ██║█████╔╝ ',
        '██║     ██║██║╚██╗██║██╔═██╗ ',
        '███████╗██║██║ ╚████║██║  ██╗',
        '╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝')
_BLUES = (27, 33, 39, 45, 51, 87)
_PS_BLUES = ("Blue", "Blue", "Cyan", "Cyan", "Cyan", "Cyan")


def _sh_logo() -> str:
    lines = "".join(f"  printf '  \\033[38;5;{c}m%s%s\\n' '{l}' \"$R\"\n" for c, l in zip(_BLUES, LOGO))
    return ("if [ -n \"$R\" ] && [ \"$(tput cols 2>/dev/null || echo 80)\" -ge 34 ]; then\n"
            "  printf '\\n  %s\\033[38;5;75mH A R N E S S%s\\n' \"$B\" \"$R\"\n" + lines +
            "else printf '\\n  %sHARNESS LINK%s\\n' \"$B\" \"$R\"; fi\n"
            "printf '  %sInstall on this computer%s\\n\\n' \"$D\" \"$R\"\n")


def _ps_logo() -> str:
    lines = "".join(f"  Write-Host '  {l}' -ForegroundColor {c}\n" for c, l in zip(_PS_BLUES, LOGO))
    return ("Write-Host ''\n"
            "if ($Host.UI.RawUI.WindowSize.Width -ge 34) {\n"
            "  Write-Host '  H A R N E S S' -ForegroundColor Cyan\n" + lines +
            "} else { Write-Host '  HARNESS LINK' }\n"
            "Write-Host '  Install on this computer' -ForegroundColor DarkGray\n"
            "Write-Host ''\n")


_SH_STYLE = (
    "if [ -t 1 ] && [ -z \"${NO_COLOR:-}\" ] && [ \"${TERM:-}\" != dumb ]; then\n"
    "  A=$(printf '\\033[38;5;141m'); G=$(printf '\\033[38;5;114m'); Y=$(printf '\\033[38;5;221m')\n"
    "  E=$(printf '\\033[38;5;203m'); D=$(printf '\\033[2m'); B=$(printf '\\033[1m'); R=$(printf '\\033[0m')\n"
    "else A= G= Y= E= D= B= R=; fi\n"
    "step() { printf '  %s●%s %s\\n' \"$G\" \"$R\" \"$1\"; }\n"
    "fail() { printf '\\n  %s■ %s%s\\n\\n' \"$E\" \"$1\" \"$R\" >&2; exit 1; }\n"
)


def install_error_script(kind: str, code: str) -> str:
    """What the pasted command runs when its code cannot be used (expired, already used, unknown): the reason in
    plain words instead of a bare HTTP error."""
    msg = ("This command expired or was already used" if code == "expired" else "This command is not valid") + \
        ". Add the computer again in Harness Maxxing (Settings > Devices)."
    if kind == "ps1":
        return f"Write-Host ''; Write-Host '  ■ {msg}' -ForegroundColor Red; Write-Host ''\n"
    return "#!/bin/sh\n" + _SH_STYLE + f"fail '{msg}'\n"


def install_script(kind: str, code: str, server_url: str) -> str:
    """The script the pasted command (`commands()`) runs: stop and unregister an older copy (Harness Link started at
    login, or the first "Harness PC"), download the app (with its pairing trailer), put it on the PATH, then run it
    in the foreground of the same terminal (live log; it stops with the window). Nothing starts at login. Each step
    is printed as one styled line."""
    store.invite(code)
    c = store.normalize_code(code)
    base = f"{server_url}/api/devices/download"
    if kind == "ps1":
        return ("$ErrorActionPreference = 'Stop'\n"
                "$ProgressPreference = 'SilentlyContinue'\n"
                "function Step($t) { Write-Host '  ● ' -ForegroundColor Green -NoNewline; Write-Host $t }\n"
                "function Fail($t) { Write-Host ''; Write-Host ('  ■ ' + $t) -ForegroundColor Red; Write-Host ''; "
                "return }\n"
                + _ps_logo() +
                "$arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }\n"
                "Step (\"Windows · $arch\")\n"
                "$dir = Join-Path $env:LOCALAPPDATA 'HarnessLink'\n"
                "New-Item -ItemType Directory -Force -Path $dir | Out-Null\n"
                "$exe = Join-Path $dir 'harness-link.exe'\n"
                "# older versions started at login (Harness Link, then the first Harness PC): stop them, remove the "
                "entry\n"
                "$old = Get-Process -Name harness-link, HarnessLink, HarnessPC -ErrorAction SilentlyContinue\n"
                "if ($old) { $old | Stop-Process -Force; Start-Sleep -Milliseconds 500; Step 'Older version stopped' }\n"
                "foreach ($n in 'HarnessLink', 'HarnessPC') { Remove-ItemProperty -Path "
                "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' -Name $n -ErrorAction SilentlyContinue }\n"
                "try {\n"
                f"  Invoke-WebRequest -UseBasicParsing -Uri \"{base}/windows-${{arch}}?code={c}\" -OutFile \"$exe.tmp\"\n"
                "  Move-Item -Force \"$exe.tmp\" $exe\n"
                "} catch {\n"
                "  Remove-Item -Force \"$exe.tmp\" -ErrorAction SilentlyContinue\n"
                "  $s = $_.Exception.Response.StatusCode.value__\n"
                "  if ($s -eq 410 -or $s -eq 400) { Fail 'This command expired or was already used. Add the computer "
                "again in Harness Maxxing (Settings > Devices).'; return }\n"
                "  if (Get-Process -Name harness-link -ErrorAction SilentlyContinue) { Fail 'Harness Link is running "
                "in another window: close it, then paste the command again.'; return }\n"
                "  Fail ('Download failed: ' + $_.Exception.Message); return\n"
                "}\n"
                "$mb = '{0:N1} MB' -f ((Get-Item $exe).Length / 1MB)\n"
                "Step \"Downloaded ($mb)\"\n"
                "Step \"Installed in $exe\"\n"
                "$p = [Environment]::GetEnvironmentVariable('Path', 'User'); if (-not $p) { $p = '' }\n"
                "if (-not (($p -split ';') -contains $dir)) {\n"
                "  [Environment]::SetEnvironmentVariable('Path', ($p.TrimEnd(';') + ';' + $dir).TrimStart(';'), 'User')\n"
                "  $env:Path = $env:Path.TrimEnd(';') + ';' + $dir\n"
                "  Step 'Added to the PATH'\n"
                "}\n"
                "Write-Host ''\n"
                "Write-Host '  Done. ' -ForegroundColor Green -NoNewline; Write-Host 'Harness Link is installed.'\n"
                "Write-Host ''\n"
                "Write-Host '  How to use it'\n"
                "function Cmd($c, $d) { Write-Host ('    ' + $c.PadRight(24)) -ForegroundColor Magenta -NoNewline; "
                "Write-Host (' ' + $d) }\n"
                "Cmd 'harness-link' 'start it: Claude can use this computer while the window stays open'\n"
                "Cmd 'Ctrl+C' 'stop it (closing the window does the same)'\n"
                "Cmd 'harness-link status' 'what is paired and what this computer allows'\n"
                "Cmd 'harness-link uninstall' 'remove Harness Link from this computer'\n"
                "Write-Host ''\n"
                "Write-Host '  Starting Harness Link...' -ForegroundColor DarkGray\n"
                "$env:HARNESS_LINK_NO_LOGO = '1'\n"
                "try { & $exe } finally { Remove-Item Env:HARNESS_LINK_NO_LOGO -ErrorAction SilentlyContinue }\n")
    return ("#!/bin/sh\nset -e\n" + _SH_STYLE +
            _sh_logo() +
            'case "$(uname -s)" in Linux) os=linux; osn=Linux ;; Darwin) os=darwin; osn=macOS ;; '
            '*) fail "This system is not supported: $(uname -s)" ;; esac\n'
            'case "$(uname -m)" in x86_64|amd64) arch=amd64 ;; arm64|aarch64) arch=arm64 ;; '
            '*) fail "This processor is not supported: $(uname -m)" ;; esac\n'
            'if [ "$os" = darwin ]; then [ "$arch" = arm64 ] && cpu="Apple silicon" || cpu=Intel; '
            'else cpu=$(uname -m); fi\n'
            'step "$osn · $cpu"\n'
            'dir="$HOME/.local/bin"; mkdir -p "$dir"; f="$dir/harness-link"\n'
            '# older versions started at login (Harness Link, then the first "Harness PC"): stop them, remove the entry\n'
            'old=; pkill -x harness-link 2>/dev/null && old=1; pkill -x harness-pc 2>/dev/null && old=1\n'
            '[ -n "$old" ] && { sleep 0.5; step "Older version stopped"; }\n'
            'if [ "$os" = darwin ]; then\n'
            '  launchctl remove com.harnessmaxxing.link 2>/dev/null || true\n'
            '  launchctl remove com.harnessmaxxing.pc 2>/dev/null || true\n'
            'fi\n'
            'rm -f "$HOME/Library/LaunchAgents/com.harnessmaxxing.link.plist" '
            '"$HOME/Library/LaunchAgents/com.harnessmaxxing.pc.plist" '
            '"${XDG_CONFIG_HOME:-$HOME/.config}/autostart/harness-link.desktop" '
            '"${XDG_CONFIG_HOME:-$HOME/.config}/autostart/harness-pc.desktop"\n'
            f'st=$(curl -sSL -w "%{{http_code}}" "{base}/$os-$arch?code={c}" -o "$f.tmp") || '
            'fail "Cannot reach Harness Maxxing: check the connection and paste the command again."\n'
            'if [ "$st" != 200 ]; then rm -f "$f.tmp"\n'
            '  case "$st" in 400|410) fail "This command expired or was already used. Add the computer again in '
            'Harness Maxxing (Settings > Devices)." ;; esac\n'
            '  fail "Download failed (HTTP $st)."\n'
            'fi\n'
            'chmod 755 "$f.tmp" && mv -f "$f.tmp" "$f"\n'
            '[ "$os" = darwin ] && xattr -d com.apple.quarantine "$f" 2>/dev/null || true\n'
            'mb=$(awk "BEGIN { printf \\"%.1f\\", $(wc -c < "$f") / 1048576 }")\n'
            'step "Downloaded ($mb MB)"\n'
            'step "Installed in $f"\n'
            'where="a terminal"\n'
            'case ":$PATH:" in *":$dir:"*) ;; *)\n'
            '  case "${SHELL##*/}" in zsh) rc="$HOME/.zshrc" ;; '
            'bash) if [ "$os" = darwin ]; then rc="$HOME/.bash_profile"; else rc="$HOME/.bashrc"; fi ;; '
            '*) rc="$HOME/.profile" ;; esac\n'
            '  if ! grep -qs "Harness Link" "$rc"; then\n'
            '    printf \'\\n# Harness Link\\nexport PATH="$HOME/.local/bin:$PATH"\\n\' >> "$rc"\n'
            '  fi\n'
            '  step "Added to the PATH (${rc#"$HOME"/})"\n'
            '  where="a new terminal window" ;;\n'
            'esac\n'
            'printf \'\\n  %sDone.%s Harness Link is installed.\\n\\n\' "$G" "$R"\n'
            'printf \'  %sHow to use it%s\\n\' "$B" "$R"\n'
            'cmd() { printf \'    %s%-24s%s %s\\n\' "$A" "$1" "$R" "$2"; }\n'
            'cmd "harness-link" "start it: Claude can use this computer while the window stays open"\n'
            'cmd "Ctrl+C" "stop it (closing the window does the same)"\n'
            'cmd "harness-link status" "what is paired and what this computer allows"\n'
            'cmd "harness-link uninstall" "remove Harness Link from this computer"\n'
            'if [ "$where" != "a terminal" ]; then printf \'\\n  %sThis time it starts by itself; next time, type harness-link in a new '
            'terminal window.%s\\n\' "$D" "$R"; fi\n'
            'if [ "$os" = darwin ]; then printf \'  %sThe first time, macOS asks to allow your terminal app in Screen Recording '
            'and Accessibility: allow both, quit the terminal (cmd+Q), open it again and type harness-link.%s\\n\' '
            '"$D" "$R"; fi\n'
            'printf \'\\n  %sStarting Harness Link...%s\\n\' "$D" "$R"\n'
            'export HARNESS_LINK_NO_LOGO=1\n'
            'if (exec </dev/tty) 2>/dev/null; then exec "$f" </dev/tty; else exec "$f"; fi\n')


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
