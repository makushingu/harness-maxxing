"""Test doubles for the connectivity domain (Telegram gateway + GitHub backup).

- FakeTelegram: a local Bot API server (stdlib ThreadingHTTPServer) - long polling, forum topics,
  files, recorded calls. Never talks to the real Telegram.
- FakeGitHub: a local REST API for /user, /repos, /user/repos, /orgs/{org}/repos backed by bare git
  repositories on disk (used as `file://` remotes).
- FakeService / FakeWorkspace: stand-ins for maxxing.sessions.service and maxxing.workspace
  (installed in sys.modules), following docs/dev/INTERNALS.md.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import threading
import time
import types
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import pytest

from maxxing import config

TG_TOKEN = "123456789:AAEhBP0av28tT3st-T0ken_ForMaxxingTests12"
GH_TOKEN = "test-github-token-not-a-real-one"


# =============================================================================================
# Generic local HTTP server
# =============================================================================================
class _Server:
    def __init__(self, handler: Callable[[str, str, dict, bytes], tuple[int, Any, str]]):
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _do(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                status, payload, ctype = handler(self.command, self.path, dict(self.headers), body)
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = _do

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        _ = outer

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


# =============================================================================================
# Fake Telegram
# =============================================================================================
class FakeTelegram:
    """Minimal Bot API: records every call, serves queued updates via long polling."""

    def __init__(self, token: str = TG_TOKEN):
        self.token = token
        self.calls: list[tuple[str, dict]] = []
        self.updates: list[dict] = []
        self.next_update = 1
        self.next_msg = 100
        self.next_thread = 10
        self.topics_enabled = True
        self.topics: dict[int, str] = {}                      # live forum topics (thread id -> name)
        self.webhook = ""
        self.files: dict[str, tuple[str, bytes]] = {}
        self.fail: dict[str, tuple[int, str]] = {}            # method -> (code, description)
        self.fail_once: dict[str, tuple[int, str]] = {}       # same, consumed by the next call
        self.cond = threading.Condition()
        self.server = _Server(self._handle)
        self.url = self.server.url

    # ---- helpers for tests -----------------------------------------------------------------
    def push(self, update: dict) -> None:
        with self.cond:
            update = {"update_id": self.next_update, **update}
            self.next_update += 1
            self.updates.append(update)
            self.cond.notify_all()

    def message(self, text: str = "", chat_id: int = 555, user_id: int = 555, thread: int | None = None,
                **extra: Any) -> None:
        self.next_msg += 1
        msg: dict[str, Any] = {"message_id": self.next_msg, "date": int(time.time()),
                               "chat": {"id": chat_id, "type": "private", "first_name": "Ada"},
                               "from": {"id": user_id, "is_bot": False, "first_name": "Ada"}}
        if text:
            msg["text"] = text
        if thread is not None:
            msg["message_thread_id"] = thread
            msg["is_topic_message"] = True
        msg.update(extra)
        self.push({"message": msg})

    def callback(self, data: str, chat_id: int = 555, user_id: int = 555, thread: int | None = None,
                 message_id: int = 1) -> None:
        m: dict[str, Any] = {"message_id": message_id, "chat": {"id": chat_id, "type": "private"}}
        if thread is not None:
            m["message_thread_id"] = thread
            m["is_topic_message"] = True
        self.push({"callback_query": {"id": f"cq{self.next_update}", "data": data,
                                      "from": {"id": user_id}, "message": m}})

    def user_thread(self, name: str, chat_id: int = 555) -> int:
        """The user creates a thread in the bot chat (Telegram sends a forum_topic_created message)."""
        with self.cond:
            self.next_thread += 1
            tid = self.next_thread
            self.topics[tid] = name
        self.message("", chat_id=chat_id, thread=tid, forum_topic_created={"name": name, "icon_color": 1})
        return tid

    def add_file(self, file_id: str, data: bytes, path: str = "photos/file_1.jpg") -> None:
        self.files[file_id] = (path, data)

    def sent(self, method: str = "sendMessage") -> list[dict]:
        return [p for m, p in list(self.calls) if m == method]

    def close(self) -> None:
        self.server.close()

    # ---- server ----------------------------------------------------------------------------
    def _ok(self, result: Any) -> tuple[int, Any, str]:
        return 200, {"ok": True, "result": result}, "application/json"

    def _err(self, code: int, desc: str) -> tuple[int, Any, str]:
        return code, {"ok": False, "error_code": code, "description": desc}, "application/json"

    def _handle(self, verb: str, path: str, headers: dict, body: bytes) -> tuple[int, Any, str]:
        m = re.match(r"^/file/bot([^/]+)/(.+)$", path)
        if m:
            for fp, data in self.files.values():
                if fp == m.group(2) and m.group(1) == self.token:
                    return 200, data, "application/octet-stream"
            return 404, b"not found", "text/plain"
        m = re.match(r"^/bot([^/]+)/(\w+)$", path)
        if not m:
            return self._err(404, "Not Found")
        tok, method = m.group(1), m.group(2)
        params = json.loads(body or b"{}") if body else {}
        if tok != self.token:
            return self._err(401, "Unauthorized")
        if method != "getUpdates":
            self.calls.append((method, params))
        if method in self.fail:
            return self._err(*self.fail[method])
        if method in self.fail_once:
            return self._err(*self.fail_once.pop(method))
        if method == "getMe":
            return self._ok({"id": 123456789, "is_bot": True, "first_name": "Maxxing Test",
                             "username": "maxxing_test_bot", "has_topics_enabled": self.topics_enabled})
        if method == "getWebhookInfo":
            return self._ok({"url": self.webhook, "pending_update_count": 0})
        if method == "deleteWebhook":
            self.webhook = ""
            return self._ok(True)
        if method == "getUpdates":
            off = int(params.get("offset") or 0)
            deadline = time.time() + min(float(params.get("timeout") or 0), 1.0)
            with self.cond:
                while True:
                    ready = [u for u in self.updates if u["update_id"] >= off]
                    if ready or time.time() >= deadline:
                        break
                    self.cond.wait(max(0.01, deadline - time.time()))
                self.updates = [u for u in self.updates if u["update_id"] >= off]
            return self._ok(ready)
        if method == "createForumTopic":
            if not self.topics_enabled:
                return self._err(400, "Bad Request: the chat is not a forum")
            self.next_thread += 1
            self.topics[self.next_thread] = params.get("name") or ""
            return self._ok({"message_thread_id": self.next_thread, "name": params.get("name")})
        gone = self._err(400, "Bad Request: message thread not found")
        tid = params.get("message_thread_id")
        if method in ("editForumTopic", "deleteForumTopic") and tid not in self.topics:
            return gone
        if method == "editForumTopic":
            if params.get("name") == self.topics[tid]:
                return self._err(400, "Bad Request: TOPIC_NOT_MODIFIED")
            self.topics[tid] = params.get("name") or ""
            return self._ok(True)
        if method == "deleteForumTopic":
            self.topics.pop(tid, None)
            return self._ok(True)
        if method in ("sendMessage", "sendChatAction") and tid is not None and self.topics and tid not in self.topics:
            return gone
        if method == "sendMessage":
            self.next_msg += 1
            return self._ok({"message_id": self.next_msg, "chat": {"id": params.get("chat_id")},
                             "text": params.get("text")})
        if method == "getFile":
            f = self.files.get(params.get("file_id"))
            if not f:
                return self._err(400, "Bad Request: invalid file_id")
            return self._ok({"file_id": params["file_id"], "file_path": f[0], "file_size": len(f[1])})
        return self._ok(True)


# =============================================================================================
# Fake GitHub
# =============================================================================================
class FakeGitHub:
    """REST API double backed by bare repositories under `root/<owner>/<name>.git`."""

    def __init__(self, root: Path, token: str = GH_TOKEN, login: str = "alice"):
        self.root = root
        self.token = token
        self.login = login
        self.repos: dict[str, dict] = {}
        self.calls: list[tuple[str, str, dict]] = []
        self.server = _Server(self._handle)
        self.url = self.server.url

    def add_repo(self, full: str, private: bool = True, push: bool = True) -> Path:
        bare = self.root / f"{full}.git"
        bare.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        self.repos[full] = {"full_name": full, "private": private, "permissions": {"push": push}}
        return bare

    def close(self) -> None:
        self.server.close()

    def _handle(self, verb: str, path: str, headers: dict, body: bytes) -> tuple[int, Any, str]:
        data = json.loads(body) if body else {}
        self.calls.append((verb, path, data))
        auth = {k.lower(): v for k, v in headers.items()}.get("authorization", "")
        if auth != f"Bearer {self.token}":
            return 401, {"message": "Bad credentials"}, "application/json"
        if verb == "GET" and path == "/user":
            return 200, {"login": self.login}, "application/json"
        m = re.match(r"^/repos/([^/]+/[^/]+)$", path)
        if verb == "GET" and m:
            r = self.repos.get(m.group(1))
            return (200, r, "application/json") if r else (404, {"message": "Not Found"}, "application/json")
        m = re.match(r"^/(?:user|orgs/([^/]+))/repos$", path)
        if verb == "POST" and m:
            owner = m.group(1) or self.login
            full = f"{owner}/{data['name']}"
            if full in self.repos:
                return 422, {"message": "name already exists on this account"}, "application/json"
            self.add_repo(full, private=bool(data.get("private")))
            return 201, self.repos[full], "application/json"
        return 404, {"message": "Not Found"}, "application/json"


# =============================================================================================
# Fake domain modules
# =============================================================================================
class FakeService(types.ModuleType):
    """maxxing.sessions.service double (INTERNALS.md signatures)."""

    def __init__(self) -> None:
        super().__init__("maxxing.sessions.service")
        self.sessions: dict[str, dict] = {}
        self.sent: list[dict] = []
        self.auto_titles: list[str] = []          # sessions created with auto_title=True
        self.replies: dict[str, str] = {}
        self.events: dict[str, list[dict]] = {}
        self.callbacks: list[Callable] = []
        self.stopped: list[str] = []
        self.queues: dict[str, list[dict]] = {}          # sid -> waiting items {text, source, refs}
        self.current: dict[str, dict] = {}               # sid -> item of the running turn
        self.unreadable: set[str] = set()                 # sessions whose file cannot be read just now

    def create_session(self, path: str, message: str | None = None, title: str | None = None,
                       model: str | None = None, attachments: list | None = None, source: str = "web",
                       notify: bool = False, cron: bool = False, env: dict | None = None,
                       timeout_s: int | None = None, auto_title: bool = False, plan_mode: bool = False) -> dict:
        sid = str(uuid.uuid4())
        now = time.time()
        self.sessions[sid] = {"id": sid, "title": title or "New session", "path": path, "state": "idle",
                              "queue": 0, "created": now, "updated": now, "turns": 0, "cost_usd": 0.0,
                              "model": model or "", "real_model": None, "context_tokens": None,
                              "archived": False, "notify": notify, "source": source, "unread": False,
                              "last_text": "", "error": None, "cron": cron, "plan_mode": plan_mode}
        if auto_title:
            self.auto_titles.append(sid)
        return dict(self.sessions[sid])

    def get_session(self, sid: str) -> dict | None:
        s = self.sessions.get(sid) if sid not in self.unreadable else None
        return dict(s) if s else None

    def list_sessions(self, path: str | None = None, archived: bool | None = None) -> list[dict]:
        out = [dict(s) for s in self.sessions.values() if s["id"] not in self.unreadable
               and (path is None or s["path"] == path) and (archived is None or s["archived"] == archived)]
        return sorted(out, key=lambda s: s["updated"], reverse=True)

    def send_message(self, sid: str, text: str, attachments: list | None = None, source: str = "web",
                     ref: str | None = None) -> dict:
        s = self.sessions[sid]
        queued = s["state"] == "running"
        item = {"text": text, "source": source, "kind": "user", "refs": [ref] if ref else []}
        if queued:
            self.queues.setdefault(sid, []).append(item)
        else:
            self.current[sid] = item
        s["state"] = "running"
        s["updated"] = time.time()
        self.sent.append({"sid": sid, "text": text, "attachments": attachments, "source": source, "ref": ref})
        return {"queued": queued, "session": dict(s)}

    def live_refs(self, sid: str) -> set:
        out = {r for x in self.queues.get(sid, []) for r in x["refs"]}
        if self.sessions[sid]["state"] == "running" and sid in self.current:
            out |= set(self.current[sid]["refs"])
        return out

    def session_exists(self, sid: str) -> bool:
        return sid in self.sessions

    def steer(self, sid: str) -> None:
        """The waiting messages become one (their refs merged); the running turn ends interrupted (finish it)."""
        q = self.queues.get(sid, [])
        if q:
            self.queues[sid] = [{"text": "\n\n".join(x["text"] for x in q), "source": q[-1]["source"],
                                 "kind": "user", "refs": [r for x in q for r in x["refs"]]}]

    def update_session(self, sid: str, **fields: Any) -> dict:
        self.sessions[sid].update(fields)
        return dict(self.sessions[sid])

    def stop(self, sid: str) -> None:
        self.stopped.append(sid)
        self.sessions[sid]["state"] = "idle"
        self.queues.pop(sid, None)
        self.current.pop(sid, None)

    def last_assistant_text(self, sid: str) -> str:
        return self.replies.get(sid, "")

    def last_user_message(self, sid: str) -> dict | None:
        mine = [m for m in self.sent if m["sid"] == sid]
        return {"type": "user", "text": mine[-1]["text"], "source": mine[-1]["source"]} if mine else None

    def read_events(self, sid: str, offset: int = 0) -> tuple[list[dict], int]:
        ev = self.events.get(sid, [])
        return ev[offset:], len(ev)

    def on_turn_end(self, cb: Callable) -> None:
        self.callbacks.append(cb)

    def finish(self, sid: str, text: str = "", error: str | None = None, kind: str = "user") -> None:
        """Simulate the end of a turn (call on the event loop): the running item ends, the next queued one runs.
        kind="compact": a summary turn (the running message stays queued behind it)."""
        s = self.sessions[sid]
        self.replies[sid] = text
        if kind != "user":
            item = {"text": "summary", "source": "system", "kind": kind, "refs": []}
            if sid in self.current:
                self.queues.setdefault(sid, []).insert(0, self.current.pop(sid))
        else:
            item = self.current.pop(sid, None) or {"source": "web", "kind": "user", "refs": []}
        q = self.queues.get(sid) or []
        if q and not error:
            self.current[sid] = q.pop(0)
        state = "error" if error else ("running" if sid in self.current else "idle")
        s.update(state=state, error=error, last_text=text[:200], turns=s["turns"] + 1)
        last = {"kind": item["kind"], "source": item["source"], "refs": list(item["refs"])}
        for cb in self.callbacks:
            cb({**s, "last_turn": last}, {"ok": not error})


class FakeWorkspace(types.ModuleType):
    """maxxing.workspace double rooted at `root`."""

    def __init__(self, root: Path, topics: list[tuple[str, str]]):
        super().__init__("maxxing.workspace")
        self.root = root
        self.topics = list(topics)
        self.callbacks: list[Callable] = []
        for p, t in self.topics:
            (root / "projects" / p / "topics" / t).mkdir(parents=True, exist_ok=True)

    def topic_dir(self, path: str) -> Path:
        p = (self.root / path).resolve()
        if p != self.root.resolve() and self.root.resolve() not in p.parents:
            raise ValueError("bad path")
        return p

    def list_topics(self) -> list[dict]:
        return [{"path": f"projects/{p}/topics/{t}", "project": p, "name": t, "description": ""}
                for p, t in self.topics]

    def on_change(self, cb: Callable) -> None:
        self.callbacks.append(cb)

    def add_topic(self, project: str, name: str) -> None:
        self.topics.append((project, name))
        (self.root / "projects" / project / "topics" / name).mkdir(parents=True, exist_ok=True)
        for cb in self.callbacks:
            cb()


# =============================================================================================
# Fixtures
# =============================================================================================
@pytest.fixture
def mx_state(tmp_path, monkeypatch):
    """Isolated state dir + workspace + crontab file; every external URL points to nowhere."""
    state = tmp_path / "state"
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(config, "STATE", state)
    monkeypatch.setenv("MAXXING_STATE", str(state))
    monkeypatch.setenv("MAXXING_CRONTAB_FILE", str(tmp_path / "crontab"))
    monkeypatch.setenv("MAXXING_TELEGRAM_API", "http://127.0.0.1:9")      # nothing listens there
    monkeypatch.setenv("MAXXING_GITHUB_API", "http://127.0.0.1:9")
    monkeypatch.setenv("MAXXING_GITHUB_GIT", f"file://{tmp_path / 'nowhere'}")
    monkeypatch.setenv("MAXXING_TELEGRAM_POLL", "1")
    config.update_config(workspace=str(ws))
    return tmp_path


def bare_app(router) -> Any:
    """A FastAPI app with one router, auth bypassed and the product's JSON error shape."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse

    from maxxing import security
    app = FastAPI()

    @app.exception_handler(HTTPException)
    async def _err(request, exc: HTTPException):
        d = exc.detail
        return JSONResponse(d if isinstance(d, dict) else {"error": "error", "message": str(d)},
                            status_code=exc.status_code)

    app.include_router(router)
    app.dependency_overrides[security.require_auth] = lambda: None
    return app


async def wait_for(pred: Callable[[], Any], timeout: float = 15.0, what: str = "condition") -> Any:
    """Poll `pred` on the event loop until it returns a truthy value."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = pred()
        if v:
            return v
        await asyncio.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")
