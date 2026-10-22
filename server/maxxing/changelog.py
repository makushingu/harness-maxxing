"""The public changelog (CHANGELOG.md at the repo root) parsed for the UI "What's new" dialog.

CHANGELOG.md is written for users (what changes for them, plain language). Technical notes for the
maintainers go to docs/dev/CHANGES.md, which is never shown in the product.
"""
from __future__ import annotations

import re

from . import __version__, config

# "[Show me](#show:<id>)" after a bullet: the UI turns it into a button that shows the feature (web
# features/whatsnew/showcases.ts); plain-text readers (terminal, Telegram) drop it.
SHOW_LINK = re.compile(r"\s*\[[^\]\n]*\]\(#show:[\w-]+\)")
_HEAD = re.compile(r"^##\s+(?P<version>\S+)(?:\s+-\s+(?P<label>.+?))?\s*$")
_PRE = {"alpha": "a", "beta": "b", "rc": "rc"}


def strip_show(text: str) -> str:
    return SHOW_LINK.sub("", text)


def normalize(v: str) -> str:
    """'2.0.0-alpha.6' / '2.0.0a6' / 'v2.0.0' -> '2.0.0a6' (comparable with __version__)."""
    v = v.strip().lstrip("vV").lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)*)(?:[-.]?(alpha|beta|rc|a|b)[-.]?(\d+))?", v)
    if not m:
        return v
    base, pre, n = m.groups()
    return base + (_PRE.get(pre, pre) + n if pre else "")


def parse(text: str) -> list[dict]:
    """-> [{version, label, current, body}] newest first (body = the markdown of that section)."""
    out: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        m = _HEAD.match(line)
        if m:
            cur = {"version": m["version"], "label": (m["label"] or "").strip(),
                   "current": normalize(m["version"]) == normalize(__version__), "body": []}
            out.append(cur)
        elif cur is not None:
            cur["body"].append(line)
    for e in out:
        e["body"] = "\n".join(e["body"]).strip()
    return out


def entries(limit: int = 10) -> dict:
    try:
        text = (config.CODE / "CHANGELOG.md").read_text()
    except OSError:
        text = ""
    return {"version": __version__, "entries": parse(text)[:limit]}
