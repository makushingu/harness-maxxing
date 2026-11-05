"""What an agent may do with the mailboxes of the E-mail page: its `mail` setting (agent.json), checked by
`maxxing mail` in every agent turn (the turn's identity comes from its systemd unit, agent_guard.agent_turn, never
from its environment). Nothing by default: an agent sees no mailbox until the owner gives it one.

    "mail": [{"account": "contact-example", "rights": ["read", "draft", "move", "mark", "send"],
              "senders": ["*@stripe.com", "client@example.com"], "approve_send": "always",
              "trigger": {"enabled": true, "folder": "INBOX", "subject": "", "senders": [], "prompt": ""}}]

rights: read (list, read, save attachments), draft (write drafts), move (file, archive, trash, new folder), mark
(read / unread, star), send. senders: the agent only sees mail from these addresses or domains - and only when the
mail provider checked the sender (`verified`) - and only writes to them. approve_send: always (every message waits
for the owner's click), new (a message to someone the mailbox never exchanged with waits), never. trigger: every
new mail matching it starts the agent (poll.py), one turn per check of the mailbox.

Stdlib only: agents.clean() calls clean_grants() on every agent.json read.
"""
from __future__ import annotations

import fnmatch
import re
from email.message import Message
from typing import Any, Callable

RIGHTS = ("read", "draft", "move", "mark", "send")
APPROVE = ("always", "new", "never")
MAX_GRANTS = 10
MAX_SENDERS = 50
ACC_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")          # = mail.ID_RE
SENDER_RE = re.compile(r"^[a-z0-9*?._%+'-]*@[a-z0-9*?.-]+$")
DEFAULT_RIGHTS = ["read", "draft"]


class AccessError(ValueError):
    pass


def _clean_senders(v: Any, strict: bool) -> list[str]:
    out: list[str] = []
    for s in v if isinstance(v, list) else []:
        s = str(s).strip().lower()
        if s and "@" not in s:
            s = "*@" + s                                  # "stripe.com": the whole domain
        if s.startswith("@"):
            s = "*" + s
        if not s or not SENDER_RE.match(s) or len(s) > 254 or s.endswith("@*"):
            if strict:
                raise AccessError(f"Not an address or a domain: {s!r} (examples: client@example.com, *@stripe.com)")
            continue
        if s not in out:
            out.append(s)
    return out[:MAX_SENDERS]


def _clean_trigger(t: Any, strict: bool) -> dict | None:
    if not isinstance(t, dict):
        return None
    folder = " ".join(str(t.get("folder") or "INBOX").split())[:200] or "INBOX"
    if any(c in folder for c in "\r\n\0"):
        folder = "INBOX"
    return {"enabled": t.get("enabled") is not False, "folder": folder,
            "subject": " ".join(str(t.get("subject") or "").split())[:200],
            "senders": _clean_senders(t.get("senders"), strict),
            "prompt": str(t.get("prompt") or "").strip()[:4000]}


def clean_grants(v: Any, strict: bool = False) -> list[dict]:
    """agent.json `mail` with every field valid (one entry per mailbox)."""
    out: list[dict] = []
    for g in v if isinstance(v, list) else []:
        if not isinstance(g, dict):
            continue
        acc = str(g.get("account") or "").strip().lower()
        if not ACC_RE.match(acc):
            if strict:
                raise AccessError(f"Not a mailbox id: {acc!r}")
            continue
        if any(x["account"] == acc for x in out):
            if strict:
                raise AccessError(f"The mailbox {acc} is listed twice")
            continue
        rights = g.get("rights") if isinstance(g.get("rights"), list) else DEFAULT_RIGHTS
        bad = [r for r in rights if r not in RIGHTS]
        if bad and strict:
            raise AccessError(f"Unknown right {bad[0]!r} (rights: {', '.join(RIGHTS)})")
        approve = g.get("approve_send") if g.get("approve_send") in APPROVE else "always"
        if strict and g.get("approve_send") not in (None, "", *APPROVE):
            raise AccessError(f"approve_send: one of {', '.join(APPROVE)}")
        out.append({"account": acc, "rights": [r for r in RIGHTS if r in rights],
                    "senders": _clean_senders(g.get("senders"), strict), "approve_send": approve,
                    "trigger": _clean_trigger(g.get("trigger"), strict)})
    if strict and isinstance(v, list) and len(v) > MAX_GRANTS:
        raise AccessError(f"At most {MAX_GRANTS} mailboxes per agent")
    return out[:MAX_GRANTS]


# ---------------------------------------------------------------- addresses

def matches(address: str, patterns: list[str]) -> bool:
    a = (address or "").strip().lower()
    return bool(a) and "@" in a and any(fnmatch.fnmatchcase(a, p) for p in patterns)


