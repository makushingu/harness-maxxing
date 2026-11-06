"""`maxxing keys` - the Keys vault (Settings -> Keys) from scripts and sessions.

    maxxing keys list                     names, notes, exposed or not, files marked (never the values)
    maxxing keys get NAME                 print the value (exit 1 if missing)
    printf %s "$V" | maxxing keys set NAME [--note TEXT] [--no-expose]
    maxxing keys delete NAME
    maxxing keys put-file NAME PATH|-     store a secret FILE (keystore, JSON, certificate; 1 byte to 1 MiB)
    maxxing keys get-file NAME [--output PATH] [--force]     its bytes on stdout (text only on a terminal), or in
                                          a new file of mode 600
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
    pf = sub.add_parser(
        "put-file", help="store a secret file (keystore, service-account JSON, certificate), 1 byte to 1 MiB",
        description="Store the bytes of PATH (or of stdin with -) in the Keys vault as NAME; an existing NAME is "
                    "replaced and keeps its note and its exposure. The file is kept in the state folder (mode 600), "
                    "never in the backup. A new file is exposed: every later Claude turn and shell job gets the "
                    "environment variable NAME holding the file's PATH (never its content).")
    pf.add_argument("name", help="capital letters, digits and _, starting with a letter (like a text key)")
    pf.add_argument("path", help="the file to store, or - to read it from stdin (1 MiB at most)")
    pf.add_argument("--note", help="a short note shown in Settings -> Keys (200 characters at most)")
    pf.add_argument("--no-expose", action="store_true",
                    help="do not export NAME (the file's path) to sessions and jobs; read it with get-file only")
    gf = sub.add_parser("get-file", help="write a secret file to stdout, or to --output",
                        description="Write the bytes of the secret file NAME to stdout, or to a new file with "
                                    "--output. On a terminal only text is printed: redirect the output or use "
                                    "--output for a binary file.")
    gf.add_argument("name")
    gf.add_argument("-o", "--output", metavar="PATH", help="a new file of mode 600 instead of stdout")
    gf.add_argument("--force", action="store_true", help="with --output: overwrite an existing path")
    df = sub.add_parser("delete-file", help="remove a secret file")
    df.add_argument("name")


def _read_input(path: str, limit: int) -> bytes:
    """The bytes of a file or of stdin ("-"), at most limit + 1 (vault_files refuses a file over its size)."""
    if path == "-":
        return sys.stdin.buffer.read(limit + 1)
    with open(path, "rb") as f:
        return f.read(limit + 1)


def _printable(data: bytes) -> bool:
    """UTF-8 text without control characters other than tab and line breaks: safe to print on a terminal."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return not any((c < " " and c not in "\t\n\r") or "\x7f" <= c <= "\x9f" for c in text)


def _save(data: bytes, output: str, force: bool) -> int:
    """`data` into a temp file of output's folder (mode 600), then renamed to output: never a half-written file.
    Without `force` an existing output (a link included) is kept."""
    import tempfile
    folder = os.path.dirname(os.path.abspath(output))
    try:
        fd, tmp = tempfile.mkstemp(prefix=".maxxing-keys-", suffix=".tmp", dir=folder)
    except OSError as e:
        print(f"{output}: {e.strerror or e}", file=sys.stderr)
        return 1
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if not force:
            try:
                os.link(tmp, output)               # fails if output exists: no overwrite, no race
                return 0
            except FileExistsError:
                raise
            except OSError:                        # no hard links on this file system: check, then rename
                if os.path.lexists(output):
                    raise FileExistsError(output) from None
        os.replace(tmp, output)
    except FileExistsError:
        print(f"{output}: already exists (--force to overwrite)", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"{output}: {e.strerror or e}", file=sys.stderr)
        return 1
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return 0


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
            hint = " (it is a text key: maxxing keys get)" if vault.get(a.name) is not None else " (Settings -> Keys)"
            print(f"{a.name}: no such file{hint}", file=sys.stderr)
            return 1
        if a.output:
            return _save(data, a.output, a.force)
        if sys.stdout.isatty() and not _printable(data):
            print(f"{a.name}: binary content, not printed on a terminal: use -o FILE or redirect the output "
                  f"(> FILE)", file=sys.stderr)
            return 2
        try:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except BrokenPipeError:                    # `| head`: the reader is gone; no traceback, like cat
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())   # the flush at exit fails quietly too
            return 141
        return 0
    if not vault_files.delete(a.name):
        hint = " (it is a text key: maxxing keys delete)" if vault.get(a.name) is not None else ""
        print(f"{a.name}: no such file{hint}", file=sys.stderr)
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
            if vault_files.exists(a.name):
                print(f"{a.name}: is a secret file, not a text key: maxxing keys get-file {a.name} -o FILE",
                      file=sys.stderr)
            else:
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
        if vault_files.exists(a.name):
            print(f"{a.name}: is a secret file, not a text key: maxxing keys delete-file {a.name}", file=sys.stderr)
        else:
            print(f"{a.name}: no such key", file=sys.stderr)
        return 1
    print(f"{a.name} deleted")
    return 0


cli.register("keys", "the Keys vault: list, get, set (value from stdin), delete, put-file, get-file, delete-file", _configure, _handler)
