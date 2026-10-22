"""`maxxing import <zip> [--dry-run]` / `maxxing import --prompt [agent]` - import another agent's memory."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import cli


def _configure(p) -> None:
    p.add_argument("zip", nargs="?", help="the zip made by the old agent (see --prompt)")
    p.add_argument("--dry-run", action="store_true", help="only show what would be imported")
    p.add_argument("--prompt", nargs="?", const="other", metavar="AGENT",
                   help="print the prompt to give the old agent (hermes, claude-code, openclaw, other)")
    p.add_argument("--json", action="store_true", help="machine-readable output")


def _handler(a) -> int:
    from . import importer
    if a.prompt:
        print(importer.prompt(a.prompt))
        return 0
    if not a.zip:
        print("Usage: maxxing import <export.zip> [--dry-run]   |   maxxing import --prompt [agent]")
        return 2
    src = Path(a.zip).expanduser()
    if not src.is_file():
        print(f"No such file: {src}")
        return 2
    try:
        if a.dry_run:
            res = importer.inspect(src)
        else:
            uid, tmp = importer.new_upload()
            shutil.copyfile(src, tmp)
            res = importer.apply(tmp)
            res["finish_prompt"] = importer.finish_prompt(res)
    except importer.ImportFailed as e:
        print(f"Import refused: {e.message}")
        return 1
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if a.dry_run:
        for pr in res["projects"]:
            tps = ", ".join(("" if t["exists"] else "+") + t["name"] for t in pr["topics"]) or "-"
            print(f"{'merge' if pr['exists'] else 'new  '}  {pr['name']}: {tps}")
        print(f"skills: {', '.join(res['skills']) or '-'} · aside: {', '.join(res['aside']) or '-'} · "
              f"{res['files']} files")
    else:
        print(f"Imported: {len(res['projects'])} new projects, {len(res['topics'])} new topics, {res['files']} files.")
        print(f"Report: {res['report']}")
    for s in res["secrets"]:
        print(f"refused (contains {', '.join(s['kinds'])}): {s['file']}")
    for s in res["skipped"]:
        print(f"skipped ({s['reason']}): {s['file']}")
    return 0


cli.register("import", "Import the memory of another agent from a zip", _configure, _handler)
