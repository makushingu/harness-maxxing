"""Dependency and tooling checks for `maxxing doctor`: known vulnerabilities in the installed lockfiles (OSV),
Claude Code behind its latest release, and the size of the skill listing Claude Code puts in every prompt.

Network calls only on demand (`maxxing doctor --deps` for OSV; the Claude Code release check follows the doctor's
`--offline`). Standard library only: the CLI stays fast.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from . import config

OSV_BATCH = "https://api.osv.dev/v1/querybatch"
CLAUDE_LATEST = "https://registry.npmjs.org/@anthropic-ai/claude-code/latest"
CLAUDE_TAGS = "https://registry.npmjs.org/-/package/@anthropic-ai/claude-code/dist-tags"
# Claude Code lists every skill (name + description) in the system prompt within a budget (about 1% of the context
# window, 8 000 characters when unknown); past it, the descriptions of the least used skills are dropped.
SKILL_LISTING_BUDGET = 8000


def _post_json(url: str, body: dict, timeout: float = 30) -> dict:
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _get_json(url: str, timeout: float = 6) -> dict:
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}),
                                timeout=timeout) as r:
        return json.load(r)


# ---- installed packages --------------------------------------------------------------------
def python_packages(lock: Path) -> list[tuple[str, str]]:
    try:
        data = tomllib.loads(lock.read_text())
    except (OSError, ValueError):
        return []
    return [(p["name"], p["version"]) for p in data.get("package", [])
            if "version" in p and (p.get("source") or {}).get("registry")]


def npm_packages(lock: Path) -> list[tuple[str, str]]:
    try:
        data = json.loads(lock.read_text())
    except (OSError, ValueError):
        return []
    out = set()
    for key, v in (data.get("packages") or {}).items():
        if key.startswith("node_modules/") and isinstance(v, dict) and v.get("version") and not v.get("link"):
            out.add((key.rsplit("node_modules/", 1)[-1], v["version"]))
    return sorted(out)


def lockfiles() -> list[tuple[str, str, Path]]:
    """(label, ecosystem, lockfile) of what this install runs."""
    return [("server", "PyPI", config.CODE / "server" / "uv.lock"),
            ("web", "npm", config.CODE / "web" / "package-lock.json"),
            ("video tools", "npm", config.STATE / "tools" / "remotion" / "package-lock.json")]


def osv_scan(timeout: float = 30) -> dict:
    """-> {"checked": n, "vulnerable": [{"where", "ecosystem", "name", "version", "ids"}]}. Raises on network errors."""
    queries: list[tuple[str, str, str, str]] = []
    for where, eco, lock in lockfiles():
        pkgs = python_packages(lock) if eco == "PyPI" else npm_packages(lock)
        queries += [(where, eco, n, v) for n, v in pkgs]
    found = []
    for i in range(0, len(queries), 500):
        chunk = queries[i:i + 500]
        res = _post_json(OSV_BATCH, {"queries": [{"package": {"ecosystem": e, "name": n}, "version": v}
                                                 for _, e, n, v in chunk]}, timeout)
        for (where, eco, name, version), r in zip(chunk, res.get("results") or []):
            if r.get("vulns"):
                found.append({"where": where, "ecosystem": eco, "name": name, "version": version,
                              "ids": [x.get("id") for x in r["vulns"]][:5]})
    return {"checked": len(queries), "vulnerable": found}


# ---- Claude Code ---------------------------------------------------------------------------
def _vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def claude_latest(timeout: float = 6) -> str | None:
    try:
        v = _get_json(CLAUDE_LATEST, timeout).get("version")
        return v if isinstance(v, str) else None
    except Exception:  # noqa: BLE001 - offline: no opinion
        return None


def claude_stable(timeout: float = 6) -> str | None:
    """The npm `stable` dist-tag of Claude Code (a release already out for some days), or None offline."""
    try:
        v = _get_json(CLAUDE_TAGS, timeout).get("stable")
        return v if isinstance(v, str) else None
    except Exception:  # noqa: BLE001 - offline: no opinion
        return None


def claude_behind(installed: str, latest: str | None) -> int:
    """Patch releases between the installed and the latest version (0 = up to date or unknown)."""
    if not latest:
        return 0
    a, b = _vtuple(installed), _vtuple(latest)
    if len(a) < 3 or len(b) < 3 or a >= b:
        return 0
    return b[2] - a[2] if a[:2] == b[:2] else max(1, b[2])


# ---- skill listing -------------------------------------------------------------------------
_DESC = re.compile(r"^description:\s*(.+?)(?=^[\w-]+:|^---)", re.S | re.M)


def skill_listing(roots: list[Path]) -> dict:
    """Skills Claude Code lists in every prompt from these folders -> {"count", "chars"} (name + description)."""
    count = chars = 0
    for root in roots:
        try:
            files = sorted(root.glob("*/SKILL.md"))
        except OSError:
            continue
        for f in files:
            try:
                head = f.read_text(errors="replace")[:6000]
            except OSError:
                continue
            m = _DESC.search(head)
            count += 1
            chars += len(f.parent.name) + (len(" ".join(m.group(1).split())) if m else 0)
    return {"count": count, "chars": chars}