def sender_ok(grant: dict, sender: str, verified: bool) -> bool:
    """May the agent of `grant` see a mail from `sender`? Any mail when it has no sender list; else only a mail whose
    sender the provider checked and that is on the list."""
    if not grant.get("senders"):
        return True
    return verified and matches(sender, grant["senders"])


def recipients_ok(grant: dict, rcpts: list[str]) -> list[str]:
    """The recipients the agent may not write to (empty: all fine)."""
    if not grant.get("senders"):
        return []
    return [r for r in rcpts if not matches(r, grant["senders"])]


def imap_from(patterns: list[str]) -> list[str]:
    """IMAP SEARCH criteria narrowing a folder to the senders (server-side substring; checked again after)."""
    terms = []
    for p in patterns:
        local, _, domain = p.partition("@")
        if "*" in domain or "?" in domain:
            frag = domain.split("*")[-1].split("?")[-1].lstrip(".")
            terms.append("@" + frag if frag else "")
        elif "*" in local or "?" in local:
            terms.append("@" + domain)
        else:
            terms.append(p)
    terms = [t for t in dict.fromkeys(terms) if t and t != "@"]
    if not terms or len(terms) > 20:
        return []
    q = lambda s: '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'  # noqa: E731
    crit = f"FROM {q(terms[0])}"
    for t in terms[1:]:
        crit = f"OR FROM {q(t)} ({crit})"
    return [crit] if len(terms) == 1 else [f"({crit})"]


# ---------------------------------------------------------------- did the provider check the sender?

_RESINFO = re.compile(r"\b(dkim|spf|dmarc)\s*=\s*([a-z]+)([^;]*)", re.I)
_PROP = re.compile(r"\b(header\.d|header\.i|header\.from|smtp\.mailfrom|smtp\.from)\s*=\s*\"?([^\s;\"()]+)", re.I)
_SECOND = {"co", "com", "net", "org", "gov", "gouv", "ac", "edu", "ne", "or"}
# mailbox providers whose authentication servers carry another name than their mail servers
PROVIDER_ALIASES = {"gmail.com": ["google.com"], "googlemail.com": ["google.com"],
                    "outlook.com": ["outlook.com", "microsoft.com", "office365.com", "hotmail.com"],
                    "office365.com": ["outlook.com", "microsoft.com"], "hotmail.com": ["outlook.com", "microsoft.com"],
                    "live.com": ["outlook.com", "microsoft.com"], "me.com": ["apple.com", "icloud.com"],
                    "icloud.com": ["apple.com", "me.com"], "yahoo.com": ["yahoo.com", "yahoo.net"],
                    "zoho.eu": ["zoho.com", "zoho.eu"], "zoho.com": ["zoho.com", "zoho.eu"],
                    "messagingengine.com": ["fastmail.com", "messagingengine.com"],
                    "fastmail.com": ["fastmail.com", "messagingengine.com"]}


def base_domain(host: str) -> str:
    """mx.google.com -> google.com, mail.example.co.uk -> example.co.uk (rough, enough to compare servers)."""
    parts = [p for p in (host or "").lower().strip(".").split(".") if p]
    if len(parts) >= 3 and parts[-2] in _SECOND and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def trusted_servers(acc: dict, mx: list[str] | None = None) -> set[str]:
    """Base domains this mailbox is hosted by: its own servers (IMAP, SMTP, MX) and their known aliases, or the
    account's `auth_servers` when set. Being one of them is not enough to be trusted: see sender_check."""
    if acc.get("auth_servers"):
        return {base_domain(s) for s in acc["auth_servers"]}
    out: set[str] = set()
    for h in [acc.get("imap_host") or "", acc.get("smtp_host") or "", *(mx or [])]:
        b = base_domain(h)
        if b:
            out.add(b)
            out.update(PROVIDER_ALIASES.get(b, []))
    return out


def _aligned(d: str, from_domain: str) -> bool:
    d = d.lower().strip(".").split("@")[-1]
    return bool(d) and (d == from_domain or from_domain.endswith("." + d) or d.endswith("." + from_domain))


# providers known to write their own Authentication-Results on EVERY incoming mail: when the mailbox is really there
# (its IMAP / SMTP / MX servers) and their name tops its recent mail, it is trusted without asking the owner
STAMPING = {"google.com", "yahoo.com", "yahoo.net", "messagingengine.com", "fastmail.com", "zoho.com", "zoho.eu",
            "zohomail.com", "icloud.com", "apple.com"}
