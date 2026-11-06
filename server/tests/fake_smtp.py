"""A tiny SMTP server for the tests (plain text, AUTH PLAIN/LOGIN): keeps every message it receives.

    srv = FakeSMTP(user="me@example.com", password="pw").start()
    ... srv.port, srv.messages -> [{"from", "to", "data"}]
    srv.stop()
"""
from __future__ import annotations

import base64
import socket
import socketserver
import threading


class FakeSMTP:
    def __init__(self, user: str = "", password: str = "", refuse: set[str] | None = None):
        self.user, self.password = user, password
        self.refuse = {a.lower() for a in refuse or ()}
        self.messages: list[dict] = []
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def send(self, line: str) -> None:
                self.wfile.write((line + "\r\n").encode())

            def handle(self) -> None:
                self.send("220 fake ESMTP")
                authed, mail_from, rcpts = not outer.user, "", []
                while True:
                    raw = self.rfile.readline()
                    if not raw:
                        return
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    cmd = line.split(" ", 1)[0].upper()
                    arg = line[len(cmd):].strip()
                    if cmd in ("EHLO", "HELO"):
                        self.wfile.write(b"250-fake\r\n250-AUTH PLAIN LOGIN\r\n250 8BITMIME\r\n")
                    elif cmd == "AUTH":
                        parts = arg.split()
                        if parts[0].upper() == "PLAIN":
                            tok = parts[1] if len(parts) > 1 else None
                            if tok is None:
                                self.send("334 ")
                                tok = self.rfile.readline().decode().strip()
                            _, u, p = base64.b64decode(tok).decode().split("\0")
                        else:
                            if len(parts) > 1:
                                u = base64.b64decode(parts[1]).decode()
                            else:
                                self.send("334 VXNlcm5hbWU6")
                                u = base64.b64decode(self.rfile.readline().strip()).decode()
                            self.send("334 UGFzc3dvcmQ6")
                            p = base64.b64decode(self.rfile.readline().strip()).decode()
                        if u == outer.user and p == outer.password:
                            authed = True
                            self.send("235 ok")
                        else:
                            self.send("535 bad credentials")
                    elif cmd == "MAIL":
                        if not authed:
                            self.send("530 auth first")
                            continue
                        mail_from, rcpts = arg.split(":", 1)[1].strip().strip("<>").split(">")[0], []
                        self.send("250 ok")
                    elif cmd == "RCPT":
                        to = arg.split(":", 1)[1].strip().strip("<>").split(">")[0]
                        if to.lower() in outer.refuse:
                            self.send("550 no such user")
                        else:
                            rcpts.append(to)
                            self.send("250 ok")
                    elif cmd == "DATA":
                        self.send("354 go")
                        buf = []
                        while True:
                            ln = self.rfile.readline()
                            if ln in (b".\r\n", b".\n", b""):
                                break
                            buf.append(ln[1:] if ln.startswith(b"..") else ln)
                        outer.messages.append({"from": mail_from, "to": rcpts, "data": b"".join(buf)})
                        self.send("250 queued")
                    elif cmd == "RSET":
                        mail_from, rcpts = "", []
                        self.send("250 ok")
                    elif cmd == "NOOP":
                        self.send("250 ok")
                    elif cmd == "QUIT":
                        self.send("221 bye")
                        return
                    else:
                        self.send("502 unknown")

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._srv = Server(("127.0.0.1", 0), Handler)
        self.port = self._srv.server_address[1]

    def start(self) -> "FakeSMTP":
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self._srv.shutdown()
        self._srv.server_close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
