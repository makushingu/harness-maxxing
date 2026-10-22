"""`maxxing mcp` - the MCP servers of Claude Code (Settings -> MCP) from scripts and sessions.

    maxxing mcp list [--json]             every server, where it applies, its state (checks first)
    maxxing mcp add NAME URL [--where projects/acme/topics/blog] [--header 'Authorization: Bearer ${KEY}']
    maxxing mcp add NAME --command 'npx -y pkg' [--env KEY=VALUE] [--where ...]
    maxxing mcp remove NAME [--where ...]

No --where = every session. Secrets go in the Keys vault and are referenced as ${KEY_NAME}.
OAuth servers are connected from Settings -> MCP (button Connect).
"""
from __future__ import annotations

import json
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="action", required=True)
    ls = sub.add_parser("list", help="servers, where they apply and their state")
    ls.add_argument("--json", action="store_true")
    ls.add_argument("--no-check", action="store_true", help="do not ask Claude Code for the states")
    a = sub.add_parser("add", help="add a server (URL, or --command for a local program)")
    a.add_argument("name")
    a.add_argument("url", nargs="?")
    a.add_argument("--command", help="local program (stdio), e.g. 'npx -y some-mcp'")
    a.add_argument("--sse", action="store_true", help="the URL speaks SSE (old transport)")
    a.add_argument("--header", action="append", default=[], help="'Name: value' (repeatable)")
    a.add_argument("--env", action="append", default=[], help="KEY=VALUE for --command (repeatable)")
    a.add_argument("--where", help="workspace folder (topic) - default: every session")
    r = sub.add_parser("remove", help="remove a server")
    r.add_argument("name")
    r.add_argument("--where", help="workspace folder (topic) - default: every session")


def _pairs(items: list[str], sep: str) -> dict[str, str]:
    out = {}
    for it in items:
        k, _, v = it.partition(sep)
        if k.strip():
            out[k.strip()] = v.strip()
    return out


def _handler(a) -> int:
    from . import mcp
    try:
        if a.action == "list":
            if not a.no_check:
                mcp.check(wait=True)
            rows = mcp.servers()
            if a.json:
                print(json.dumps(rows, indent=2, ensure_ascii=False))
                return 0
            for s in rows:
                where = s["where"]["rel"] or "every session"
                print(f"{s['name']:<28} {s['type']:<6} {s['state']:<11} {where}")
            if not rows:
                print("no MCP server (Settings -> MCP or `maxxing mcp add`)")
            return 0
        if a.action == "add":
            if a.command:
                spec = {"type": "stdio", "command": a.command, "env": _pairs(a.env, "=")}
            else:
                spec = {"type": "sse" if a.sse else "http", "url": a.url, "headers": _pairs(a.header, ":")}
            res = mcp.add(a.name, spec, a.where)
            print(f"{a.name} added" + (f" (keys now exposed to sessions: {', '.join(res['exposed'])})"
                                       if res["exposed"] else ""))
            return 0
        folder = mcp._folder_of(a.where) if a.where else None          # noqa: SLF001
        match = [s for s in mcp.servers() if s["name"] == a.name and s["where"]["path"] == folder]
        if not match:
            print(f"{a.name}: no such server there", file=sys.stderr)
            return 1
        mcp.remove(match[0]["id"])
        print(f"{a.name} removed")
        return 0
    except mcp.McpError as e:
        print(f"{a.name if hasattr(a, 'name') else 'mcp'}: {e.message}", file=sys.stderr)
        return 1 if e.status == 404 else 2


cli.register("mcp", "MCP servers of Claude Code: list, add, remove", _configure, _handler)
