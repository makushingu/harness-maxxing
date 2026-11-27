"""What the Harness Browser may open and do: addresses (pages and hosts), DevTools commands, Chromium policies.

Three layers, each one enough on its own for what it covers:
- the proxy (proxy.py) refuses every host that is not on the public internet - the server itself, its local network,
  cloud metadata, raw IPs, DNS-rebinding helpers - after resolving it, and connects to the IP it checked;
- the Chromium policy (`policy()`) blocks file:, chrome:, devtools: pages and downloads;
- the DevTools relay (relay.py) refuses commands that reach past the page (`check_command`, rules.json) and, for a
  sandboxed agent, pages outside its domains (`page_refusal`; pool.Pool._keep_to empties a tab that got there anyway).
"""
from __future__ import annotations

import contextlib
import ipaddress
import json
import re
import socket
import unicodedata
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

# names that only mean something on a local network (a router, a NAS, a service of this server)
LOCAL_SUFFIXES = (".localhost", ".local", ".lan", ".home", ".internal", ".intranet", ".home.arpa", ".corp")
# public names that resolve to the IP written in them, or to 127.0.0.1 (DNS rebinding helpers)
LOOPBACK_DNS = ("nip.io", "sslip.io", "xip.io", "localtest.me", "lvh.me", "vcap.me", "traefik.me", "local.gd",
                "localhost.direct", "lacolhost.com")
SITE_RE = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9-]{0,62}\.)+[a-z0-9-]{2,63}\Z")
# a site covers a domain and its subdomains, never a whole extension ("com", "co.uk")
TOO_WIDE = {"co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp", "com.br",
            "com.cn", "com.tr", "co.in", "co.za", "github.io", "pages.dev", "workers.dev", "vercel.app",
            "netlify.app", "herokuapp.com", "web.app", "firebaseapp.com"}
BLOCKED_PAGES = ["file://*", "chrome://*", "chrome-untrusted://*", "chrome-extension://*", "devtools://*",
                 "view-source:*", "javascript:*", "filesystem:*"]


@lru_cache(maxsize=1)
def _rules() -> dict:
    return json.loads(Path(__file__).with_name("rules.json").read_text())


# ---- sites of an owner ---------------------------------------------------------------------------------------------
def clean_site(raw: object) -> str | None:
    """"Example.com", "https://www.example.com/x", "*.example.com" -> "example.com" / "www.example.com"; None when it
    is not a public site name (an IP, localhost, a bare word, a whole extension)."""
    s = str(raw or "").strip().lower()
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s).split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    s = s.rsplit("@", 1)[-1].split(":", 1)[0].rstrip(".")
    if s.startswith("*."):
        s = s[2:]
    try:
        s = s.encode("idna").decode("ascii") if not s.isascii() else s
    except UnicodeError:
        return None
    if not SITE_RE.match(s) or len(s) > 253 or s in TOO_WIDE or local_host(s):
        return None
    return s


def site_allowed(host: str, sites: list[str]) -> bool:
    h = (host or "").lower().rstrip(".")
    return any(h == s or h.endswith("." + s) for s in sites)


# ---- hosts -------------------------------------------------------------------------------------------------------
def local_host(host: str) -> bool:
    """A host of this server or of a local network, as a browser would read it (127.1, 2130706433, 0x7f.1...)."""
    h = unicodedata.normalize("NFKC", host or "").replace("。", ".")
    h = h.strip().strip("[]").rstrip(".").lower()
    if not h:
        return True
    if not h.isascii() and ":" not in h:
        try:
            h = h.encode("idna").decode("ascii")
        except UnicodeError:
            return True
    if "%" in h or not h.isascii():
        return True
    if h == "localhost" or h.endswith(LOCAL_SUFFIXES) or ("." not in h and not h.isdigit() and ":" not in h):
        return True
    if any(h == d or h.endswith("." + d) for d in LOOPBACK_DNS):
        return True
    ip = parse_ip(h)
    return ip is not None and not ip_public(ip)


