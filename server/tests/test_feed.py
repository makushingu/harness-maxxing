from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from maxxing import feed, feedhooks


def test_post_list_group_dedupe_read(client, mx):
    r = client.post("/api/feed", json={"title": "Hello", "body": "World", "level": "success", "source": "mail"})
    assert r.status_code == 200 and r.json()["event"]["title"] == "Hello"
    assert client.post("/api/feed", json={"title": "x", "level": "nope"}).status_code == 400
    assert client.post("/api/feed", json={"title": " "}).status_code == 400
    # dedupe per source
    a = client.post("/api/feed", json={"title": "Order 1", "source": "shop", "dedupe": "o1"}).json()
    b = client.post("/api/feed", json={"title": "Order 1", "source": "shop", "dedupe": "o1"}).json()
    assert a["duplicate"] is False and b["duplicate"] is True
    # group: repeats fold into one unread row
    for _ in range(3):
        client.post("/api/feed", json={"title": "Jobs OK", "source": "crons", "group": "ok", "level": "success"})
    lst = client.get("/api/feed").json()
    grouped = [e for e in lst["events"] if e["title"] == "Jobs OK"]
    assert len(grouped) == 1 and grouped[0]["count"] == 3
    assert lst["unread"] == 3 and {s["source"] for s in lst["sources"]} == {"mail", "shop", "crons"}
    assert [e["source"] for e in client.get("/api/feed", params={"source": "shop"}).json()["events"]] == ["shop"]
    # read: one source, then everything
    assert client.post("/api/feed/read", json={"source": "shop"}).json()["unread"] == 2
    client.post("/api/feed", json={"title": "Jobs OK", "source": "crons", "group": "ok", "level": "success"})
    assert client.post("/api/feed/read", json={"all": True}).json()["unread"] == 0
    # a read row is not grown any more: a new one starts
    client.post("/api/feed", json={"title": "Jobs OK", "source": "crons", "group": "ok", "level": "success"})
    assert len([e for e in client.get("/api/feed").json()["events"] if e["title"] == "Jobs OK"]) == 2
    eid = lst["events"][0]["id"]
    assert client.delete(f"/api/feed/{eid}").json() == {"ok": True}
    # paging
    page = client.get("/api/feed", params={"limit": 1}).json()
    assert len(page["events"]) == 1 and page["more"] is True
    assert client.get("/api/feed", params={"limit": 1, "before": page["events"][0]["id"]}).json()["events"]


def test_rules_and_telegram_routing(client, mx, monkeypatch):
    sent = []
    from maxxing.telegram import gateway
    monkeypatch.setattr(gateway, "feed_notify", lambda ev, loud=False: sent.append((ev["title"], loud)))
    feed.post("Boom", level="error", source="shop")            # auto: error -> loud
    feed.post("Careful", level="warning", source="shop")       # auto: warning -> silent
    feed.post("Fyi", level="info", source="shop")              # auto: info -> off
    feed.post("Cron failed", level="error", source="crons")    # own thread (Crons) -> off by default
    assert sent == [("Boom", True), ("Careful", False)]
    s = client.put("/api/feed/settings", json={"rules": {"shop": "loud", "crons": "silent"}}).json()
    assert {x["source"]: x["rule"] for x in s["sources"]}["shop"] == "loud"
    sent.clear()
    feed.post("Fyi", level="info", source="shop")
    feed.post("Cron failed", level="error", source="crons")
    assert sent == [("Fyi", True), ("Cron failed", False)]
    assert client.put("/api/feed/settings", json={"rules": {"shop": "maybe"}}).status_code == 400
    client.put("/api/feed/settings", json={"telegram": False})
    sent.clear()
    feed.post("Boom", level="error", source="shop")
    assert sent == []
    msg, markup = gateway.feed_message({"id": 7, "title": "Sale: 49.00 EUR", "body": "a@b.c", "level": "success",
                                        "source": "stripe", "url": "https://dashboard.stripe.com/payments", "count": 1})
    assert "<b>Sale: 49.00 EUR</b>" in msg and markup["inline_keyboard"][0][0]["callback_data"] == "f:7"
    assert markup["inline_keyboard"][0][1]["url"].startswith("https://dashboard.stripe.com")


