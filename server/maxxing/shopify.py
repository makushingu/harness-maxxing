"""Built-in Shopify widget: today's sales, orders to ship, 14-day revenue, latest orders.

Connect a store with two keys in Settings -> Keys (the vault):
  SHOPIFY_STORE         the shop domain, e.g. myshop.myshopify.com
  SHOPIFY_ADMIN_TOKEN   an Admin API access token (shpat_...) with the read_orders scope
The Admin GraphQL API is read-only here. Results are cached CACHE_S seconds.
MAXXING_SHOPIFY_API overrides the base URL (tests, demo).
"""
from __future__ import annotations

import datetime as dt
import os
import threading
import time
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from . import config

API_VERSION = "2025-01"
CACHE_S = 120
DAYS = 14
STORE_KEY, TOKEN_KEY = "SHOPIFY_STORE", "SHOPIFY_ADMIN_TOKEN"
QUERY = """query($q: String!, $after: String) {
  shop { name currencyCode }
  orders(first: 250, after: $after, sortKey: CREATED_AT, reverse: true, query: $q) {
    pageInfo { hasNextPage endCursor }
    edges { node { name createdAt displayFulfillmentStatus cancelledAt
      totalPriceSet { shopMoney { amount currencyCode } } } }
  }
}"""

_T = {"fr": {"Shopify": "Shopify", "Revenue today": "CA du jour", "Orders today": "Commandes du jour",
             "To ship": "À expédier", "Last 7 days": "7 derniers jours", "Revenue": "Chiffre d'affaires",
             "Latest orders": "Dernières commandes", "No order yet": "Aucune commande pour l'instant",
             "Connect your store": "Connecter votre boutique", "unfulfilled": "à expédier",
             "fulfilled": "expédiée", "vs previous 7 days": "vs 7 jours précédents"}}
_cache: dict[str, Any] = {"at": 0.0, "key": None, "card": None}
_lock = threading.Lock()


def t(s: str) -> str:
    return _T.get(config.load_config().get("language", "en"), {}).get(s, s)


def credentials() -> tuple[str, str]:
    from . import vault
    store = (vault.get(STORE_KEY) or "").strip().removeprefix("https://").strip("/")
    return store, (vault.get(TOKEN_KEY) or "").strip()


def configured() -> bool:
    store, token = credentials()
    return bool(store and token)


def _url(store: str) -> str:
    base = os.environ.get("MAXXING_SHOPIFY_API") or f"https://{store}"
    return f"{base.rstrip('/')}/admin/api/{API_VERSION}/graphql.json"


