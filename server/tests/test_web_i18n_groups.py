"""Texts must not stay English or blank: the network error is translated, and a page's lazy dictionary groups are
declared on its route (translate() answers '' while a group downloads)."""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


def _groups() -> dict[str, str]:
    src = (WEB / "i18n" / "groups.ts").read_text(encoding="utf-8")
    body = src[src.index("export const GROUPS"):src.index("} as const")]
    out: dict[str, str] = {}
    for m in re.finditer(r"^  (\w+): \[(.*?)\],?\s*$", body, re.M | re.S):
        for ns in re.findall(r"'(\w+)'", m[2]):
            out[ns] = m[1]
    return out


def test_network_error_is_translated():
    lib = WEB / "lib"
    assert "throw networkError()" in (lib / "api.ts").read_text(encoding="utf-8")
    for f in ("files.ts", "sessions.ts"):
        assert "reject(networkError())" in (lib / "queries" / f).read_text(encoding="utf-8"), f
    for f in lib.rglob("*.ts*"):
        assert "ApiError(0, 'network', 'network')" not in f.read_text(encoding="utf-8"), f
    for lang in ("en", "fr"):
        assert "'common.networkError'" in (WEB / "i18n" / f"{lang}.ts").read_text(encoding="utf-8")


# groups loaded by their own trigger (a paste, a drag, a hover...), not with a page
ON_DEMAND = {"paste", "drag", "where", "media", "skw", "tour", "maxxing", "feedback", "composer", "cut"}

# (route, group) pairs knowingly left undeclared, with the reason
KNOWN = {
    ("sessions/*", "tasks"): "Tasks.tsx; declaring it would overflow the first-load dictionary budget",
    ("sessions/*", "agents"): "agents feature, out of scope",
}


def test_lazy_groups_used_by_a_page_are_declared_on_its_route():
    groups = _groups()
    routes = (WEB / "routes.tsx").read_text(encoding="utf-8")
    missing = []
    found = list(re.finditer(r"path: '([^']*)', lazy: page\(\(\) => import\('\./([^']+)'\)(?:, \[([^\]]*)\])?", routes))
    assert len(found) >= 15 and len(found) == len(re.findall(r"path: '[^']*', lazy: page\(", routes)), len(found)
    for m in found:
        path, mod, declared = m[1], m[2], set(re.findall(r"'(\w+)'", m[3] or ""))
        base = WEB / mod
        folder = base if base.is_dir() else base.parent
        files = list(folder.rglob("*.tsx")) if base.is_dir() or base.parent.name != "pages" else [base.with_suffix(".tsx")]
        for f in files:
            for ns in set(re.findall(r"\bt\('(\w+)\.", f.read_text(encoding="utf-8"))):
                g = groups.get(ns)
                if g and g not in declared and g not in ON_DEMAND:
                    missing.append(f"{path}: {f.relative_to(WEB)} uses {ns}.* (group {g})")
    missing = [x for x in missing if not any(x.startswith(f"{p}: ") and f" (group {g})" in x for (p, g) in KNOWN)]
    assert not missing, ("declare the group on the route or add it to ON_DEMAND", missing)
