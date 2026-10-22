#!/usr/bin/env python3
"""Generate THIRD_PARTY_NOTICES.md: the third-party code Harness Maxxing ships or installs, with its license.

    python3 scripts/third_party_notices.py            (writes THIRD_PARTY_NOTICES.md at the repository root)
    python3 scripts/third_party_notices.py --check    (exit 1 when the file is not up to date)

Run it when you add or upgrade a dependency. Standard library only (Python >= 3.11). It reads:
- Python: the packages `server/uv.lock` resolves for the server (runtime dependencies and the `voice` extra, not the
  dev group); license texts from the dist-info folders of `server/.venv` (`cd server && uv sync --extra voice`);
- JavaScript: the production `dependencies` of `web/package.json` and everything they pull in (`web/package-lock.json`),
  bundled into `web/dist`, plus the build-time code Vite and Tailwind embed in it; texts from `web/node_modules`
  (`cd web && npm ci`); the fonts of `web/dist` come from the `@fontsource-variable/*` packages (SIL OFL 1.1);
- Go: the modules of `pc-agent/go.mod`; texts from the Go module cache when present (`go mod download`).
The output is sorted and has no date or local path: the same inputs give the same file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "THIRD_PARTY_NOTICES.md"
PY_TARGET = {"python_version": "3.12", "python_full_version": "3.12.0", "sys_platform": "linux",
             "platform_system": "Linux", "os_name": "posix", "implementation_name": "cpython",
             "platform_python_implementation": "CPython", "platform_machine": "x86_64"}
LICENSE_FILE = re.compile(r"^(licen[cs]e|copying|notice|copyright|unlicense)([-._].*)?$", re.I)
# build-time code that ends up inside web/dist (module preload helper, Tailwind's preflight CSS)
JS_EMBEDDED = ("vite", "tailwindcss")
# Go modules whose license cannot be read without the module cache (checked by hand on pkg.go.dev)
GO_KNOWN = {"github.com/coder/websocket": "ISC", "golang.org/x/sys": "BSD-3-Clause"}


# ---- license detection -------------------------------------------------------------------------------------------
def norm_license(s: str | None) -> str:
    s = (s or "").strip()
    if not s or len(s) > 100 or "\n" in s:
        return ""
    aliases = {"MIT License": "MIT", "BSD": "BSD-3-Clause", "BSD License": "BSD-3-Clause", "3-Clause BSD License": "BSD-3-Clause",
               "Apache 2.0": "Apache-2.0", "Apache License 2.0": "Apache-2.0", "Apache Software License": "Apache-2.0",
               "Apache License, Version 2.0": "Apache-2.0", "ISC License": "ISC", "ISC License (ISCL)": "ISC",
               "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0"}
    return aliases.get(s, s)


def license_from_text(text: str) -> str:
    t = " ".join(text.split()).lower()
    if "sil open font license" in t:
        return "OFL-1.1"
    if "apache license" in t and "version 2.0" in t:
        return "Apache-2.0"
    if "mozilla public license" in t:
        return "MPL-2.0"
    if "this is free and unencumbered software released into the public domain" in t:
        return "Unlicense"
    if "permission is hereby granted, free of charge" in t:
        return "MIT"
    if "permission to use, copy, modify, and/or distribute this software for any purpose" in t:
        return "0BSD" if "provided that the above copyright notice" not in t else "ISC"
    if "redistribution and use in source and binary forms" in t:
        return "BSD-3-Clause" if "neither the name" in t or "names of its contributors" in t else "BSD-2-Clause"
    if "gnu lesser general public license" in t:
        return "LGPL"
    if "gnu affero general public license" in t:
        return "AGPL"
    if "gnu general public license" in t:
        return "GPL"
    return ""


def classifier_license(lines: list[str]) -> str:
    out = []
    for c in lines:
        if c.startswith("License :: OSI Approved :: "):
            out.append(norm_license(c.rsplit("::", 1)[1].strip()))
    return " OR ".join(sorted(set(x for x in out if x)))


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").strip()
    except OSError:
        return ""


def license_files(d: Path, recursive: bool = False) -> list[Path]:
    if not d.is_dir():
        return []
    it = d.rglob("*") if recursive else d.iterdir()
    return sorted((p for p in it if p.is_file() and (recursive or LICENSE_FILE.match(p.name))), key=lambda p: str(p.relative_to(d)))


# ---- Python ------------------------------------------------------------------------------------------------------
def _marker_ok(marker: str | None) -> bool:
    """Tiny PEP 508 marker evaluation for the server target (Linux, CPython 3.12)."""
    if not marker:
        return True

    def ver(v: str) -> tuple:
        return tuple(int(x) for x in re.findall(r"\d+", v)[:3])

    def one(m: re.Match) -> str:
        var, op, val = m.group(1), m.group(2), m.group(3)
        if var == "extra":
            return "False"
        have = PY_TARGET.get(var, "")
        if var.startswith("python"):
            a, b = ver(have), ver(val)
            res = {"==": a[:len(b)] == b, "!=": a[:len(b)] != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}.get(op, True)
        elif op in ("in", "not in"):
            res = (have in val) == (op == "in")
        else:
            res = {"==": have == val, "!=": have != val}.get(op, True)
        return str(bool(res))

    expr = re.sub(r"(\w+)\s*(==|!=|<=|>=|<|>|not in|in)\s*['\"]([^'\"]*)['\"]", one, marker)
    if not re.fullmatch(r"[\sA-Za-z()]*", expr) or set(re.findall(r"[A-Za-z]+", expr)) - {"True", "False", "and", "or", "not"}:
        return True
    return bool(eval(expr, {"__builtins__": {}}))  # noqa: S307 - only True/False/and/or/not/() remain


def python_packages() -> list[dict]:
    lock = tomllib.loads((ROOT / "server" / "uv.lock").read_text())
    pkgs = {p["name"]: p for p in lock["package"]}
    root = next(p for p in lock["package"] if p.get("source", {}).get("editable") == ".")
    todo = [(d, "runtime") for d in root.get("dependencies", [])]
    todo += [(d, f"{extra} (optional)") for extra, deps in root.get("optional-dependencies", {}).items() for d in deps]
    groups: dict[str, str] = {}                      # name -> "runtime" or "<extra> (optional)"
    visited: set[tuple] = set()
    while todo:
        dep, group = todo.pop()
        name = dep["name"]
        p = pkgs.get(name)
        key = (name, tuple(dep.get("extra", [])), group)
        if p is None or key in visited or not _marker_ok(dep.get("marker")):
            continue
        visited.add(key)
        if groups.get(name) != "runtime":
            groups[name] = group
        todo += [(d, group) for d in p.get("dependencies", [])]
        for e in dep.get("extra", []):
            todo += [(d, group) for d in p.get("optional-dependencies", {}).get(e, [])]
    site = sorted((ROOT / "server" / ".venv" / "lib").glob("python*/site-packages"))
    out = []
    for name in sorted(groups):
        out.append(_python_info(name, pkgs[name]["version"], groups[name], site[0] if site else None))
    return out


def _dist_info(site: Path | None, name: str, version: str) -> Path | None:
    if site is None:
        return None
    want = re.sub(r"[-_.]+", "_", name).lower()
    for d in site.glob("*.dist-info"):
        n, _, v = d.name[: -len(".dist-info")].rpartition("-")
        if re.sub(r"[-_.]+", "_", n).lower() == want and v == version:
            return d
    return None


def _python_info(name: str, version: str, group: str, site: Path | None) -> dict:
    info = {"eco": "Python", "name": name, "version": version, "group": group, "license": "", "texts": [],
            "url": f"https://pypi.org/project/{name}/{version}/"}
    d = _dist_info(site, name, version)
    if d is None:
        return info
    meta = read_text(d / "METADATA")
    head = meta.split("\n\n", 1)[0]
    fields: dict[str, list[str]] = {}
    for line in head.splitlines():
        k, _, v = line.partition(": ")
        if v:
            fields.setdefault(k, []).append(v.strip())
    lic = norm_license((fields.get("License-Expression") or [""])[0]) or classifier_license(fields.get("Classifier", [])) \
        or norm_license((fields.get("License") or [""])[0])
    files = license_files(d / "licenses", recursive=True) or license_files(d)
    info["texts"] = [(str(f.relative_to(d / "licenses" if (d / "licenses").is_dir() else d)), read_text(f)) for f in files]
    if not info["texts"]:                              # no license in the dist-info: one at the top of the package
        for row in sorted(read_text(d / "RECORD").splitlines()):
            rel = row.split(",", 1)[0]
            if rel.count("/") <= 1 and not rel.startswith(d.name) and LICENSE_FILE.match(rel.rsplit("/", 1)[-1]):
                info["texts"].append((rel, read_text(d.parent / rel)))
    info["license"] = lic or next((license_from_text(t) for _, t in info["texts"] if license_from_text(t)), "")
    return info


# ---- JavaScript --------------------------------------------------------------------------------------------------
def js_packages() -> list[dict]:
    web = ROOT / "web"
    lock = json.loads((web / "package-lock.json").read_text())["packages"]
    pkg = json.loads((web / "package.json").read_text())

    def resolve(frm: str, name: str) -> str | None:
        base = frm
        while True:
            cand = (base + "/" if base else "") + "node_modules/" + name
            if cand in lock:
                return cand
            if not base:
                return None
            i = base.rfind("/node_modules/")
            base = base[:i] if i >= 0 else ""

    seen: dict[str, str] = {}
    todo = [("", n, "bundled in web/dist") for n in sorted(pkg.get("dependencies", {}))]
    todo += [("", n, "build code embedded in web/dist") for n in JS_EMBEDDED]
    while todo:
        frm, name, group = todo.pop()
        path = resolve(frm, name)
        if path is None or path in seen:
            continue
        seen[path] = group
        e = lock[path]
        if group != "bundled in web/dist":
            continue                                   # only the build tool itself, not its own dependencies
        for field in ("dependencies", "optionalDependencies", "peerDependencies"):
            todo += [(path, n, group) for n in sorted(e.get(field, {}))]
    by_id: dict[tuple, dict] = {}
    for path in sorted(seen):
        e = lock[path]
        name = path.rsplit("node_modules/", 1)[1]
        d = web / path
        texts = [(f.name, read_text(f)) for f in license_files(d)]
        if name in JS_EMBEDDED:                        # only the tool's own license, not those of what it bundles
            texts = [(n, re.split(r"\n#+ Licenses of bundled dependencies", t, maxsplit=1)[0].strip()) for n, t in texts]
        lic = e.get("license") or ""
        if not lic:
            lic = json.loads(read_text(d / "package.json") or "{}").get("license") or ""
        if isinstance(lic, dict):
            lic = lic.get("type", "")
        lic = norm_license(str(lic)) or next((license_from_text(t) for _, t in texts if license_from_text(t)), "")
        key = (name, e.get("version", ""))
        if key in by_id:
            continue
        by_id[key] = {"eco": "JavaScript", "name": name, "version": e.get("version", ""), "group": seen[path],
                      "license": lic, "texts": texts, "url": f"https://www.npmjs.com/package/{name}/v/{e.get('version', '')}"}
    return [by_id[k] for k in sorted(by_id)]


# ---- Go ----------------------------------------------------------------------------------------------------------
def _go_cache() -> Path | None:
    for c in (os.environ.get("GOMODCACHE"), (os.environ.get("GOPATH") or "") and Path(os.environ["GOPATH"]) / "pkg" / "mod",
              Path.home() / "go" / "pkg" / "mod"):
        if c and Path(c).is_dir():
            return Path(c)
    return None


def go_packages() -> list[dict]:
    mod = read_text(ROOT / "pc-agent" / "go.mod")
    reqs = re.findall(r"^\s*(?:require\s+)?([\w.\-]+(?:/[\w.\-~]+)+)\s+(v[\w.\-+]+)", mod, re.M)
    cache = _go_cache()
    out = []
    for name, version in sorted(set(reqs)):
        esc = re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), name)
        d = cache / f"{esc}@{version}" if cache else None
        texts = [(f.name, read_text(f)) for f in license_files(d)] if d else []
        lic = next((license_from_text(t) for _, t in texts if license_from_text(t)), "") or GO_KNOWN.get(name, "")
        out.append({"eco": "Go", "name": name, "version": version, "group": "compiled into the PC agent", "license": lic,
                    "texts": texts, "url": f"https://pkg.go.dev/{name}@{version}?tab=licenses"})
    return out


# ---- output ------------------------------------------------------------------------------------------------------
COPYLEFT = re.compile(r"\b(A?GPL|LGPL)", re.I)


def render(items: list[dict]) -> str:
    counts: dict[str, int] = {}
    for it in items:
        counts[it["license"] or "UNKNOWN"] = counts.get(it["license"] or "UNKNOWN", 0) + 1
    lines = [
        "# Third-party notices",
        "",
        "Harness Maxxing includes or installs the third-party software below. Each one keeps its own license, reproduced",
        "here with its copyright notice. Harness Maxxing itself is under the [LICENSE](LICENSE) of this repository.",
        "",
        "- **JavaScript**: bundled into the web interface (`web/dist`), fonts included (SIL Open Font License 1.1).",
        "- **Python**: installed from PyPI into the server's virtual environment by the installer and `maxxing update`.",
        "- **Go**: compiled into the optional PC agent (`pc-agent/`).",
        "",
        "Tools the installer downloads from their publishers (Claude Code, uv, Python, Node.js, Caddy, Chromium, ...)",
        "are not part of this list: they come with their own licenses.",
        "",
        "Generated by `scripts/third_party_notices.py` from the lock files; do not edit by hand.",
        "",
        "## Summary",
        "",
        "| License | Packages |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    texts: dict[str, list[str]] = {}
    for eco in ("JavaScript", "Python", "Go"):
        group = [it for it in items if it["eco"] == eco]
        lines += ["", f"## {eco} ({len(group)})", "", "| Package | Version | License | Use |", "|---|---|---|---|"]
        for it in group:
            lines.append(f"| [{it['name']}]({it['url']}) | {it['version']} | {it['license'] or 'UNKNOWN'} | {it['group']} |")
            if it["texts"]:
                for fname, t in it["texts"]:
                    texts.setdefault(t, []).append(f"{it['name']} {it['version']} ({fname})")
    lines += ["", "## License texts", "",
              "Each text below applies to the packages listed above it (identical texts are shown once).", ""]
    for t, users in sorted(texts.items(), key=lambda kv: kv[1][0].lower()):
        fence = "~~~~" if "```" in t else "```"
        lines += ["### " + ", ".join(sorted(users, key=str.lower)), "", fence + "text", t, fence, ""]
    missing = [it for it in items if not it["texts"]]
    if missing:
        lines += ["## Packages without a license file", "",
                  "Their license is named above; the full text is at the link:", ""]
        lines += [f"- [{it['name']} {it['version']}]({it['url']}) - {it['license'] or 'UNKNOWN'}" for it in missing]
        lines.append("")
    out = "\n".join(lines).rstrip() + "\n"
    return out.replace(str(ROOT) + "/", "").replace(str(Path.home()), "~")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when THIRD_PARTY_NOTICES.md is not up to date")
    a = ap.parse_args()
    items = js_packages() + python_packages() + go_packages()
    text = render(items)
    flagged = sorted(f"{it['eco']} {it['name']} {it['version']}: {it['license'] or 'UNKNOWN'}" for it in items
                     if not it["license"] or COPYLEFT.search(it["license"]))
    for f in flagged:
        print(f"check: {f}", file=sys.stderr)
    no_text = sum(1 for it in items if not it["texts"])
    if a.check:
        ok = OUT.exists() and OUT.read_text() == text
        print("THIRD_PARTY_NOTICES.md is up to date" if ok else "THIRD_PARTY_NOTICES.md is out of date: "
              "run python3 scripts/third_party_notices.py", file=sys.stderr if not ok else sys.stdout)
        return 0 if ok else 1
    OUT.write_text(text)
    print(f"{OUT.name}: {len(items)} packages ({no_text} without a license file), {len(flagged)} to check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
