"""Incoming webhooks of the feed: POST /api/hooks/<token> (public, the token is the permission).

A hook = {id, name, kind, created} in config `feed.hooks`; its token and optional signing secret live in
secrets.json (`feed_hooks: {id: {token, secret}}`). The hook's name is the event source. Kinds:

  stripe   Stripe-Signature (t=, v1= HMAC-SHA256 of "t.body"), 5 min tolerance; sales, refunds, failed
           payments, subscriptions
  shopify  X-Shopify-Hmac-Sha256 (base64 HMAC-SHA256 of the body); orders, refunds, stock
  github   X-Hub-Signature-256 (sha256=hex); pushes, pull requests, issues, failed workflows, releases
  generic  optional X-Signature: sha256=hex; JSON {title, body|message|text, level, url, id}

A secret set on a hook is always checked. Stripe, Shopify and GitHub hooks (SIGNED_KINDS) REFUSE every
delivery until their secret is set (401 secret_required + one folded "security" feed warning): the hook
can be created first because Stripe only shows the signing secret once the endpoint (its URL) exists.
A generic hook without a secret accepts any POST with the token.
Payloads are data: they never run anything.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets as _secrets
import threading
import time
from collections import deque
from typing import Any

from . import config, feed
from .feed import FeedError

KINDS = ("stripe", "shopify", "github", "generic")
SIGNED_KINDS = ("stripe", "shopify", "github")     # these services always sign: no secret = refused
MAX_BODY = 1024 * 1024
RATE = 120                     # deliveries per hook per minute
STRIPE_TOLERANCE_S = 300
_hits: dict[str, deque] = {}


# ---- management ----------------------------------------------------------------------------
_lock = threading.Lock()                             # sources list + their secrets: one read-modify-write at a time


def _store() -> dict:
    v = config.load_secrets().get("feed_hooks")
    return v if isinstance(v, dict) else {}


def _save_store(store: dict) -> None:
    config.set_secret("feed_hooks", store or None)


def hook_url(token: str) -> str:
    base = (config.load_config().get("public_url") or "").rstrip("/")
    return f"{base}/api/hooks/{token}"


def public(h: dict, store: dict | None = None) -> dict:
    s = (store if store is not None else _store()).get(h["id"]) or {}
    return {**h, "url": hook_url(s.get("token", "")), "has_secret": bool(s.get("secret"))}


def list_hooks() -> list[dict]:
    store = _store()
    return [public(h, store) for h in feed.settings()["hooks"]]


def create(name: str, kind: str, secret: str = "") -> dict:
    if kind not in KINDS:
        raise FeedError(400, "bad_kind", f"Kind: {', '.join(KINDS)}")
    source = feed.clean_source(name or kind)
    if source in feed.BUILTIN:
        raise FeedError(409, "reserved", f"{source!r} is a built-in source")
    with _lock:
        hooks = feed.settings()["hooks"]
        if any(h["name"] == source for h in hooks):
            raise FeedError(409, "exists", f"A source named {source!r} already exists")
        h = {"id": _secrets.token_hex(4), "name": source, "kind": kind, "created": time.time()}
        store = _store()
        store[h["id"]] = {"token": _secrets.token_urlsafe(24), "secret": (secret or "").strip()}
        _save_store(store)
        feed.save_settings(hooks=hooks + [h])
    return public(h, store)


def update(hid: str, secret: str | None = None, regenerate: bool = False) -> dict:
    with _lock:
        h = _find(hid)
        store = _store()
        s = store.setdefault(hid, {"token": _secrets.token_urlsafe(24), "secret": ""})
        if secret is not None:
            s["secret"] = secret.strip()
        if regenerate:
            s["token"] = _secrets.token_urlsafe(24)
        _save_store(store)
    return public(h, store)


def remove(hid: str) -> None:
    with _lock:
        _find(hid)
        store = _store()
        store.pop(hid, None)
        _save_store(store)
        feed.save_settings(hooks=[h for h in feed.settings()["hooks"] if h["id"] != hid])


def _find(hid: str) -> dict:
    h = next((h for h in feed.settings()["hooks"] if h["id"] == hid), None)
    if h is None:
        raise FeedError(404, "not_found", "Unknown source")
    return h


def by_token(token: str) -> tuple[dict, dict] | None:
    for hid, s in _store().items():
        if token and _same(str(s.get("token", "")), token):
            h = next((h for h in feed.settings()["hooks"] if h["id"] == hid), None)
            if h:
                return h, s
    return None


def test(hid: str) -> dict | None:
    h = _find(hid)
    return feed.post(f"Test from {h['name']}", "If you can read this, the source works.", "info", h["name"],
                     notify=True)


# ---- delivery ------------------------------------------------------------------------------
def _limited(hid: str) -> bool:
    q = _hits.setdefault(hid, deque())
    now = time.time()
    while q and q[0] < now - 60:
        q.popleft()
    if len(q) >= RATE:
        return True
    q.append(now)
    return False


def _same(a: str, b: str) -> bool:
    """Constant-time comparison that also takes non-ASCII text (hmac.compare_digest raises on it: a 500)."""
    return hmac.compare_digest(a.encode("utf-8", "surrogateescape"), b.encode("utf-8", "surrogateescape"))


def _hex_ok(secret: str, body: bytes, got: str) -> bool:
    want = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return _same(want, (got or "").strip().lower())


def verify(kind: str, secret: str, headers: dict, body: bytes) -> bool:
    if not secret:
        return True
    h = {k.lower(): v for k, v in headers.items()}
    if kind == "stripe":
        parts = dict(p.split("=", 1) for p in h.get("stripe-signature", "").split(",") if "=" in p)
        t = parts.get("t", "")
        sigs = [v for k, v in (p.split("=", 1) for p in h.get("stripe-signature", "").split(",") if "=" in p) if k == "v1"]
        if not (t.isascii() and t.isdigit()) or abs(time.time() - int(t)) > STRIPE_TOLERANCE_S:   # "²" is a digit
            return False
        want = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
        return any(_same(want, s) for s in sigs)
    if kind == "shopify":
        want = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
        return _same(want, h.get("x-shopify-hmac-sha256", ""))
    if kind == "github":
        got = h.get("x-hub-signature-256", "")
        return got.startswith("sha256=") and _hex_ok(secret, body, got[7:])
    got = h.get("x-signature", "")
    return _hex_ok(secret, body, got[7:] if got.startswith("sha256=") else got)


def deliver(token: str, headers: dict, body: bytes) -> tuple[int, dict]:
    """-> (status, json). 404 unknown token, 401 bad signature, 413 too big, 429 too many, 400 bad body (bad_json,
    or bad_payload: valid JSON whose fields have an unexpected shape)."""
    found = by_token(token)
    if found is None:
        return 404, {"error": "not_found"}
    h, s = found
    if len(body) > MAX_BODY:
        return 413, {"error": "too_big"}
    # Signed sources count only deliveries that pass the signature: a leaked URL without the secret cannot use up
    # the minute's quota of the real sender.
    if not s.get("secret") and _limited(h["id"]):
        return 429, {"error": "rate_limited"}
    if h["kind"] in SIGNED_KINDS and not s.get("secret"):
        feed.system(f"Webhook {h['name']} refused: no signing secret",
                    f"Add the {h['kind'].capitalize()} signing secret in Settings -> Notifications "
                    "(source menu -> Set the signing secret); events are refused until then.",
                    "warning", "security", group=f"hook-secret-{h['id']}")
        return 401, {"error": "secret_required"}
    if not verify(h["kind"], s.get("secret", ""), headers, body):
        return 401, {"error": "bad_signature"}
    if s.get("secret") and _limited(h["id"]):
        return 429, {"error": "rate_limited"}
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except RecursionError:                             # "[[[[…" nested deeper than Python can parse
        return 400, {"error": "bad_json"}
    except (UnicodeDecodeError, ValueError):
        if h["kind"] != "generic":
            return 400, {"error": "bad_json"}
        payload = {"title": body.decode("utf-8", "replace")[:200]}
    lower = {k.lower(): v for k, v in headers.items()}
    try:
        ev = PARSERS[h["kind"]](payload if isinstance(payload, dict) else {"value": payload}, lower)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):   # a field of an unexpected shape
        return 400, {"error": "bad_payload"}
    if ev is None:
        return 200, {"ok": True, "ignored": True}
    # a parser passes some fields through as they came (an "email": 5): text for the feed, never a 500
    title, body_text, url = ("" if v is None else str(v) for v in ev[:2] + ev[3:4])
    level, dedupe = ev[2], ev[4]
    if h["kind"] in BODY_DEDUPE:                       # their delivery-id header is not signed: a captured body
        dedupe = _replay_key(h["kind"], lower, body)   # replayed with a new id must stay a duplicate
    try:
        posted = feed.post(title, body_text, level, h["name"], url, dedupe=dedupe)
    except FeedError as e:
        return e.status, {"error": e.code, "message": e.message}
    return 200, {"ok": True, "duplicate": posted is None, "id": posted["id"] if posted else None}


BODY_DEDUPE = ("shopify", "github")
_SHOPIFY_TOPICS = ("orders/create", "orders/paid", "orders/cancelled", "refunds/create", "inventory_levels/update")


def _replay_key(kind: str, lower_headers: dict, body: bytes) -> str:
    """Dedupe key from what the signature covers (the body). Shopify sends the same order body for several topics
    (an order paid at once: orders/create + orders/paid), so a known topic is part of the key; an unknown topic is
    not, so a replay cannot post again by inventing topics."""
    topic = ""
    if kind == "shopify":
        topic = str(lower_headers.get("x-shopify-topic", ""))
        topic = topic if topic in _SHOPIFY_TOPICS else "other"
    return f"sha256:{topic}:" + hashlib.sha256(body).hexdigest()


# ---- parsers: payload -> (title, body, level, url, dedupe) | None -----------------------------
Event = tuple[str, str, str, str, "str | None"]


def _money(amount: Any, currency: Any, cents: bool = True) -> str:
    try:
        v = float(amount) / (100 if cents else 1)
    except (OverflowError, TypeError, ValueError):
        return ""
    return f"{v:,.2f} {str(currency or '').upper()}".strip()


def _stripe(p: dict, h: dict) -> Event | None:
    typ = str(p.get("type") or "")
    obj = ((p.get("data") or {}).get("object") or {}) if isinstance(p.get("data"), dict) else {}
    eid = p.get("id")
    email = (obj.get("customer_details") or {}).get("email") or obj.get("receipt_email") or obj.get("customer_email") or ""
    dash = "https://dashboard.stripe.com/"
    if typ == "checkout.session.completed":
        amt = _money(obj.get("amount_total"), obj.get("currency"))
        return f"Sale: {amt}".strip(), email, "success", dash + "payments", eid
    if typ in ("payment_intent.succeeded", "charge.succeeded"):
        amt = _money(obj.get("amount_received", obj.get("amount")), obj.get("currency"))
        return f"Payment received: {amt}".strip(), email, "success", dash + "payments", eid
    if typ in ("charge.refunded", "refund.created"):
        amt = _money(obj.get("amount_refunded", obj.get("amount")), obj.get("currency"))
        return f"Refund: {amt}".strip(), email, "warning", dash + "payments", eid
    if typ in ("invoice.payment_failed", "payment_intent.payment_failed", "charge.failed"):
        amt = _money(obj.get("amount_due", obj.get("amount")), obj.get("currency"))
        return f"Payment failed: {amt}".strip(), email, "error", dash + "payments", eid
    if typ == "charge.dispute.created":
        return f"Dispute opened: {_money(obj.get('amount'), obj.get('currency'))}", "", "error", dash + "disputes", eid
    if typ == "customer.subscription.created":
        return "New subscription", email, "success", dash + "subscriptions", eid
    if typ == "customer.subscription.deleted":
        return "Subscription cancelled", email, "warning", dash + "subscriptions", eid
    if not typ:
        return None
    return f"Stripe: {typ}", "", "info", dash + "events", eid


def _shopify(p: dict, h: dict) -> Event | None:
    topic = h.get("x-shopify-topic", "")
    shop = h.get("x-shopify-shop-domain", "")
    did = h.get("x-shopify-webhook-id") or h.get("x-shopify-event-id")
    admin = f"https://{shop}/admin" if shop else ""
    name = p.get("name") or (f"#{p['order_number']}" if p.get("order_number") else "")
    amt = _money(p.get("total_price"), p.get("currency"), cents=False)
    who = (p.get("customer") or {}).get("email") or p.get("email") or ""
    if topic == "orders/create":
        return f"New order {name}: {amt}".strip(), who, "success", f"{admin}/orders/{p.get('id', '')}" if admin else "", did
    if topic == "orders/paid":
        return f"Order paid {name}: {amt}".strip(), who, "success", f"{admin}/orders/{p.get('id', '')}" if admin else "", did
    if topic == "orders/cancelled":
        return f"Order cancelled {name}", who, "warning", f"{admin}/orders/{p.get('id', '')}" if admin else "", did
    if topic == "refunds/create":
        return f"Refund on order {p.get('order_id', '')}", "", "warning", f"{admin}/orders/{p.get('order_id', '')}" if admin else "", did
    if topic == "inventory_levels/update":
        avail = p.get("available")
        level = "warning" if isinstance(avail, int) and avail <= 0 else "info"
        return f"Stock update: {avail} available", f"Item {p.get('inventory_item_id', '')}", level, f"{admin}/products" if admin else "", did
    if not topic:
        return None
    return f"Shopify: {topic}", name, "info", admin, did


def _github(p: dict, h: dict) -> Event | None:
    ev = h.get("x-github-event", "")
    did = h.get("x-github-delivery")
    repo = (p.get("repository") or {}).get("full_name", "")
    if ev == "ping":
        return f"GitHub connected: {repo or 'webhook'}", "", "success", "", did
    if ev == "push":
        commits = p.get("commits") or []
        branch = str(p.get("ref", "")).rsplit("/", 1)[-1]
        first = (commits[0].get("message", "") if commits else "").splitlines()[0:1]
        return (f"{len(commits)} commit(s) to {branch} - {repo}", first[0] if first else "", "info",
                p.get("compare", ""), did)
    if ev == "pull_request":
        pr = p.get("pull_request") or {}
        act = p.get("action", "")
        if act == "closed" and pr.get("merged"):
            act = "merged"
        if act not in ("opened", "merged", "closed", "reopened", "ready_for_review"):
            return None
        return f"PR {act}: {pr.get('title', '')} - {repo}", pr.get("user", {}).get("login", ""), "info", pr.get("html_url", ""), did
    if ev == "issues":
        iss = p.get("issue") or {}
        if p.get("action") not in ("opened", "closed", "reopened"):
            return None
        return f"Issue {p.get('action')}: {iss.get('title', '')} - {repo}", "", "info", iss.get("html_url", ""), did
    if ev == "workflow_run":
        run = p.get("workflow_run") or {}
        if p.get("action") != "completed":
            return None
        ok = run.get("conclusion") == "success"
        return (f"{run.get('name', 'Workflow')} {'passed' if ok else run.get('conclusion', 'failed')} - {repo}",
                run.get("head_branch", ""), "success" if ok else "error", run.get("html_url", ""), did)
    if ev == "release":
        rel = p.get("release") or {}
        if p.get("action") != "published":
            return None
        return f"Release {rel.get('tag_name', '')} published - {repo}", rel.get("name", ""), "success", rel.get("html_url", ""), did
    if ev == "star":
        return f"Star {p.get('action', '')} - {repo}", (p.get("sender") or {}).get("login", ""), "info", "", did
    if not ev:
        return None
    return f"GitHub: {ev} - {repo}".strip(" -"), "", "info", "", did


def _generic(p: dict, h: dict) -> Event | None:
    title = p.get("title") or p.get("subject") or p.get("event") or p.get("type")
    body = p.get("body") or p.get("message") or p.get("text") or ""
    if not title:
        compact = json.dumps(p, ensure_ascii=False)[:300]
        title, body = "Webhook received", body or compact
    level = p.get("level") if p.get("level") in feed.LEVELS else "info"
    url = p.get("url") if isinstance(p.get("url"), str) else ""
    dedupe = p.get("id") or p.get("dedupe") or h.get("x-request-id")
    return str(title), str(body), level, url, (str(dedupe) if dedupe else None)


PARSERS = {"stripe": _stripe, "shopify": _shopify, "github": _github, "generic": _generic}