def test_webhooks_signatures_and_parsing(client, mx):
    hooks = {}
    for kind, secret in (("stripe", "whsec_test"), ("shopify", "shpss"), ("github", "ghs"), ("generic", "")):
        r = client.post("/api/feed/hooks", json={"name": f"my-{kind}", "kind": kind, "secret": secret})
        assert r.status_code == 200, r.text
        hooks[kind] = r.json()
        assert "/api/hooks/" in hooks[kind]["url"] and hooks[kind]["has_secret"] == bool(secret)
    assert client.post("/api/feed/hooks", json={"name": "my-stripe", "kind": "stripe"}).status_code == 409
    assert client.post("/api/feed/hooks", json={"name": "crons", "kind": "generic"}).status_code == 409
    assert client.post("/api/feed/hooks", json={"name": "x", "kind": "paypal"}).status_code == 400
    path = {k: "/api/hooks/" + h["url"].rsplit("/", 1)[-1] for k, h in hooks.items()}

    # Stripe: sale, signed; bad signature refused; replay ignored
    body = json.dumps({"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {
        "amount_total": 4900, "currency": "eur", "customer_details": {"email": "a@b.c"}}}}).encode()
    t = str(int(time.time()))
    sig = hmac.new(b"whsec_test", f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    ok = client.post(path["stripe"], content=body, headers={"Stripe-Signature": f"t={t},v1={sig}"})
    assert ok.status_code == 200 and ok.json()["duplicate"] is False
    assert client.post(path["stripe"], content=body, headers={"Stripe-Signature": f"t={t},v1={sig}"}).json()["duplicate"]
    assert client.post(path["stripe"], content=body, headers={"Stripe-Signature": f"t={t},v1=deadbeef"}).status_code == 401
    old = str(int(time.time()) - 3600)
    osig = hmac.new(b"whsec_test", f"{old}.".encode() + body, hashlib.sha256).hexdigest()
    assert client.post(path["stripe"], content=body, headers={"Stripe-Signature": f"t={old},v1={osig}"}).status_code == 401
    # Shopify order
    body = json.dumps({"id": 42, "name": "#1001", "total_price": "59.90", "currency": "EUR", "email": "c@d.e"}).encode()
    hm = base64.b64encode(hmac.new(b"shpss", body, hashlib.sha256).digest()).decode()
    r = client.post(path["shopify"], content=body, headers={"X-Shopify-Hmac-Sha256": hm, "X-Shopify-Topic": "orders/create",
                                                          "X-Shopify-Shop-Domain": "acme.myshopify.com", "X-Shopify-Webhook-Id": "w1"})
    assert r.status_code == 200, r.text
    assert client.post(path["shopify"], content=body, headers={"X-Shopify-Hmac-Sha256": "bad", "X-Shopify-Topic": "orders/create"}).status_code == 401
    # GitHub failed workflow
    body = json.dumps({"action": "completed", "repository": {"full_name": "acme/site"},
                       "workflow_run": {"name": "CI", "conclusion": "failure", "head_branch": "main",
                                        "html_url": "https://github.com/acme/site/actions/runs/1"}}).encode()
    gs = "sha256=" + hmac.new(b"ghs", body, hashlib.sha256).hexdigest()
    assert client.post(path["github"], content=body, headers={"X-Hub-Signature-256": gs, "X-GitHub-Event": "workflow_run",
                                                            "X-GitHub-Delivery": "d1"}).status_code == 200
    # Generic, no secret
    assert client.post(path["generic"], json={"title": "Stock low", "message": "3 left", "level": "warning",
                                              "id": "s1"}).status_code == 200
    assert client.post("/api/hooks/not-a-token", json={"title": "x"}).status_code == 404

    events = {e["source"]: e for e in client.get("/api/feed").json()["events"]}
    assert events["my-stripe"]["title"] == "Sale: 49.00 EUR" and events["my-stripe"]["level"] == "success"
    assert events["my-shopify"]["title"] == "New order #1001: 59.90 EUR"
    assert events["my-shopify"]["url"] == "https://acme.myshopify.com/admin/orders/42"
    assert events["my-github"]["level"] == "error" and "CI failure - acme/site" in events["my-github"]["title"]
    assert events["my-generic"]["title"] == "Stock low" and events["my-generic"]["body"] == "3 left"

    # test button, regenerate token (old URL dead), delete
    hid = hooks["generic"]["id"]
    assert client.post(f"/api/feed/hooks/{hid}/test").json()["event"]["source"] == "my-generic"
    new = client.patch(f"/api/feed/hooks/{hid}", json={"regenerate": True}).json()
    assert new["url"] != hooks["generic"]["url"]
    assert client.post(path["generic"], json={"title": "x"}).status_code == 404
    assert client.delete(f"/api/feed/hooks/{hid}").json() == {"ok": True}
    assert hid not in {h["id"] for h in client.get("/api/feed/settings").json()["hooks"]}


def test_webhook_rate_limit(client, mx, monkeypatch):
    h = feedhooks.create("bursty", "generic")
    monkeypatch.setattr(feedhooks, "RATE", 3)
    url = "/api/hooks/" + h["url"].rsplit("/", 1)[-1]
    client.cookies.clear()                                    # webhooks come from outside: no session
    assert client.get("/api/feed").status_code == 401
    codes = [client.post(url, json={"title": f"n{i}"}).status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_cron_runs_go_to_the_feed(client, mx):
    from maxxing import crons
    ok = client.post("/api/crons", json={"name": "Nightly ok", "schedule": "0 3 * * *", "type": "shell",
                                          "command": "echo done"}).json()
    bad = client.post("/api/crons", json={"name": "Nightly bad", "schedule": "0 3 * * *", "type": "shell",
                                           "command": "echo oops >&2; exit 3"}).json()
    crons.run_job(ok["id"])
    crons.run_job(ok["id"])
    crons.run_job(bad["id"])
    evs = client.get("/api/feed", params={"source": "crons"}).json()["events"]
    fail = next(e for e in evs if e["level"] == "error")
    okrow = next(e for e in evs if e["level"] == "success")
    assert fail["title"] == "Cron failed: Nightly bad" and "oops" in fail["body"] and fail["url"] == f"/crons?job={bad['id']}"
    assert okrow["title"] == "Cron jobs succeeded" and okrow["count"] == 2


def test_cli_post_reaches_the_api(client, mx, capsys):
    from maxxing import cli
    assert cli.main(["feed", "post", "Inbox: invoice from ACME", "--source", "mail", "--level", "warning",
                     "--dedupe", "m1"]) == 0
    assert cli.main(["feed", "post", "Inbox: invoice from ACME", "--source", "mail", "--dedupe", "m1"]) == 0
    assert "duplicate" in capsys.readouterr().out
    evs = client.get("/api/feed", params={"source": "mail"}).json()["events"]
    assert len(evs) == 1 and evs[0]["level"] == "warning"


def test_signed_kinds_refuse_deliveries_without_secret(client, mx):
    import json as _json
    for kind in ("stripe", "shopify", "github"):
        h = client.post("/api/feed/hooks", json={"name": f"ns-{kind}", "kind": kind}).json()
        assert h["has_secret"] is False                        # creation stays possible (Stripe: secret comes later)
        url = "/api/hooks/" + h["url"].rsplit("/", 1)[-1]
        body = _json.dumps({"id": "evt_x", "type": "checkout.session.completed"}).encode()
        r = client.post(url, content=body)
        assert r.status_code == 401 and r.json()["error"] == "secret_required", kind
        assert client.post(url, content=body).status_code == 401
    evs = client.get("/api/feed", params={"source": "security"}).json()["events"]
    assert {e["title"] for e in evs} >= {"Webhook ns-stripe refused: no signing secret"}
    assert len([e for e in evs if "ns-stripe" in e["title"]]) == 1       # folded, not one row per call
    # once the secret is set, signed deliveries go through
    hid = next(h["id"] for h in client.get("/api/feed/settings").json()["hooks"] if h["name"] == "ns-github")
    url = "/api/hooks/" + client.patch(f"/api/feed/hooks/{hid}", json={"secret": "ghs"}).json()["url"].rsplit("/", 1)[-1]
    body = _json.dumps({"zen": "hi"}).encode()
    gs = "sha256=" + hmac.new(b"ghs", body, hashlib.sha256).hexdigest()
    assert client.post(url, content=body, headers={"X-Hub-Signature-256": gs, "X-GitHub-Event": "ping"}).status_code == 200


def test_sources_created_at_the_same_time_are_all_kept(mx):
    import threading
    errs = []

    def make(i):
        try:
            feedhooks.create(f"race{i}", "generic", f"s{i}")
        except Exception as e:  # noqa: BLE001
            errs.append(e)
    threads = [threading.Thread(target=make, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    hooks = feedhooks.list_hooks()
    assert errs == [] and sorted(h["name"] for h in hooks) == sorted(f"race{i}" for i in range(12))
    assert all(h["has_secret"] for h in hooks)


def test_a_lone_surrogate_in_a_webhook_is_stored_not_a_500(client, mx):
    tok = feedhooks.create("gen", "generic")["url"].rsplit("/", 1)[1]
    r = client.post(f"/api/hooks/{tok}", content=b'{"title": "a\\ud800b", "body": "x\\udfff"}',
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert [e["title"] for e in feed.list_events()["events"]] == ["a?b"]


def test_a_deeply_nested_webhook_body_is_a_400(client, mx):
    tok = feedhooks.create("gen", "generic")["url"].rsplit("/", 1)[1]
    assert feedhooks.deliver(tok, {}, b"[" * 200000) == (400, {"error": "bad_json"})


def test_stripe_timestamp_with_a_unicode_digit_is_a_401(client, mx):
    tok = feedhooks.create("stp", "stripe", "sek")["url"].rsplit("/", 1)[1]
    r = feedhooks.deliver(tok, {"Stripe-Signature": "t=²,v1=ab"}, b'{"type": "charge.succeeded"}')
    assert r == (401, {"error": "bad_signature"})


def test_webhook_payloads_of_an_unexpected_shape_are_a_400(client, mx):
    def signed(kind, body, event=""):
        tok = feedhooks.create(f"{kind}{len(feedhooks.list_hooks())}", kind, "sek")["url"].rsplit("/", 1)[1]
        if kind == "stripe":
            now = str(int(time.time()))
            sig = hmac.new(b"sek", f"{now}.".encode() + body, hashlib.sha256).hexdigest()
            return feedhooks.deliver(tok, {"Stripe-Signature": f"t={now},v1={sig}"}, body)
        sig = "sha256=" + hmac.new(b"sek", body, hashlib.sha256).hexdigest()
        return feedhooks.deliver(tok, {"X-Hub-Signature-256": sig, "X-GitHub-Event": event}, body)
    bad = (400, {"error": "bad_payload"})
    assert signed("stripe", b'{"type": "charge.succeeded", "id": "e1", "data": {"object": "x"}}') == bad
    assert signed("github", b'{"pull_request": {"user": null, "title": "x"}, "action": "opened"}', "pull_request") == bad
    assert signed("github", b'{"ref": "refs/heads/m", "commits": [1]}', "push") == bad
    assert feed.list_events()["events"] == []


def test_webhook_fields_of_another_type_are_text_not_a_500(client, mx):
    import base64

    def signed(kind, body, headers):
        tok = feedhooks.create(f"{kind}{len(feedhooks.list_hooks())}", kind, "sek")["url"].rsplit("/", 1)[1]
        mac = hmac.new(b"sek", body, hashlib.sha256)
        if kind == "stripe":
            now = str(int(time.time()))
            sig = hmac.new(b"sek", f"{now}.".encode() + body, hashlib.sha256).hexdigest()
            headers = {"Stripe-Signature": f"t={now},v1={sig}", **headers}
        elif kind == "shopify":
            headers = {"X-Shopify-Hmac-Sha256": base64.b64encode(mac.digest()).decode(), **headers}
        else:
            headers = {"X-Hub-Signature-256": "sha256=" + mac.hexdigest(), **headers}
        return feedhooks.deliver(tok, headers, body)
    shop = b'{"name": "#1", "total_price": "10", "currency": "eur", "email": 5}'
    assert signed("shopify", shop, {"X-Shopify-Topic": "orders/create"})[0] == 200
    gh = b'{"pull_request": {"user": {"login": "a"}, "title": "x", "html_url": 5}, "action": "opened"}'
    assert signed("github", gh, {"X-GitHub-Event": "pull_request"})[0] == 200
    big = b'{"type": "checkout.session.completed", "id": "e2", "data": {"object": {"amount_total": 1' + b"0" * 400 + b'}}}'
    assert signed("stripe", big, {})[0] == 200
    events = feed.list_events()["events"]
    assert len(events) == 3 and "5" in [e["body"] for e in events]


def test_an_unreadable_feed_db_is_set_aside_and_replaced(mx):
    path = feed.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a database" * 100)
    feed._ready.discard(str(path))
    assert feed.post("after the crash")["title"] == "after the crash"
    assert [e["title"] for e in feed.list_events()["events"]] == ["after the crash"]
    kept = list(path.parent.glob("feed.db.damaged-*"))
    assert len(kept) == 1 and kept[0].read_bytes().startswith(b"this is not a database")


def test_event_ids_too_big_for_sqlite_are_not_a_500(client, mx):
    ev = client.post("/api/feed", json={"title": "kept"}).json()["event"]
    big = 10**30
    r = client.get("/api/feed", params={"before": big})
    assert r.status_code == 200 and [e["id"] for e in r.json()["events"]] == [ev["id"]]
    assert client.post("/api/feed/read", json={"ids": [big, ev["id"]]}).status_code == 200
    assert client.delete(f"/api/feed/{big}").status_code < 500
    assert feed.get(big) is None and feed.get(ev["id"])["read"] is True


def test_stripe_timestamp_with_thousands_of_digits_is_a_401(client, mx):
    tok = feedhooks.create("stp", "stripe", "sek")["url"].rsplit("/", 1)[1]
    r = feedhooks.deliver(tok, {"Stripe-Signature": "t=" + "9" * 5000 + ",v1=ab"}, b'{"type": "charge.succeeded"}')
    assert r == (401, {"error": "bad_signature"})
