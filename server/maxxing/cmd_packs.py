"""`maxxing packs` - starter projects (e-commerce, affiliate, creator, apps, second brain, freelance) and `basics`
(puts back the default projects)."""
from __future__ import annotations

import json
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="packs_cmd", required=True)
    s = sub.add_parser("list", help="the starter packs and whether they are installed")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("add", help="add a pack as a new project (`basics` puts back the default projects); never overwrites")
    s.add_argument("id", nargs="+", help="pack id(s), e.g. ecommerce freelance")
    s.add_argument("--json", action="store_true")


def _run(a) -> int:
    from . import packs
    if a.packs_cmd == "list":
        items = packs.list_packs()
        if a.json:
            print(json.dumps(items, indent=2, ensure_ascii=False))
            return 0
        for p in items:
            if p["basics"]:
                state = "complete" if p["installed"] else "some missing"
                print(f"{p['emoji']} {p['id']:<13} {state:<17} {', '.join(p['topics'])}")
            else:
                state = "added" if p["project_exists"] else "-"
                print(f"{p['emoji']} {p['id']:<13} {state:<17} projects/{p['project']}: {', '.join(p['topics'])}")
            print(f"   {p['description']}")
        return 0
    out, code = [], 0
    for pid in a.id:
        try:
            r = packs.install(pid)
            out.append(r)
            if not a.json:
                jobs = f", jobs (disabled): {', '.join(r['jobs'])}" if r["jobs"] else ""
                where = f"projects/{r['project']}" if r["project"] else r["pack"]["project"]
                print(f"{r['pack']['emoji']} {pid}: {where} - {r['created_files']} file(s) added{jobs}")
        except packs.PackError as e:
            code = 2
            print(f"error: {e.message}", file=sys.stderr)
    if a.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    return code


cli.register("packs", "Starter projects: list them, add one (e-commerce, affiliate, creator, apps...)", _configure, _run)
