"""Signed webhooks: a captured delivery replayed with a new (unsigned) delivery id is a duplicate; two copies of
one event arriving together post once and never fail."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from maxxing import feed, feedhooks


def _token(hook: dict) -> str:
    return hook["url"].rsplit("/", 1)[-1]


def _shopify(body: bytes, wid: str, topic: str = "orders/create") -> dict:
    sig = base64.b64encode(hmac.new(b"shpss", body, hashlib.sha256).digest()).decode()
    return {"X-Shopify-Hmac-Sha256": sig, "X-Shopify-Topic": topic, "X-Shopify-Webhook-Id": wid}


ORDER = json.dumps({"id": 42, "name": "#1001", "total_price": "59.90", "currency": "EUR"}).encode()


def test_replayed_shopify_delivery_with_a_new_id_is_a_duplicate(mx):
    tok = _token(feedhooks.create("shop", "shopify", "shpss"))
    assert feedhooks.deliver(tok, _shopify(ORDER, "w1"), ORDER)[1]["duplicate"] is False
    st, out = feedhooks.deliver(tok, _shopify(ORDER, "w2-replay"), ORDER)       # same signed body, new header id
    assert st == 200 and out["duplicate"] is True
    assert len(feed.list_events(source="shop")["events"]) == 1


def test_shopify_topics_of_one_order_each_post_once(mx):
    """An order paid at once: Shopify sends the same body as orders/create and orders/paid - both are shown,
    and inventing topics on a replay posts at most one more event."""
    tok = _token(feedhooks.create("shop", "shopify", "shpss"))
    assert feedhooks.deliver(tok, _shopify(ORDER, "w1"), ORDER)[1]["duplicate"] is False
    assert feedhooks.deliver(tok, _shopify(ORDER, "w2", "orders/paid"), ORDER)[1]["duplicate"] is False
    assert feedhooks.deliver(tok, _shopify(ORDER, "w3", "orders/paid"), ORDER)[1]["duplicate"] is True
    made_up = [feedhooks.deliver(tok, _shopify(ORDER, f"x{i}", f"made/up{i}"), ORDER)[1]["duplicate"] for i in range(4)]
    assert made_up == [False, True, True, True]


def test_replayed_shopify_delivery_cannot_link_outside_shopify(mx):
    """X-Shopify-Shop-Domain is not signed: a replay with another domain gets no link and stays a duplicate."""
    tok = _token(feedhooks.create("shop", "shopify", "shpss"))
    evil = {**_shopify(ORDER, "w1", "orders/cancelled"), "X-Shopify-Shop-Domain": "evil.example"}
    assert feedhooks.deliver(tok, evil, ORDER)[1]["duplicate"] is False
    assert feed.list_events(source="shop")["events"][0]["url"] in ("", None)
    good = {**_shopify(ORDER, "w2"), "X-Shopify-Shop-Domain": "Acme.myshopify.com"}
    assert feedhooks.deliver(tok, good, ORDER)[1]["duplicate"] is False
    urls = {e["url"] for e in feed.list_events(source="shop")["events"]}
    assert "https://acme.myshopify.com/admin/orders/42" in urls and not any("evil" in (u or "") for u in urls)
    again = {**_shopify(ORDER, "w3"), "X-Shopify-Shop-Domain": "other.myshopify.com"}
    assert feedhooks.deliver(tok, again, ORDER)[1]["duplicate"] is True


def test_replayed_github_delivery_with_a_new_id_is_a_duplicate(mx):
    tok = _token(feedhooks.create("gh", "github", "ghs"))
    body = json.dumps({"action": "published", "release": {"tag_name": "v1"}, "repository": {"full_name": "a/b"}}).encode()
    sig = "sha256=" + hmac.new(b"ghs", body, hashlib.sha256).hexdigest()
    hd = {"X-Hub-Signature-256": sig, "X-GitHub-Event": "release", "X-GitHub-Delivery": "d1"}
    assert feedhooks.deliver(tok, hd, body)[1]["duplicate"] is False
    assert feedhooks.deliver(tok, {**hd, "X-GitHub-Delivery": "d2"}, body)[1]["duplicate"] is True


def test_simultaneous_duplicate_delivery_is_not_a_500(mx, monkeypatch):
    """Two copies of one event at the same time (sender retry): the check passes for both, the unique index
    refuses the second insert - that copy is a duplicate, not a server error."""
    tok = _token(feedhooks.create("gen", "generic"))
    real_conn = feed._conn

    class Racy:
        def __init__(self):
            self.c = real_conn()

        def __enter__(self):
            self.c.__enter__()
            return self

        def __exit__(self, *a):
            return self.c.__exit__(*a)

        def execute(self, sql, args=()):
            r = self.c.execute(sql, args)
            if sql.startswith("SELECT 1 FROM events WHERE source=? AND dedupe=?"):
                with real_conn() as other:              # the other request inserts right now
                    other.execute("INSERT INTO events(at, source, level, title, dedupe) VALUES (?,?,?,?,?)",
                                  (time.time(), args[0], "info", "x", args[1]))
            return r
    monkeypatch.setattr(feed, "_conn", lambda: Racy())
    body = json.dumps({"title": "Deploy", "id": "evt-1"}).encode()
    st, out = feedhooks.deliver(tok, {}, body)
    assert st == 200 and out["duplicate"] is True


def _github(body: bytes, event: str, delivery: str) -> dict:
    sig = "sha256=" + hmac.new(b"ghs", body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": sig, "X-GitHub-Event": event, "X-GitHub-Delivery": delivery}


def test_an_ignored_github_body_replayed_as_another_event_is_a_duplicate(mx):
    """GitHub signs the body, not X-GitHub-Event: a pull_request "synchronize" (ignored) sent again as "star" must
    not post; nor a posted body whose event was deleted since."""
    tok = _token(feedhooks.create("gh", "github", "ghs"))
    body = json.dumps({"action": "synchronize", "pull_request": {"title": "x"}, "repository": {"full_name": "o/r"}}).encode()
    assert feedhooks.deliver(tok, _github(body, "pull_request", "d1"), body)[1].get("ignored") is True
    for ev in ("star", "fork", "deployment"):
        st, out = feedhooks.deliver(tok, _github(body, ev, f"d-{ev}"), body)
        assert st == 200 and out["duplicate"] is True
    rel = json.dumps({"action": "published", "release": {"tag_name": "v1"}, "repository": {"full_name": "o/r"}}).encode()
    first = feedhooks.deliver(tok, _github(rel, "release", "d2"), rel)[1]
    feed.delete(first["id"])
    assert feedhooks.deliver(tok, _github(rel, "release", "d3"), rel)[1]["duplicate"] is True
    assert feed.list_events(source="gh")["events"] == []


def _generic(body: bytes) -> dict:
    return {"X-Signature": "sha256=" + hmac.new(b"k", body, hashlib.sha256).hexdigest()}


def test_a_signed_generic_body_replayed_posts_once_within_a_day(mx, monkeypatch):
    tok = _token(feedhooks.create("mon", "generic", "k"))
    body = json.dumps({"title": "Server down", "level": "error"}).encode()
    assert feedhooks.deliver(tok, _generic(body), body)[1]["duplicate"] is False
    for rid in ("r2", "r3"):
        assert feedhooks.deliver(tok, {**_generic(body), "X-Request-Id": rid}, body)[1]["duplicate"] is True
    assert len(feed.list_events(source="mon")["events"]) == 1
    later = time.time() + feedhooks.GENERIC_REPLAY_S + 1                # the same alert the next day: shown again
    monkeypatch.setattr(feed.time, "time", lambda: later)
    assert feedhooks.deliver(tok, _generic(body), body)[1]["duplicate"] is False
    # without a secret nothing changes: the token is the only permission, every POST counts
    open_tok = _token(feedhooks.create("open", "generic"))
    assert [feedhooks.deliver(open_tok, {}, body)[1]["duplicate"] for _ in range(2)] == [False, False]


def test_a_failed_signed_delivery_can_be_retried(mx, monkeypatch):
    tok = _token(feedhooks.create("mon", "generic", "k"))
    body = json.dumps({"title": "Deploy done"}).encode()
    real = feed.post

    def down(*a, **k):
        raise feed.FeedError(503, "busy", "busy")
    monkeypatch.setattr(feed, "post", down)
    assert feedhooks.deliver(tok, _generic(body), body)[0] == 503
    monkeypatch.setattr(feed, "post", real)
    assert feedhooks.deliver(tok, _generic(body), body)[1]["duplicate"] is False
