"""`maxxing` command line. Sub-commands are added by each domain (see docs/dev/PLAN.md).

  maxxing serve                 run the web server (systemd service)
  maxxing setup-link            print the one-time setup link, valid 1 h (first run / password lost)
  maxxing password              set a new UI password interactively
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from . import __version__, config


def cmd_serve(a) -> int:
    import uvicorn

    from . import security
    from .app import create_app
    cfg = config.load_config()
    from . import logs
    logs.setup()
    if not security.password_is_set():           # the link itself never goes to the journal (readable by admins)
        print("First run - run `maxxing setup-link` on the server for the one-time setup link", flush=True)
    port = a.port or cfg["port"]
    os.environ["MAXXING_LISTEN_PORT"] = str(port)   # local clients of this server (pcbridge) follow --port
    uvicorn.run(create_app(), host=a.host or cfg["bind"], port=port,
                proxy_headers=True, forwarded_allow_ips="127.0.0.1", log_level="warning",
                timeout_graceful_shutdown=3)   # live (SSE) connections never end by themselves
    return 0


def _base(cfg: dict) -> str:
    return (cfg.get("public_url") or f"http://{cfg['bind']}:{cfg['port']}").rstrip("/")


def cmd_setup_link(a) -> int:
    from . import security
    cfg = config.load_config()
    if security.password_is_set() and not a.reset:
        print("A password is already set. Use `maxxing password` (or --reset to start the setup again).")
        return 1
    if a.reset:
        config.set_secret("password_hash", None)
        security.clear_setup_token()
    print(f"{_base(cfg)}/setup?token={security.ensure_setup_token()}")
    if sys.stdout.isatty():
        print(f"(valid {security.SETUP_TOKEN_TTL // 60} min - run this command again for a fresh link)", file=sys.stderr)
    return 0


def cmd_password(a) -> int:
    pw = getpass.getpass("New UI password: ")
    from . import security
    if len(pw) < security.MIN_PASSWORD or pw != getpass.getpass("Repeat: "):
        print(f"Passwords differ or are shorter than {security.MIN_PASSWORD} characters.", file=sys.stderr)
        return 1
    security.set_password(pw)
    print("Password changed - every browser has to sign in again.")
    return 0


COMMANDS = {}   # name -> (help, configure(parser), handler) - domains register here


def register(name: str, help: str, configure, handler) -> None:
    COMMANDS[name] = (help, configure, handler)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="maxxing", description="Harness Maxxing " + __version__)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the web server")
    s.add_argument("--host"); s.add_argument("--port", type=int); s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("setup-link", help="print a one-time setup link")
    s.add_argument("--reset", action="store_true", help="forget the password and start the setup again")
    s.set_defaults(fn=cmd_setup_link)
    sub.add_parser("password", help="set a new UI password").set_defaults(fn=cmd_password)
    _load_plugins()
    args = sys.argv[1:] if argv is None else argv
    chosen = next((x for x in args if not x.startswith("-")), None)
    for name, (hlp, configure, handler) in COMMANDS.items():
        s = sub.add_parser(name, help=hlp)
        if name == chosen:                          # only the command being run builds its options
            configure(s)
        s.set_defaults(fn=handler)
    a = p.parse_args(argv)
    return a.fn(a) or 0


def _load_plugins() -> None:
    """Domain modules that add sub-commands (import errors must not break the CLI)."""
    import importlib
    for mod in ("maxxing.commands",):
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError:
            pass


if __name__ == "__main__":
    sys.exit(main())
