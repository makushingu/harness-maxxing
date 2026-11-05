"""`maxxing keys` - the Keys vault (Settings -> Keys) from scripts and sessions.

    maxxing keys list                     names, notes, exposed or not, files marked (never the values)
    maxxing keys get NAME                 print the value (exit 1 if missing)
    printf %s "$V" | maxxing keys set NAME [--note TEXT] [--no-expose]
    maxxing keys delete NAME
    maxxing keys put-file NAME PATH|-     store a secret FILE (keystore, JSON, certificate; 1 byte to 1 MiB)
    maxxing keys get-file NAME [--output PATH] [--force]     its bytes on stdout, or in a new file of mode 600
    maxxing keys delete-file NAME

`set` reads the value from stdin (never from the command line, which `ps` shows). A new key is exposed
by default: every later Claude turn and shell job gets it as an environment variable. A new file is exposed
too, as an environment variable holding its PATH (see maxxing/vault_files.py). In an agent's turn the file
commands are refused.
"""
from __future__ import annotations

import json
import os
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="action", required=True)
    ls = sub.add_parser("list", help="names and notes, never the values")
    ls.add_argument("--json", action="store_true")
    g = sub.add_parser("get", help="print a value")
    g.add_argument("name")
    s = sub.add_parser("set", help="create or update a key; the value is read from stdin")
    s.add_argument("name")
    s.add_argument("--note")
    s.add_argument("--no-expose", action="store_true", help="keep it out of the environment of sessions and jobs")
    d = sub.add_parser("delete", help="remove a key")
    d.add_argument("name")
    pf = sub.add_parser("put-file", help="create or update a secret file; PATH, or - for stdin")
    pf.add_argument("name")
    pf.add_argument("path")
    pf.add_argument("--note")
    pf.add_argument("--no-expose", action="store_true", help="keep its path out of the environment of sessions and jobs")
    gf = sub.add_parser("get-file", help="write a secret file to stdout, or to --output")
    gf.add_argument("name")
    gf.add_argument("--output", metavar="PATH", help="a new file of mode 600 instead of stdout")
    gf.add_argument("--force", action="store_true", help="with --output: overwrite an existing path")
    df = sub.add_parser("delete-file", help="remove a secret file")
    df.add_argument("name")


def _read_input(path: str, limit: int) -> bytes:
    """The bytes of a file or of stdin ("-"), at most limit + 1 (vault_files refuses a file over its size)."""
    if path == "-":
        return sys.stdin.buffer.read(limit + 1)
    with open(path, "rb") as f:
        return f.read(limit + 1)


def _files(a) -> int:
    from . import vault, vault_files
    if a.action == "put-file":
        try:
            data = _read_input(a.path, vault_files.MAX_SIZE)
        except OSError as e:
            print(f"{a.path}: {e.strerror or e}", file=sys.stderr)
            return 2
        existed = vault_files.exists(a.name)
        try:
            vault_files.put(a.name, data, filename=None if a.path == "-" else os.path.basename(a.path), note=a.note,
                            expose=False if a.no_expose else (None if existed else True))
        except vault.VaultError as e:
            print(f"{a.name}: {e}", file=sys.stderr)
            return 2
        print(f"{a.name} {'updated' if existed else 'created'} ({len(data)} bytes)")
        return 0
    if a.action == "get-file":
        data = vault_files.read(a.name)
        if data is None:
            print(f"{a.name}: no such file (Settings -> Keys)", file=sys.stderr)
            return 1
        if not a.output:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
            return 0
        flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_TRUNC if a.force else os.O_EXCL)
        try:
            fd = os.open(a.output, flags, 0o600)
        except FileExistsError:
            print(f"{a.output}: already exists (--force to overwrite)", file=sys.stderr)
            return 1
        except OSError as e:
            print(f"{a.output}: {e.strerror or e}", file=sys.stderr)
            return 1
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(data)
        return 0
    if not vault_files.delete(a.name):
        print(f"{a.name}: no such file", file=sys.stderr)
        return 1
    print(f"{a.name} deleted")
    return 0


def _handler(a) -> int:
    from . import vault, vault_files
    if a.action == "list":
        rows = [{**r, "kind": "text"} for r in vault.list_secrets()] + [{**r, "kind": "file"} for r in vault_files.list_files()]
        rows.sort(key=lambda r: r["name"])
        if a.json:
            fields = {"text": ("name", "note", "expose", "updated"),
                      "file": ("name", "note", "expose", "updated", "filename", "size", "sha256")}
            print(json.dumps([{**{k: r[k] for k in fields[r["kind"]]}, "kind": r["kind"]} for r in rows], indent=2))
        for r in [] if a.json else rows:
            print(f"{r['name']:<40} {'env' if r['expose'] else '   '} {'file' if r['kind'] == 'file' else '    '}  {r['note']}")
        return 0
    from . import agent_guard
    agent = agent_guard.agent_turn()["path"]        # from the turn's own session, not its (changeable) environment
    if agent and a.action in ("get", "set", "delete", "put-file", "get-file", "delete-file"):
        # a turn of an agent: only its own keys, read-only; never a file (those never reach an agent). A speed bump against injected orders (the real limit is
        # its permission mode and approvals), so a message saying "run maxxing keys get" gets nothing.
        from . import agents
        mine = agents.load(agent)["keys"] if agents.exists(agent) else []
        if a.action != "get" or a.name not in mine:
            print(f"{a.name}: not available to this agent (its Keys setting)", file=sys.stderr)
            return 1
    if a.action in ("put-file", "get-file", "delete-file"):
        return _files(a)
    if a.action == "get":
        v = vault.get(a.name)
        if v is None:
            print(f"{a.name}: no such key (Settings -> Keys)", file=sys.stderr)
            return 1
        print(v, end="" if v.endswith("\n") else "\n")
        return 0
    if a.action == "set":
        raw = sys.stdin.read()
        value = raw.strip()
        if "\n" in value and raw.rstrip(" \t\r").endswith("\n"):
            value += "\n"          # a multi-line value (PEM, SSH key) keeps its final line break: OpenSSH wants it
        if not value:
            print("the value is read from stdin: printf %s \"$VALUE\" | maxxing keys set NAME", file=sys.stderr)
            return 2
        existed = vault.get(a.name) is not None
        try:
            vault.put(a.name, value, note=a.note, expose=False if a.no_expose else (None if existed else True))
        except vault.VaultError as e:
            print(f"{a.name}: {e}", file=sys.stderr)
            return 2
        print(f"{a.name} {'updated' if existed else 'created'}")
        return 0
    if not vault.delete(a.name):
        print(f"{a.name}: no such key", file=sys.stderr)
        return 1
    print(f"{a.name} deleted")
    return 0


cli.register("keys", "the Keys vault: list, get, set (value from stdin), delete, put-file, get-file, delete-file", _configure, _handler)