def parse_ip(h: str) -> ipaddress._BaseAddress | None:
    with contextlib.suppress(ValueError):
        return ipaddress.ip_address(h)
    if re.fullmatch(r"[0-9a-fx.]+", h) and any(c.isdigit() for c in h):
        try:
            return ipaddress.ip_address(socket.inet_aton(h))   # short / decimal / hex IPv4 forms
        except OSError:
            return None
    return None


NAT64 = ipaddress.ip_network("64:ff9b::/96")     # a translator sends these to the IPv4 address of the last 32 bits


def ip_public(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip.sixtofour:
            ip = ip.sixtofour
        elif ip.teredo:
            return False
        elif ip in NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global and not ip.is_multicast


# ---- pages (what Claude asks to open) ------------------------------------------------------------------------------
NOT_A_PAGE = "Only http(s) pages can be opened in the browser (no file:, chrome:, view-source:... addresses)."
LOCAL_PAGE = ("Addresses of this server or of a local network (localhost, 127.0.0.1, 192.168.x.x, router...) cannot be "
              "opened in the browser: only sites on the internet.")


# the address bar's search engine (browser settings `search`); Google spots a browser driven over DevTools now and
# then and asks its own check: DuckDuckGo and Bing do not
SEARCH_ENGINES = {"google": "https://www.google.com/search?q=", "duckduckgo": "https://duckduckgo.com/?q=",
                  "bing": "https://www.bing.com/search?q="}
SEARCH = SEARCH_ENGINES["google"]
HOST_LIKE = re.compile(r"^[^\s/?#]+\.[^\s/?#]{2,}([/?#]\S*)?$|^localhost(:\d+)?([/?#]\S*)?$", re.I)


def address(text: object, engine: str = "google") -> str:
    """What the address bar opens for what was typed: an address as is (https:// added), anything else a search."""
    t = str(text or "").strip()
    if not t:
        return ""
    if re.match(r"^[a-z][a-z0-9+.-]*:", t, re.I) and ("://" in t or t.lower().startswith(("about:", "data:"))):
        return t
    if HOST_LIKE.match(t):
        return "https://" + t
    from urllib.parse import quote_plus
    return SEARCH_ENGINES.get(engine, SEARCH) + quote_plus(t)


def page_refusal(url: object, sites: list[str] | None = None) -> str | None:
    """Why `url` cannot be opened (None = it can). sites: a sandboxed agent's domains, None = any public site."""
    if url is None:
        return None
    raw = re.sub(r"[\t\n\r]", "", str(url)).strip().replace("\\", "/")
    low = raw.lower()
    if low in _rules()["about_pages"]:
        return None
    try:
        u = urlsplit(raw)
    except ValueError:
        return NOT_A_PAGE
    scheme = u.scheme.lower()
    if scheme not in _rules()["page_schemes"]:
        return NOT_A_PAGE
    if scheme == "data":
        return None
    try:
        host = u.hostname or ""
    except ValueError:
        host = ""
    # `http:host/`, `http:/host/`, `http:///host/`: a browser finds a host where urlsplit sees none
    if not re.match(r"^[a-z]+://[^/]", raw, re.I) or not host or local_host(host):
        return LOCAL_PAGE
    if parse_ip(host.strip("[]")) is not None:
        return "Open sites by their name, not by an IP address."
    if sites is not None and not site_allowed(host, sites):
        return (f"{host} is not one of this agent's domains ({', '.join(sites) or 'none yet'}): in its sandbox, its "
                "browser opens only those. The owner got a notification to add it for the next runs: go on another "
                "way, or end the run and say what you needed it for.")
    return None


def off_domains(url: object, sites: list[str]) -> str | None:
    """The host of `url` when its only refusal is that it is not one of `sites` (a domain the owner could add)."""
    if page_refusal(url, None) is not None:
        return None
    try:
        host = (urlsplit(str(url).strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    return host if host and not site_allowed(host, sites) else None


# ---- DevTools commands ---------------------------------------------------------------------------------------------
def check_command(raw: str | bytes) -> tuple[str | None, dict | None]:
    """(why refused or None, the parsed command). Refused: too large, not a command, a blocked method or domain, a
    url that is not a page, files given to a page."""
    r = _rules()
    if len(raw) > r["max_command"]:
        return "command too large", None
    try:
        c = json.loads(raw)
    except (ValueError, RecursionError):
        return "not a DevTools command", None
    if not isinstance(c, dict) or not isinstance(c.get("method"), str) or not c["method"]:
        return "not a DevTools command", c if isinstance(c, dict) else None
    method = c["method"]
    if method in UPLOAD_METHODS and _uploads_only(c):
        return None, c
    if method in r["blocked_methods"] or method.split(".", 1)[0] in r["blocked_domains"]:
        return f"{method} is not allowed in the Harness Browser", c
    p = c.get("params") if isinstance(c.get("params"), dict) else {}
    url = p.get("url")
    if isinstance(url, str) and url and _bad_scheme(url):
        return "only http(s) pages can be opened", c
    data = p.get("data") if isinstance(p.get("data"), dict) else {}
    if data.get("files"):
        return "files cannot be given to pages", c
    return None, c


# Files a page may get: only ones copied into a profile's uploads folder (pool.upload, the live view's file chooser).
# Chromium sees that folder as /mxrun/uploads (its unit); a browser started without a unit (tests) adds its own.
UPLOAD_ROOTS: list[str] = ["/mxrun/uploads/"]
UPLOAD_METHODS = {"DOM.setFileInputFiles", "Page.setInterceptFileChooserDialog"}


def _uploads_only(c: dict) -> bool:
    if c["method"] == "Page.setInterceptFileChooserDialog":
        return True                                  # no native dialog: the files still come through the check below
    files = (c.get("params") or {}).get("files") if isinstance(c.get("params"), dict) else None
    if not isinstance(files, list) or not files or len(files) > 20:
        return False
    return all(isinstance(f, str) and "/../" not in f and not f.endswith("/..") and "\0" not in f
               and any(f.startswith(root) for root in UPLOAD_ROOTS) for f in files)


def _bad_scheme(url: str) -> bool:
    low = url.strip().lower()
    if low in _rules()["about_pages"]:
        return False
    try:
        return urlsplit(low).scheme not in _rules()["page_schemes"]
    except ValueError:
        return True


def refusal(cmd: dict | None, reason: str) -> str | None:
    """The DevTools error answer for a refused command (None when it had no id)."""
    if not cmd or "id" not in cmd:
        return None
    out = {"id": cmd["id"], "error": {"code": -32000, "message": reason}}
    if cmd.get("sessionId"):
        out["sessionId"] = cmd["sessionId"]
    return json.dumps(out)


# ---- Chromium policy ---------------------------------------------------------------------------------------------
def policy(downloads: bool = False) -> dict:
    """The managed policy of one browser (any public site: the proxy refuses local hosts)."""
    p: dict = {
        "URLBlocklist": list(BLOCKED_PAGES),
        "DownloadRestrictions": 0 if downloads else 3,
        "PasswordManagerEnabled": False, "AutofillAddressEnabled": False, "AutofillCreditCardEnabled": False,
        "BackgroundModeEnabled": False, "MetricsReportingEnabled": False, "TranslateEnabled": False,
        "SearchSuggestEnabled": False, "PromptForDownloadLocation": False, "SafeBrowsingProtectionLevel": 0,
        "DefaultNotificationsSetting": 2, "DefaultGeolocationSetting": 2, "DefaultSensorsSetting": 2,
        "DefaultSerialGuardSetting": 2, "DefaultWebBluetoothGuardSetting": 2, "DefaultWebUsbGuardSetting": 2,
        "DefaultWebHidGuardSetting": 2, "DefaultFileSystemReadGuardSetting": 2, "DefaultFileSystemWriteGuardSetting": 2,
        "AudioCaptureAllowed": False, "VideoCaptureAllowed": False, "ScreenCaptureAllowed": False,
        "PrintingEnabled": False, "ExtensionInstallBlocklist": ["*"],
        "BrowserSignin": 0, "SyncDisabled": True, "WebRtcIPHandling": "disable_non_proxied_udp",
    }
    if downloads:
        p["DownloadDirectory"] = "/mxdownloads"
    return p
