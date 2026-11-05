"""`maxxing proxy`: the second listen address for a reverse proxy that runs in a container (proxylisten.py)."""
from __future__ import annotations

import json
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="action", required=True)
    on = sub.add_parser("on", help="open the proxy address (default 172.17.0.1:8790) "
                                   "and write the Traefik block")
    on.add_argument("address", nargs="?", default="", help="HOST:PORT, a private address the containers reach")
    on.add_argument("--domain", default="", help="domain of the UI (default: the host of public_url)")
    sub.add_parser("off", help="close the proxy address")
    st = sub.add_parser("status", help="proxy address, listening or not")
    st.add_argument("--json", action="store_true")


def _handler(a) -> int:
    from . import config, proxylisten
    if a.action == "on":
        try:
            r = proxylisten.enable(a.address, a.domain)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        print(f"proxy address {r['host']}:{r['port']} for https://{r['domain']}"
              + (" (ufw: container networks allowed to it)" if r["ufw"] else ""))
        print(f"Traefik block (holds the secret): {r['file']} - copy it into Traefik's dynamic configuration folder")
        print("then: systemctl restart claude-maxxing")
        return 0
    if a.action == "off":
        r = proxylisten.disable()
        print(f"proxy address {r['was']} closed" if r["was"] else "no proxy address was set")
        print("then: systemctl restart claude-maxxing (and remove the harness-maxxing block from Traefik)")
        return 0
    cfg = config.load_config()
    addr = proxylisten.configured(cfg)
    info = {"address": f"{addr[0]}:{addr[1]}" if addr else "", "listening": bool(addr) and proxylisten.listening(*addr),
            "ufw_blocks": bool(addr) and proxylisten.ufw_missing(*addr)}
    if a.json:
        print(json.dumps(info))
    elif not addr:
        print("off (maxxing proxy on opens an address for a reverse proxy in a container)")
    else:
        print(f"{info['address']}: {'listening' if info['listening'] else 'NOT listening (restart the service)'}")
        if info["ufw_blocks"]:
            print("ufw is active without a rule for it: the proxy cannot reach it (run: maxxing proxy on)")
    return 0


cli.register("proxy", "second listen address for a reverse proxy in a container (Traefik in Docker): on, off, status",
             _configure, _handler)
