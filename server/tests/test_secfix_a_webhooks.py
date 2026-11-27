"""Webhooks: the reply of a "wait" hook, unsigned query, Stripe retries, CSV formulas, callers waiting (webhooks.py)."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

from maxxing import webhooks
from test_webhooks import _done, _shell, _tok


def test_a_wait_reply_never_renders_as_a_page_of_the_ui(client):
    h = client.post("/api/webhooks", json=_shell("page", "printf '<script>alert(1)</script>' > $MAXXING_RESPONSE_FILE; "
                                                 "printf text/html > $MAXXING_RESPONSE_FILE.type", reply="wait")).json()
    r = client.post(f"/api/hooks/{_tok(h)}", json={})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and "<script>" in r.text
    assert r.headers["content-security-policy"] == "sandbox" and r.headers["x-content-type-options"] == "nosniff"


def test_a_signed_call_without_a_body_carries_no_query(client, mx):
    """The signature of an empty body is the same for every call: the query of such a call proves nothing."""
    out = mx["tmp"] / "seen"
    h = client.post("/api/webhooks", json={**_shell("g", f'echo "$MAXXING_WEBHOOK_QUERY|$(cat)" > {out}', source="generic"),
                                           "secret": "k"}).json()
    sig = hmac.new(b"k", b"", hashlib.sha256).hexdigest()
    r = client.post(f"/api/hooks/{_tok(h)}?cmd=deploy&to=prod", headers={"X-Signature": sig})
    assert r.status_code == 202, r.text
    assert _done(h["id"], r.json()["call"])["status"] == "ok"
    assert out.read_text().strip() == "{}|"
    body = b'{"a": 1}'                                  # with a body the query is kept, as before
    r = client.post(f"/api/hooks/{_tok(h)}?to=prod", content=body, headers={
        "X-Signature": hmac.new(b"k", body, hashlib.sha256).hexdigest(), "Content-Type": "application/json"})
    assert _done(h["id"], r.json()["call"])["status"] == "ok"
    assert out.read_text().strip() == '{"to": "prod"}|{"a": 1}'


def _stripe(client, tok: str, body: bytes, t: int):
    sig = hmac.new(b"whsec", f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return client.post(f"/api/hooks/{tok}", content=body,
                       headers={"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"})


def test_a_stripe_retry_of_the_same_event_does_not_run_the_action_again(client, mx):
    out = mx["tmp"] / "runs"
    h = client.post("/api/webhooks", json={**_shell("pay", f"echo run >> {out}", source="stripe"), "secret": "whsec"}).json()
    body = json.dumps({"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {}}}).encode()
    now = int(time.time())
    first = _stripe(client, _tok(h), body, now)
    assert first.status_code == 202, first.text
    _done(h["id"], first.json()["call"])
    again = _stripe(client, _tok(h), body, now + 3)      # the retry is signed anew, with another time
    assert again.status_code == 200 and again.json() == {"ok": True, "duplicate": True}
    other = _stripe(client, _tok(h), body.replace(b"evt_1", b"evt_2"), now + 4)
    assert other.status_code == 202
    _done(h["id"], other.json()["call"])
    assert out.read_text().splitlines() == ["run", "run"]


def test_the_csv_export_never_starts_a_cell_like_a_formula(client):
    h = client.post("/api/webhooks", json={"name": "form", "trigger": {"kind": "in"},
                                           "action": {"kind": "store", "fields": {"name": "name", "n": "n"}}}).json()
    for name in ('=HYPERLINK("http://evil.example","x")', "+1", "-2", "@SUM(A1)", "Alice"):
        _done(h["id"], client.post(f"/api/hooks/{_tok(h)}", json={"name": name, "n": -5}).json()["call"])
    text = client.get(f"/api/webhooks/{h['id']}/data?format=csv").text
    import csv
    import io
    rows = list(csv.DictReader(io.StringIO(text)))
    assert sorted(r["name"] for r in rows) == sorted(["'=HYPERLINK(\"http://evil.example\",\"x\")", "'+1", "'-2", "'@SUM(A1)", "Alice"])
    assert {r["n"] for r in rows} == {"-5"}             # a number stays a number


def test_one_hook_cannot_take_every_waiting_place():
    d = webhooks.Dispatcher()
    assert [d.sync_slot("h_slow") for _ in range(webhooks.SYNC_MAX)] == [True] * webhooks.SYNC_PER_HOOK + \
        [False] * (webhooks.SYNC_MAX - webhooks.SYNC_PER_HOOK)
    assert d.sync_slot("h_other")                       # a place is left for the other hooks
    assert not d.sync_slot("h_third")                   # the total stays SYNC_MAX
    d.sync_release("h_slow")
    assert d.sync_slot("h_third")
    for hid in ("h_slow", "h_slow", "h_other", "h_third"):
        d.sync_release(hid)
    assert d.sync == 0 and d.sync_by == {}
