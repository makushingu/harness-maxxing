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