def fetch(store: str, token: str, since: dt.date) -> dict[str, Any]:
    """-> {shop, currency, orders:[{name, at, total, fulfilled}]} (raises RuntimeError with a readable reason)."""
    orders, after, shop, cur = [], None, store, ""
    with httpx.Client(timeout=12) as c:
        for _ in range(4):                                   # up to 1000 orders over the window
            try:
                r = c.post(_url(store), json={"query": QUERY, "variables": {"q": f"created_at:>={since.isoformat()}", "after": after}},
                           headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"})
            except httpx.HTTPError as e:
                raise RuntimeError(f"cannot reach {store} ({type(e).__name__})") from None
            if r.status_code in (401, 403):
                raise RuntimeError("the store refused the token (check SHOPIFY_ADMIN_TOKEN and the read_orders scope)")
            if r.status_code >= 400:
                raise RuntimeError(f"Shopify answered HTTP {r.status_code}")
            try:
                body = r.json()
            except ValueError:
                body = None
            if not isinstance(body, dict):
                raise RuntimeError("Shopify sent an unreadable answer")
            if body.get("errors"):
                raise RuntimeError(str(body["errors"])[:200])
            data = body.get("data") or {}
            shop = (data.get("shop") or {}).get("name") or shop
            cur = (data.get("shop") or {}).get("currencyCode") or cur
            page = data.get("orders") or {}
            for e in page.get("edges") or []:
                n = e.get("node") or {}
                if n.get("cancelledAt"):
                    continue
                money = ((n.get("totalPriceSet") or {}).get("shopMoney") or {})
                orders.append({"name": str(n.get("name") or ""), "at": str(n.get("createdAt") or ""),
                               "total": float(money.get("amount") or 0),
                               "fulfilled": n.get("displayFulfillmentStatus") == "FULFILLED"})
            info = page.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                break
            after = info.get("endCursor")
    return {"shop": shop, "currency": cur, "orders": orders}


def _money(v: float, cur: str) -> str:
    sym = {"EUR": "€", "USD": "$", "GBP": "£"}.get(cur, "")
    s = f"{v:,.0f}" if v >= 1000 else f"{v:,.2f}".rstrip("0").rstrip(".")
    return f"{sym}{s}" if sym and cur != "EUR" else f"{s} {sym or cur}".strip()


def build_card(data: dict[str, Any], today: dt.date, tz: ZoneInfo) -> dict:
    cur = data["currency"]
    by_day: dict[dt.date, float] = {today - dt.timedelta(days=i): 0.0 for i in range(DAYS)}
    count_today, to_ship = 0, 0
    for o in data["orders"]:
        try:
            d = dt.datetime.fromisoformat(o["at"].replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            continue
        if d in by_day:
            by_day[d] += o["total"]
        if d == today:
            count_today += 1
        if not o["fulfilled"]:
            to_ship += 1
    last7 = sum(v for d, v in by_day.items() if (today - d).days < 7)
    prev7 = sum(v for d, v in by_day.items() if 7 <= (today - d).days < 14)
    delta = f"{(last7 - prev7) / prev7 * 100:+.0f} %" if prev7 else None
    points = [[d.isoformat(), round(by_day[d], 2)] for d in sorted(by_day)]
    latest = [{"title": o["name"], "subtitle": o["at"][:16].replace("T", " "), "value": _money(o["total"], cur),
               "status": "ok" if o["fulfilled"] else "warn"} for o in data["orders"][:4]]
    return {"title": f"{t('Shopify')} · {data['shop']}", "link": "/settings/keys",
            "status": "warn" if to_ship > 10 else "ok",
            "blocks": [
                {"type": "stats", "items": [
                    {"type": "stat", "label": t("Revenue today"), "value": _money(by_day[today], cur)},
                    {"type": "stat", "label": t("Orders today"), "value": count_today},
                    {"type": "stat", "label": t("To ship"), "value": to_ship, "tone": "warn" if to_ship else None},
                    {"type": "stat", "label": t("Last 7 days"), "value": _money(last7, cur), "delta": delta,
                     "hint": t("vs previous 7 days") if delta else None}]},
                {"type": "chart", "kind": "bar", "series": [{"name": t("Revenue"), "points": points}], "unit": cur},
                {"type": "list", "items": latest, "empty": t("No order yet")},
            ]}


def connect_card() -> dict:
    return {"title": t("Shopify"), "link": "/settings/keys", "blocks": [
        {"type": "stat", "label": t("Connect your store"), "value": "—"},
        {"type": "markdown", "text": (
            "Add **SHOPIFY_STORE** (`myshop.myshopify.com`) and **SHOPIFY_ADMIN_TOKEN** (Admin API token, "
            "`read_orders`) in [Settings → Keys](/settings/keys) — or ask Harness: *connect my Shopify store*."
            if config.load_config().get("language", "en") != "fr" else
            "Ajoutez **SHOPIFY_STORE** (`maboutique.myshopify.com`) et **SHOPIFY_ADMIN_TOKEN** (token Admin API, "
            "`read_orders`) dans [Réglages → Clés](/settings/keys), ou demandez à Harness : *connecte ma boutique Shopify*.")},
    ]}


def card(force: bool = False) -> dict:
    store, token = credentials()
    if not (store and token):
        return connect_card()
    key = (store, token[-6:])
    with _lock:
        if not force and _cache["key"] == key and time.time() - _cache["at"] < CACHE_S and _cache["card"]:
            return _cache["card"]
    tz = ZoneInfo(config.load_config().get("timezone") or "UTC")
    today = dt.datetime.now(tz).date()
    try:
        data = fetch(store, token, today - dt.timedelta(days=DAYS - 1))
    except RuntimeError as e:
        return {"title": t("Shopify"), "link": "/settings/keys", "status": "error",
                "blocks": [{"type": "markdown", "text": f"{store}: {e}"}]}
    c = build_card(data, today, tz)
    with _lock:
        _cache.update(at=time.time(), key=key, card=c)
    return c