DETECT_MIN = 10          # recent mails with their topmost Authentication-Results noted...
DETECT_DOMAINS = 3       # ...from at least this many sender domains...
DETECT_SHARE = 0.9       # ...and this share of them topped by the same server...
DETECT_DAYS = 7          # ...received over at least a week, to offer an unknown server (a flood of planted headers
                         # would have to last that long, and the owner still has to confirm it)


def _cfws_free(s: str) -> str:
    """The header without its quoted strings and (nested) comments: `dkim=pass (header.d=stripe.com)` or
    `reason="header.from=stripe.com"` never count."""
    s = re.sub(r'"(?:[^"\\]|\\.)*"', '""', s)
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\((?:[^()\\]|\\.)*\)", " ", s)
    return s.replace("(", " ").replace(")", " ")


def authserv_id(top: str) -> str:
    """The server that wrote an Authentication-Results header (its authserv-id, lowercase), "" when missing."""
    head = _cfws_free(top or "").split(";", 1)[0].strip()
    tok = head.split()[0].lower() if head else ""
    return "" if "=" in tok else tok


def detect(samples: list[tuple[str, str, float | None]], own_domain: str, days: float = 0) -> str:
    """The base domain that tops the Authentication-Results of nearly all recent mail -> the provider stamps every
    mail. samples: (authserv-id of the topmost header or "", sender address, received at) of the newest mails, in the
    order the server received them (never their Date: header, which the sender writes). days: the samples must span
    that long. "" when unsure (a provider that writes nothing: whatever header a sender planted would be on top)."""
    rows = [(base_domain(a) if a else "", (f or "").lower().rsplit("@", 1)[-1], r) for a, f, r in samples]
    rows = [x for x in rows if x[1] and x[1] != own_domain.lower()]     # its own mail may skip the check
    if len(rows) < DETECT_MIN or len({d for _, d, _ in rows}) < DETECT_DOMAINS:
        return ""
    if days:
        got = [r for _, _, r in rows if r]
        if len(got) < len(rows) or max(got) - min(got) < days * 86400:
            return ""
    counts: dict[str, int] = {}
    for a, _, _ in rows:
        if a:
            counts[a] = counts.get(a, 0) + 1
    best = max(counts, key=lambda k: counts[k], default="")
    return best if best and counts[best] >= DETECT_SHARE * len(rows) else ""


def sender_check(acc: dict, samples: list[tuple[str, str, float | None]], mx: Callable[[], list[str]]) -> dict:
    """How the mailbox's senders are checked -> {state, server}: "owner" (the owner named the servers:
    auth_servers), "auto" (a known provider that stamps every mail and hosts the mailbox: its IMAP / SMTP servers -
    an MX alone could front another server), "detected" (one of the mailbox's own servers tops nearly all its mail of
    the last week, not a known provider: trusted once the owner confirms it), "none" (no sender is ever verified)."""
    if acc.get("auth_servers"):
        return {"state": "owner", "server": ", ".join(acc["auth_servers"])}
    own = (acc.get("address") or "").rsplit("@", 1)[-1]
    d = detect(samples, own)
    if d and d in STAMPING and d in trusted_servers(acc):
        return {"state": "auto", "server": d}
    d = detect(samples, own, DETECT_DAYS)
    if d and d in trusted_servers(acc, mx()):
        return {"state": "detected", "server": d}
    return {"state": "none", "server": ""}


def top_result(msg: Message) -> str:
    """The topmost Authentication-Results header of a message ("" when none)."""
    try:
        heads = msg.get_all("authentication-results") or []
    except Exception:  # noqa: BLE001 - malformed headers
        return ""
    return str(heads[0]) if heads else ""


def verified(top: str, sender: str, trusted: set[str]) -> bool:
    """`top` = top_result(msg). True when the topmost Authentication-Results header was written by the mailbox's provider (its authserv-id is
    one of `trusted`) and says the sender's domain passed DMARC, DKIM or SPF. The headers below it can be written by
    anyone, so only the top one counts, and only if it is the provider's."""
    sender = (sender or "").lower()
    if "@" not in sender or not trusted:
        return False
    from_domain = sender.rsplit("@", 1)[1]
    if not top.strip():
        return False
    server = authserv_id(top)
    if not server or base_domain(server) not in trusted:
        return False
    for kind, result, rest in _RESINFO.findall(_cfws_free(top)):
        if result.lower() != "pass":
            continue
        props = {k.lower(): v for k, v in _PROP.findall(rest)}
        kind = kind.lower()
        if kind == "dmarc" and props.get("header.from", "").lower() == from_domain:
            return True
        if kind == "dkim" and _aligned(props.get("header.d") or props.get("header.i") or "", from_domain):
            return True
        if kind == "spf" and _aligned(props.get("smtp.mailfrom") or props.get("smtp.from") or "", from_domain):
            return True
    return False
