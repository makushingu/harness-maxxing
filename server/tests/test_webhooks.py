"""Settings -> Automate -> Webhooks and Events (webhooks.py, api/webhooks.py, api/hooks.py, cmd_webhooks.py)."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from conftest import wait_for
from maxxing import config, feed, feedhooks, webhooks


def _tok(h: dict) -> str:
    return h["url"].rsplit("/", 1)[-1]


def _shell(name: str, command: str, **trigger) -> dict:
    return {"name": name, "trigger": {"kind": "in", **trigger}, "action": {"kind": "shell", "command": command}}


def _rec(hid: str, cid: str) -> dict | None:
    return next((r for r in webhooks._records(hid) if r["id"] == cid), None)


def _done(hid: str, cid: str, timeout: float = 20) -> dict:
    return wait_for(lambda: (r := _rec(hid, cid)) and r["status"] in ("ok", "failed") and r, timeout)


def test_a_call_runs_the_script_with_the_request_as_data_never_as_code(client, mx):
    out, pwned = mx["tmp"] / "seen", mx["tmp"] / "pwned"
    cmd = f'cat > {out}; echo >> {out}; echo "$MAXXING_WEBHOOK_EVENT|$MAXXING_WEBHOOK_METHOD|$MAXXING_WEBHOOK_QUERY" >> {out}'
    h = client.post("/api/webhooks", json=_shell("deploy", cmd)).json()
    assert h["url"].startswith("/api/hooks/") or "/api/hooks/" in h["url"]
    evil = {"event": "push", "title": f"$(touch {pwned})", "x": f"; touch {pwned}; `touch {pwned}`"}
    r = client.post(f"/api/hooks/{_tok(h)}?a=1", json=evil)
    assert r.status_code == 202 and r.json()["ok"]
    rec = _done(h["id"], r.json()["call"])
    assert rec["status"] == "ok", rec
    text = out.read_text()
    assert json.loads(text.splitlines()[0]) == evil
    assert text.splitlines()[1] == 'push|POST|{"a": "1"}'
    assert not pwned.exists()


def test_the_listing_never_shows_tokens_or_secrets(client):
    h = client.post("/api/webhooks", json={**_shell("s", "true", source="stripe"), "secret": "whsec_abc"}).json()
    body = client.get("/api/webhooks").text
    assert "whsec_abc" not in body and h["has_secret"] is True
    store = config.load_secrets()["webhooks"][h["id"]]
    assert store["secret"] == "whsec_abc" and store["token"] in h["url"]


def test_signed_sources_refuse_until_the_secret_is_set_then_check_it(client):
    h = client.post("/api/webhooks", json=_shell("stripe", "true", source="stripe")).json()
    body = json.dumps({"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {}}}).encode()
    r = client.post(f"/api/hooks/{_tok(h)}", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 401 and r.json()["error"] == "secret_required"
    client.post(f"/api/webhooks/{h['id']}/secret", json={"secret": "whsec_k"})
    bad = client.post(f"/api/hooks/{_tok(h)}", content=body, headers={"Stripe-Signature": "t=1,v1=00"})
    assert bad.status_code == 401
    t = str(int(time.time()))
    sig = hmac.new(b"whsec_k", f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    ok = client.post(f"/api/hooks/{_tok(h)}", content=body,
                     headers={"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"})
    assert ok.status_code == 202
    rec = _done(h["id"], ok.json()["call"])
    assert rec["event"] == "checkout.session.completed" and rec["summary"].startswith("Sale")


def test_reply_wait_returns_the_output_of_the_script(client):
    h = client.post("/api/webhooks", json=_shell("echo", 'printf \'{"got": %s}\' "$(cat)"', reply="wait")).json()
    r = client.post(f"/api/hooks/{_tok(h)}", json={"n": 2})
    assert r.status_code == 200 and r.json() == {"got": {"n": 2}}


def test_reply_wait_sends_the_response_file_with_its_type(client):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    h = client.post("/api/webhooks", json=_shell("img", "printf '\\211PNG\\r\\n\\032\\n' > $MAXXING_RESPONSE_FILE; "
                                                       "head -c 20 /dev/zero >> $MAXXING_RESPONSE_FILE; echo ignored",
                                                 reply="wait")).json()
    r = client.post(f"/api/hooks/{_tok(h)}", json={})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == png


def test_reply_wait_failure_and_timeout(client, monkeypatch):
    h = client.post("/api/webhooks", json=_shell("fail", "echo boom >&2; exit 3", reply="wait")).json()
    r = client.post(f"/api/hooks/{_tok(h)}", json={})
    assert r.status_code == 502 and r.json()["exit"] == 3
    monkeypatch.setattr(webhooks, "WAIT_S", 0.5)
    h = client.post("/api/webhooks", json=_shell("slow", "sleep 3", reply="wait")).json()
    r = client.post(f"/api/hooks/{_tok(h)}", json={})
    assert r.status_code == 504
    _done(h["id"], r.json()["call"])


def test_phone_hooks_take_get_files_and_a_key(client, mx):
    out = mx["tmp"] / "seen-files"
    h = client.post("/api/webhooks", json=_shell("photo", f'ls "$MAXXING_WEBHOOK_FILES" > {out}; echo "$MAXXING_WEBHOOK_QUERY"',
                                                 source="phone", reply="wait")).json()
    assert h["trigger"]["methods"] == ["GET", "POST"] and h["trigger"]["max_mb"] == webhooks.PHONE_MB
    r = client.get(f"/api/hooks/{_tok(h)}?city=Paris")
    assert r.status_code == 200 and "Paris" in r.text
    r = client.post(f"/api/hooks/{_tok(h)}", files={"photo": ("../../evil name.jpg", io.BytesIO(b"\xff\xd8\xffdata"), "image/jpeg")},
                    data={"note": "hi"})
    assert r.status_code == 200, r.text
    assert out.read_text().strip() == "evil_name.jpg"
    rec = webhooks.calls(h["id"])[0]
    assert webhooks.call(h["id"], rec["id"])["request"]["files"][0]["size"] == 7
    client.post(f"/api/webhooks/{h['id']}/secret", json={"secret": "k3y"})
    assert client.get(f"/api/hooks/{_tok(h)}").status_code == 401
    assert client.get(f"/api/hooks/{_tok(h)}", headers={"Authorization": "Bearer k3y"}).status_code == 200
    r = client.get(f"/api/hooks/{_tok(h)}?key=k3y&city=Lyon")       # the key in the URL: checked, then dropped
    assert r.status_code == 200 and "Lyon" in r.text and "k3y" not in r.text
    detail = client.get(f"/api/webhooks/{h['id']}/calls/{webhooks.calls(h['id'])[0]['id']}").json()
    assert detail["request"]["query"] == {"city": "Lyon"} and "k3y" not in json.dumps(detail)


def test_method_size_disabled_and_unknown(client):
    h = client.post("/api/webhooks", json=_shell("g", "true")).json()
    assert client.get(f"/api/hooks/{_tok(h)}").status_code == 405
    big = b"x" * (webhooks.MB + 10)
    assert client.post(f"/api/hooks/{_tok(h)}", content=big).status_code == 413
    client.patch(f"/api/webhooks/{h['id']}", json={"enabled": False})
    r = client.post(f"/api/hooks/{_tok(h)}", json={})
    assert r.status_code == 503 and r.json()["error"] == "disabled"
    assert client.post("/api/hooks/nope", json={}).status_code == 404


def test_filter_ignores_other_events(client):
    h = client.post("/api/webhooks", json=_shell("gh", "true", source="generic",
                                                 filter={"events": ["push"]})).json()
    r = client.post(f"/api/hooks/{_tok(h)}", json={"event": "star"})
    assert r.json()["ignored"] is True and webhooks.calls(h["id"])[0]["status"] == "ignored"
    r = client.post(f"/api/hooks/{_tok(h)}", json={"event": "push"})
    assert r.status_code == 202


def test_github_branch_filter():
    assert webhooks._passes({"branch": "main"}, "push", "main")
    assert not webhooks._passes({"branch": "main"}, "push", "dev")
    assert not webhooks._passes({"branch": "main"}, "push", "")          # a tag
    assert webhooks._passes({"branch": "main"}, "ping", "")
    assert webhooks.event_name("github", {"ref": "refs/heads/feat/x"}, {"X-GitHub-Event": "push"}) == ("push", "feat/x")


def test_a_full_queue_answers_503(client, mx):
    h = client.post("/api/webhooks", json={**_shell("q", "sleep 2"), "queue": {"parallel": 1, "max_waiting": 1}}).json()
    first = client.post(f"/api/hooks/{_tok(h)}", json={"n": 1})
    second = client.post(f"/api/hooks/{_tok(h)}", json={"n": 2})
    third = client.post(f"/api/hooks/{_tok(h)}", json={"n": 3})
    assert [first.status_code, second.status_code, third.status_code] == [202, 202, 503]
    assert third.headers["retry-after"] == "30"
    _done(h["id"], second.json()["call"], 30)
    assert _rec(h["id"], first.json()["call"])["status"] == "ok"


def test_store_keeps_rows_and_exports_csv(client):
    h = client.post("/api/webhooks", json={"name": "sales", "trigger": {"kind": "in"},
                                           "action": {"kind": "store", "fields": {"amount": "data.amount"}, "keep": 2}}).json()
    for n in (1, 2, 3):
        _done(h["id"], client.post(f"/api/hooks/{_tok(h)}", json={"data": {"amount": n}, "who": "a"}).json()["call"])
    d = client.get(f"/api/webhooks/{h['id']}/data").json()
    assert [r["fields"]["amount"] for r in d["rows"]] == [2, 3] and d["stats"]["rows"] == 2
    csv = client.get(f"/api/webhooks/{h['id']}/data?format=csv")
    assert csv.headers["content-type"].startswith("text/csv") and csv.text.splitlines()[0] == "id,at,amount"
    assert client.get("/api/webhooks").json()["hooks"][0]["data"]["today"] == 2


class _Sink(BaseHTTPRequestHandler):
    got: list = []
    fail_first = 0

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        _Sink.got.append((dict(self.headers), body))
        if _Sink.fail_first > 0:
            _Sink.fail_first -= 1
            self.send_response(500)
            self.end_headers()
            return
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"echo": true}')

    def log_message(self, *a):
        pass


@pytest.fixture
def sink():
    _Sink.got, _Sink.fail_first = [], 0
    srv = HTTPServer(("127.0.0.1", 0), _Sink)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/in"
    srv.shutdown()


def test_call_relays_signs_and_answers_the_caller(client, sink, monkeypatch):
    monkeypatch.setattr(webhooks.time, "sleep", lambda s: None)
    _Sink.fail_first = 1
    h = client.post("/api/webhooks", json={"name": "relay", "trigger": {"kind": "in", "reply": "wait"},
                                           "action": {"kind": "call", "url": sink, "sign": True}}).json()
    r = client.post(f"/api/hooks/{_tok(h)}", json={"a": 1})
    assert r.status_code == 201 and r.json() == {"echo": True}
    headers, body = _Sink.got[-1]
    assert json.loads(body) == {"a": 1} and len(_Sink.got) == 2
    key = webhooks.sign_secret(h["id"]).encode()
    assert headers["X-Harness-Signature"] == "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()
    assert webhooks.calls(h["id"])[0]["attempts"] == 2


def test_call_template_escapes_json_and_reads_vault_keys(client, sink, monkeypatch):
    from maxxing import vault
    vault.put("SINK_TOKEN", "s3cr3t")
    h = client.post("/api/webhooks", json={"name": "tpl", "trigger": {"kind": "in"},
                                           "action": {"kind": "call", "url": sink, "headers": {"Authorization": "Bearer {{key:SINK_TOKEN}}"},
                                                      "body": '{"content": "{{title}} / {{n}} / {{payload.n}}"}'}}).json()
    rec = _done(h["id"], client.post(f"/api/hooks/{_tok(h)}", json={"title": 'say "hi"\n', "n": 3}).json()["call"])
    assert rec["status"] == "ok" and rec["http"] == 201
    headers, body = _Sink.got[-1]
    assert json.loads(body) == {"content": 'say "hi"\n / 3 / 3'} and headers["Authorization"] == "Bearer s3cr3t"
    assert "s3cr3t" not in json.dumps(webhooks.call(h["id"], rec["id"]))


def test_notify_uses_the_feed_parsers(client):
    h = client.post("/api/webhooks", json={"name": "shop", "trigger": {"kind": "in", "source": "generic"},
                                           "action": {"kind": "notify"}}).json()
    _done(h["id"], client.post(f"/api/hooks/{_tok(h)}", json={"title": "Hello", "level": "warning"}).json()["call"])
    ev = feed.list_events(source="shop")["events"][0]
    assert ev["title"] == "Hello" and ev["level"] == "warning"


def test_feed_events_start_event_hooks_without_loops(mx):
    webhooks.create({"name": "fwd", "trigger": {"kind": "event", "on": "feed", "levels": ["error"]},
                     "action": {"kind": "notify", "title": "Again: {{title}}", "level": "error"}})
    feed.post("before", "", "error", "custom")
    assert webhooks.scan_feed() == 0                     # first scan: from now on
    feed.post("Disk full", "", "error", "custom")
    feed.post("fine", "", "info", "custom")
    assert webhooks.scan_feed() == 1
    h = webhooks.list_hooks()[0]
    _done(h["id"], webhooks.calls(h["id"])[0]["id"])
    assert feed.list_events(source="fwd")["events"][0]["title"] == "Again: Disk full"
    assert webhooks.scan_feed() == 0                     # its own notification does not start it again


def test_cron_and_agent_ends_reach_event_hooks(mx):
    out = mx["tmp"] / "ends"
    webhooks.create({"name": "c", "trigger": {"kind": "event", "on": "cron", "when": "fail"},
                     "action": {"kind": "shell", "command": f"cat >> {out}"}})
    webhooks.create({"name": "a", "trigger": {"kind": "event", "on": "agent", "agent": "acme/blog"},
                     "action": {"kind": "shell", "command": f"cat >> {out}"}})
    webhooks.emit("cron", {"cron": "c_1", "name": "Backup", "ok": True})
    webhooks.emit("cron", {"cron": "c_1", "name": "Backup", "ok": False})
    webhooks.emit("agent", {"agent": "acme/blog/agents/writer", "ok": True, "text": "done"})
    webhooks.emit("agent", {"agent": "other/x/agents/y", "ok": True})
    assert webhooks.process_spool() == 2
    wait_for(lambda: webhooks.dispatcher.idle() and out.exists() and out.read_text().count("}") == 2)
    assert '"ok": false' in out.read_text() and "writer" in out.read_text()


def test_cron_run_emits_its_end(mx):
    from maxxing import crons
    webhooks.create({"name": "c", "trigger": {"kind": "event", "on": "cron"}, "action": {"kind": "store"}})
    job = crons.create_job({"name": "j", "schedule": "0 5 * * *", "kind": "shell", "command": "exit 2"})
    crons.run_job(job["id"])
    item = json.loads(next(webhooks._dir("spool").glob("*.json")).read_text())
    assert item["kind"] == "cron" and item["data"]["ok"] is False and item["data"]["name"] == "j"


def test_test_and_replay(client, mx):
    out = mx["tmp"] / "t"
    h = client.post("/api/webhooks", json=_shell("t", f"cat >> {out}; echo >> {out}", source="github")).json()
    r = client.post(f"/api/webhooks/{h['id']}/test").json()
    rec = _done(h["id"], r["id"])
    assert rec["trigger"] == "test" and rec["event"] == "push"
    again = client.post(f"/api/webhooks/{h['id']}/calls/{rec['id']}/replay").json()
    assert _done(h["id"], again["id"])["trigger"] == "replay"
    assert out.read_text().count("refs/heads/main") == 2
    detail = client.get(f"/api/webhooks/{h['id']}/calls/{rec['id']}").json()
    assert "refs/heads/main" in detail["body"] and detail["request"]["event"] == "push"


def test_records_are_capped(mx, monkeypatch):
    monkeypatch.setattr(webhooks, "KEEP_CALLS", 3)
    h = webhooks.create(_shell("c", "true"))
    for _ in range(5):
        webhooks.test(h["id"], inline=True)
    recs = webhooks._records(h["id"])
    assert len(recs) == 3 and len(list(webhooks._dir("calls", h["id"]).iterdir())) == 3


def test_recover_resumes_queued_and_fails_interrupted(mx):
    h = webhooks.create(_shell("r", "true"))
    a, b = webhooks._prepare_test(h["id"]), webhooks._prepare_test(h["id"])
    webhooks._update_record(h["id"], b, status="running")
    assert webhooks.recover() == 2
    assert _done(h["id"], a)["status"] == "ok"
    assert _rec(h["id"], b)["error"].startswith("interrupted")


def test_validation():
    with pytest.raises(webhooks.WebhookError):
        webhooks._clean({"name": "x", "trigger": {"kind": "in", "source": "stripe", "methods": ["GET"]},
                         "action": {"kind": "shell", "command": "true"}})
    with pytest.raises(webhooks.WebhookError):
        webhooks._clean({"name": "x", "trigger": {"kind": "in"}, "action": {"kind": "shell", "command": "a\nb"}})
    with pytest.raises(webhooks.WebhookError):
        webhooks._clean({"name": "x", "trigger": {"kind": "in"}, "action": {"kind": "call", "url": "http://{{host}}/x"}})
    with pytest.raises(webhooks.WebhookError):
        webhooks._clean({"name": "x", "trigger": {"kind": "event", "on": "nope"}, "action": {"kind": "store"}})
    h = webhooks._clean({"name": "x", "trigger": {"kind": "event", "on": "agent"}, "action": {"kind": "call", "url": "https://a.example/x", "body": "raw"}})
    assert h["action"]["body"] == "json"


def test_feed_webhooks_still_work_and_are_listed(client):
    fh = feedhooks.create("legacy", "generic")
    r = client.post(f"/api/hooks/{fh['url'].rsplit('/', 1)[-1]}", json={"title": "old"})
    assert r.status_code == 200 and feed.list_events(source="legacy")["events"][0]["title"] == "old"
    listed = client.get("/api/webhooks").json()["feed_hooks"]
    assert listed[0]["name"] == "legacy" and listed[0]["agent"] is None


def test_cli_add_list_and_agent_guard(mx, capsys, monkeypatch):
    from maxxing import cli
    assert cli.main(["webhooks", "add", "--spec", json.dumps(_shell("cli", "true"))]) == 0
    assert "created w_" in capsys.readouterr().out
    assert cli.main(["webhooks", "list"]) == 0
    assert "cli" in capsys.readouterr().out
    from maxxing import agent_guard
    monkeypatch.setattr(agent_guard, "agent_turn", lambda: {"path": "acme/blog/agents/w", "tampered": False})
    monkeypatch.setattr(agent_guard, "in_the_sandbox", lambda: False)
    assert "not allowed" in (agent_guard.check_cli(["webhooks", "add"]) or "")
    assert "not allowed" in (agent_guard.check_cli(["webhooks", "list"]) or "")   # its URLs are its keys


def test_a_phone_without_a_session_can_send_a_file(client, mx):
    h = client.post("/api/webhooks", json=_shell("up", 'ls "$MAXXING_WEBHOOK_FILES"', source="phone", reply="wait")).json()
    from fastapi.testclient import TestClient
    anon = TestClient(client.app)
    r = anon.post(f"/api/hooks/{_tok(h)}", files={"f": ("a.jpg", io.BytesIO(b"\xff\xd8\xff"), "image/jpeg")})
    assert r.status_code == 200 and r.text.strip() == "a.jpg"
    assert anon.post("/api/sessions", files={"f": ("a.jpg", io.BytesIO(b"x"), "image/jpeg")}).status_code == 401


def test_a_call_url_may_come_from_the_vault(client, sink):
    from maxxing import vault
    vault.put("DISCORD_URL", sink)
    h = client.post("/api/webhooks", json={"name": "d", "trigger": {"kind": "event", "on": "feed"},
                                           "action": {"kind": "call", "url": "{{key:DISCORD_URL}}", "body": '{"content": "{{title}}"}'}}).json()
    rec = webhooks.test(h["id"], inline=True)
    assert rec["status"] == "ok" and json.loads(_Sink.got[-1][1]) == {"content": "Test notification"}
    assert sink not in json.dumps(client.get("/api/webhooks").json())


def test_body_cap_follows_the_hook(mx):
    from maxxing import bodylimit
    h = webhooks.create(_shell("big", "true", source="phone"))
    assert bodylimit.cap_for("POST", f"/api/hooks/{_tok(h)}", False) == webhooks.PHONE_MB * webhooks.MB
    assert bodylimit.cap_for("POST", "/api/hooks/other", False) == feedhooks.MAX_BODY


def test_unauthenticated_management_is_refused(client):
    client.cookies.clear()
    assert client.get("/api/webhooks").status_code == 401
    assert client.post("/api/webhooks", json=_shell("x", "true")).status_code == 401


def test_remove_cleans_everything(mx):
    h = webhooks.create({"name": "s", "trigger": {"kind": "in"}, "action": {"kind": "store"}})
    webhooks.test(h["id"], inline=True)
    webhooks.remove(h["id"])
    assert not (webhooks._dir("data") / f"{h['id']}.db").exists() and not (mx["state"] / "webhooks" / "calls" / h["id"]).exists() \
        and h["id"] not in config.load_secrets().get("webhooks", {})


def test_url_has_the_public_address(mx):
    config.save_config({**config.load_config(), "public_url": "https://ui.example.com/"})
    h = webhooks.create(_shell("u", "true"))
    assert h["url"].startswith("https://ui.example.com/api/hooks/")
    assert Path(webhooks.hooks_path()).exists()


def test_a_failed_save_frees_the_signed_delivery_so_the_retry_is_not_a_duplicate(client, monkeypatch):
    h = client.post("/api/webhooks", json={**_shell("g", "true", source="generic"), "secret": "k"}).json()
    body = json.dumps({"a": 1}).encode()
    hdr = {"X-Signature": hmac.new(b"k", body, hashlib.sha256).hexdigest(), "Content-Type": "application/json"}
    real = webhooks._save_request

    def boom(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(webhooks, "_save_request", boom)
    with pytest.raises(OSError):
        client.post(f"/api/hooks/{_tok(h)}", content=body, headers=hdr)
    monkeypatch.setattr(webhooks, "_save_request", real)
    r = client.post(f"/api/hooks/{_tok(h)}", content=body, headers=hdr)
    assert r.status_code == 202 and not r.json().get("duplicate"), r.text
