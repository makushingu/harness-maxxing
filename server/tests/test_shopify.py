import datetime as dt
import json
from zoneinfo import ZoneInfo

import httpx

from maxxing import shopify, vault


def _order(name, days_ago, total, fulfilled=False, today=dt.date(2026, 10, 12)):
    d = today - dt.timedelta(days=days_ago)
    return {"node": {"name": name, "createdAt": f"{d.isoformat()}T10:00:00Z", "cancelledAt": None,
                     "displayFulfillmentStatus": "FULFILLED" if fulfilled else "UNFULFILLED",
                     "totalPriceSet": {"shopMoney": {"amount": str(total), "currencyCode": "EUR"}}}}


def test_build_card_figures():
    data = {"shop": "My Coffee Shop", "currency": "EUR", "orders": [
        {"name": "#1050", "at": "2026-10-12T09:00:00Z", "total": 42.0, "fulfilled": False},
        {"name": "#1049", "at": "2026-10-12T08:00:00Z", "total": 18.0, "fulfilled": True},
        {"name": "#1040", "at": "2026-10-09T08:00:00Z", "total": 40.0, "fulfilled": True},
        {"name": "#1030", "at": "2026-10-01T08:00:00Z", "total": 50.0, "fulfilled": True},
    ]}
    c = shopify.build_card(data, dt.date(2026, 10, 12), ZoneInfo("UTC"))
    stats = {s["label"]: s for s in c["blocks"][0]["items"]}
    assert stats["Revenue today"]["value"] == "60 €" and stats["Orders today"]["value"] == 2
    assert stats["To ship"]["value"] == 1 and stats["Last 7 days"]["value"] == "100 €"
    assert stats["Last 7 days"]["delta"] == "+100 %"                    # 100 vs 50 the week before
    pts = c["blocks"][1]["series"][0]["points"]
    assert len(pts) == 14 and pts[-1] == ["2026-10-12", 60.0]
    assert [i["title"] for i in c["blocks"][2]["items"]] == ["#1050", "#1049", "#1040", "#1030"]


def test_card_needs_connection_then_fetches(mx, monkeypatch):
    shopify._cache.update(at=0, key=None, card=None)
    c = shopify.card()
    assert "SHOPIFY_STORE" in c["blocks"][1]["text"]
    vault.put("SHOPIFY_STORE", "myshop.myshopify.com")
    vault.put("SHOPIFY_ADMIN_TOKEN", "shpat_test")
    seen = []

    def handler(req: httpx.Request):
        seen.append((str(req.url), req.headers.get("X-Shopify-Access-Token"), json.loads(req.content)["variables"]))
        page2 = json.loads(req.content)["variables"]["after"] == "c1"
        return httpx.Response(200, json={"data": {"shop": {"name": "My Coffee Shop", "currencyCode": "EUR"}, "orders": {
            "pageInfo": {"hasNextPage": not page2, "endCursor": "c1"},
            "edges": [_order("#2", 0, 30)] if page2 else [_order("#1", 0, 12, True)]}}})
    real = httpx.Client
    monkeypatch.setattr(shopify.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    c = shopify.card(force=True)
    assert c["title"] == "Shopify · My Coffee Shop" and len(seen) == 2              # paginated
    assert seen[0][0] == "https://myshop.myshopify.com/admin/api/2025-01/graphql.json" and seen[0][1] == "shpat_test"
    assert seen[0][2]["q"].startswith("created_at:>=")
    assert shopify.card()["title"] == c["title"] and len(seen) == 2                # cached


def test_refused_token_is_a_readable_error(mx, monkeypatch):
    shopify._cache.update(at=0, key=None, card=None)
    vault.put("SHOPIFY_STORE", "https://myshop.myshopify.com/")
    vault.put("SHOPIFY_ADMIN_TOKEN", "bad")
    real = httpx.Client
    monkeypatch.setattr(shopify.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(401)), **kw))
    c = shopify.card(force=True)
    assert c["status"] == "error" and "refused the token" in c["blocks"][0]["text"] and "myshop.myshopify.com:" in c["blocks"][0]["text"]
