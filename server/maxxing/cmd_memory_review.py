"""`maxxing memory-review list | apply ID|all | reject ID | undo ID | run SESSION | learn PATH | daily`: the memory proposals
(memory_review.py)."""
from __future__ import annotations

import json

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="action", required=True)
    r = sub.add_parser("run", help="review one session and store its proposals")
    r.add_argument("session")
    r.add_argument("--model", default="haiku")
    r.add_argument("--prompt", default="a", help="a | b (a session) | agent (an agent run)")
    r.add_argument("--json", action="store_true")
    sub.add_parser("list", help="the proposals waiting").add_argument("--json", action="store_true")
    sub.add_parser("apply", help="write a proposal into its memory.md").add_argument("id")
    sub.add_parser("reject").add_argument("id")
    sub.add_parser("undo", help="take back a bullet or a skill that was written").add_argument("id")
    sub.add_parser("daily", help="the daily look at the busy topics, now (proposals go to the notifications)")
    le = sub.add_parser("learn", help="skills and rules the recent sessions of a folder repeat (printed, nothing kept)")
    le.add_argument("path", help="workspace path: projects/<p>/topics/<t>")
    le.add_argument("--model", default="haiku")
    le.add_argument("--write", action="store_true", help="write the proposed skills into the folder")


def _show(x: dict) -> str:
    old = f"\n      old: {x['old']}" if x.get("old") else ""
    return f"{x['id']} [{x['level']}/{x['action']}/{x['source']}] {x['text']}{old}\n      why: {x['why']} · {x['path']}"


def _handler(a) -> int:
    from . import memory_review as mr
    if a.action == "run":
        res = mr.review(a.session, a.model, prompt=a.prompt)
        if a.json:
            print(json.dumps(res, indent=1, ensure_ascii=False))
            return 0
        if res.get("error"):
            print("failed:", res["error"])
            return 1
        print(f"{len(res['proposals'])} proposal(s), ${res['cost']:.4f}, {res['ms']} ms")
        for x in res["proposals"]:
            print(_show(x))
        return 0
    if a.action == "learn":
        res = mr.learn(a.path, a.model)
        if a.write:
            res["written"] = [str(mr.write_skill(a.path.strip("/"), k)) for k in res["skills"]]
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0
    if a.action == "daily":
        new = mr.daily(force=True)
        print("\n".join(map(_show, new)) or "nothing new")
        return 0
    if a.action == "list":
        new = [x for x in mr.load() if x["state"] == "new"]
        print(json.dumps(new, indent=1, ensure_ascii=False) if a.json else "\n".join(map(_show, new)) or "nothing waits")
        return 0
    if a.action == "apply":
        ids = [x["id"] for x in mr.load() if x["state"] == "new"] if a.id == "all" else [a.id]
        for i in ids:
            print(i, mr.apply(i))
        return 0
    print(mr.undo(a.id) if a.action == "undo" else mr.reject(a.id))
    return 0


cli.register("memory-review", "memory bullets and skills proposed from sessions and agent runs", _configure, _handler)
