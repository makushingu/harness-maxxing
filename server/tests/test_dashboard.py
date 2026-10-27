import json
import sys
import time
import types

import pytest

from _org_helpers import client, org  # noqa: F401
from maxxing import config, crons, health


@pytest.fixture
def fakes(monkeypatch):
    """Fake sessions service + Telegram gateway (owned by other modules)."""
    now = time.time()
    svc = types.ModuleType("maxxing.sessions.service")
    svc.list_sessions = lambda path=None, archived=None: [
        {"id": "a" * 36, "title": "Blog post", "path": "projects/acme/topics/blog", "state": "running",
         "unread": False, "updated": now, "archived": False},
        {"id": "b" * 36, "title": "Old", "path": "", "state": "idle", "unread": True, "updated": now - 3 * 86400,
         "archived": False},
        {"id": "c" * 36, "title": "Archived", "path": "", "state": "idle", "unread": True, "updated": now,
         "archived": True}]
    monkeypatch.setitem(sys.modules, "maxxing.sessions.service", svc)
    import maxxing.sessions as pkg
    monkeypatch.setattr(pkg, "service", svc, raising=False)
    gw = types.ModuleType("maxxing.telegram.gateway")
    gw.status = lambda: {"configured": True, "running": True, "bot": {"username": "acme_bot"}, "last_error": None}
    monkeypatch.setitem(sys.modules, "maxxing.telegram.gateway", gw)
    import maxxing.telegram as tpkg
    monkeypatch.setattr(tpkg, "gateway", gw, raising=False)
    monkeypatch.setattr(health, "_systemctl_show_all", lambda names: {})


def _show_all():
    """Every built-in visible (the default layout hides some)."""
    from maxxing import widgets
    config.update_config(dashboard={"order": [b.id for b in widgets.BUILTINS], "hidden": []})


def _by_id(client, q=""):
    return {w["id"]: w for w in client.get("/api/dashboard" + q).json()["widgets"]}


def test_builtins(client, org, fakes):
    client.post("/api/tasks", json={"title": "Late", "due": "2000-01-01"})
    j = crons.create_job({"name": "Nightly", "command": "false"})
    crons.run_job(j["id"])
    ws = _by_id(client)
    # default layout: no usage, "Make it yours" last; duplicates and modules not set up hidden
    assert list(ws) == ["activity", "server", "day", "tasks", "crons", "backup", "telegram", "shopify", "customize"]
    assert {w for w, v in ws.items() if v["hidden"]} == {"crons", "backup", "telegram", "shopify"}
    assert ws["crons"]["card"] is None and ws["customize"]["card"]["blocks"][1]["grid"] is True
    client.put("/api/dashboard/layout", json={"order": list(ws), "hidden": []})
    ws = _by_id(client)
    for w in ws.values():
        assert w["error"] is None, (w["id"], w["error"])
        assert w["source"] == "builtin" and w["hidden"] is False and w["card"]["blocks"]
        assert "updated" in w["card"]
    act = ws["activity"]["card"]
    stats = {s["label"]: s["value"] for s in act["blocks"][0]["items"]}
    assert stats == {"Running": 1, "Unread": 1, "Today": 1}
    assert [i["title"] for i in act["blocks"][1]["items"]] == ["Blog post", "Old"]
    assert act["blocks"][1]["items"][0]["href"] == "/sessions/" + "a" * 36
    assert "tone" not in act["blocks"][0]["items"][0]                       # None values stripped
    t = ws["tasks"]["card"]
    assert t["status"] == "warn" and t["blocks"][1]["items"][0]["status"] == "error"
    c = ws["crons"]["card"]
    assert c["status"] == "error" and c["blocks"][1]["items"][0]["title"] == "Nightly"
    assert c["blocks"][2]["type"] == "chart" and len(c["blocks"][2]["series"][0]["points"]) == 14
    assert [b["type"] for b in ws["server"]["card"]["blocks"]][:3] == ["progress"] * 3
    cpu, mem, disk = ws["server"]["card"]["blocks"][:3]
    assert cpu["format"] == disk["format"] == "percent" and mem["unit"] == "GB" and "format" not in mem
    assert ws["backup"]["card"]["blocks"][0]["value"] == "Not configured"
    assert ws["telegram"]["card"]["blocks"][0]["items"][1]["value"] == "@acme_bot"


def test_missing_modules_are_isolated(client, org, monkeypatch):
    _show_all()
    monkeypatch.setitem(sys.modules, "maxxing.sessions.service", None)        # import -> ImportError
    monkeypatch.setitem(sys.modules, "maxxing.telegram.gateway", None)
    import maxxing.sessions as spkg
    import maxxing.telegram as tpkg
    monkeypatch.delattr(spkg, "service", raising=False)            # `from .x import y` uses the attribute
    monkeypatch.delattr(tpkg, "gateway", raising=False)
    monkeypatch.setattr(health, "_systemctl_show_all", lambda names: {})
    ws = _by_id(client)
    assert ws["activity"]["card"] is None and "not available" in ws["activity"]["error"]
    assert ws["telegram"]["error"] is None and ws["telegram"]["card"]["blocks"][0]["value"] == "Not configured"
    assert ws["tasks"]["error"] is None


def test_slow_widget_does_not_hold_the_page(client, org, fakes, monkeypatch):
    from maxxing.api import dashboard
    from maxxing import widgets
    monkeypatch.setattr(dashboard, "SOFT_S", 0.2)
    real = widgets.card
    calls = []

    def card(wid, force=False):
        if wid == "server":
            calls.append(wid)
            time.sleep(0.6)
        return real(wid, force)
    monkeypatch.setattr(widgets, "card", card)
    t0 = time.time()
    ws = _by_id(client)
    assert time.time() - t0 < 0.55
    assert ws["server"]["pending"] is True and ws["server"]["card"] is None and ws["server"]["error"] is None
    assert "pending" not in ws["tasks"] and ws["tasks"]["card"]
    one = client.get("/api/dashboard/widgets/server").json()           # joins the running computation
    assert one["card"]["blocks"] and "pending" not in one and calls == ["server"]


def test_french_labels(client, org, fakes):
    config.update_config(language="fr")
    ws = _by_id(client)
    assert ws["tasks"]["title"] == "Tâches" and ws["tasks"]["card"]["title"] == "Tâches"


def test_backup_and_usage(client, org, fakes, monkeypatch):
    _show_all()
    config.update_config(backup={"repo": "acme/memory"}, usage_widget=True)
    (config.state_dir("backup") / "history.jsonl").write_text(
        json.dumps({"at": time.time() - 3600, "ok": True, "files": 12, "commit": "abc"}) + "\n")
    monkeypatch.setattr(health, "_fetch_usage", lambda: {"available": True, "five_hour": {"pct": 85.0, "resets_at": "x"},
                                                          "seven_day": {"pct": 10.0, "resets_at": None}})
    ws = _by_id(client)
    b = ws["backup"]["card"]
    assert b["status"] == "ok" and b["blocks"][0]["items"][0]["value"] == "1 h ago"
    assert b["blocks"][0]["items"][1]["value"] == 12
    u = ws["usage"]["card"]
    assert u["status"] == "warn" and u["blocks"][0]["value"] == 85.0 and "hint" not in u["blocks"][1]


def test_layout_and_extensions(client, org, fakes):
    d = org.ws / "extensions" / "counter"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"name": "Counter", "type": "widget", "icon": "hash", "ttl": 300}))
    (d / "api.py").write_text("N = [0]\ndef card(ctx):\n    N[0] += 1\n    return {'blocks': [{'type': 'stat', "
                              "'label': 'n', 'value': N[0]}]}\n")
    e = org.ws / "extensions" / "crashy"
    e.mkdir()
    (e / "manifest.json").write_text(json.dumps({"type": "widget"}))
    (e / "api.py").write_text("def card(ctx):\n    raise RuntimeError('db down')\n")

    assert client.put("/api/dashboard/layout", json={"order": ["counter", "server", "counter"],
                                                     "hidden": ["backup"]}).json() == {"ok": True}
    assert config.load_config()["dashboard"] == {"order": ["counter", "server"], "hidden": ["backup"]}
    widgets = client.get("/api/dashboard").json()["widgets"]
    ids = [w["id"] for w in widgets]
    assert ids[:2] == ["counter", "server"] and "crashy" in ids
    wmap = {w["id"]: w for w in widgets}
    assert wmap["backup"]["hidden"] is True and wmap["backup"]["card"] is None
    assert wmap["counter"]["source"] == "extension" and wmap["counter"]["title"] == "Counter"
    assert wmap["counter"]["card"]["blocks"][0]["value"] == 1
    assert wmap["crashy"]["card"] is None and "db down" in wmap["crashy"]["error"]

    assert client.get("/api/dashboard/widgets/counter").json()["card"]["blocks"][0]["value"] == 1   # cached
    assert client.get("/api/dashboard/widgets/counter?force=1").json()["card"]["blocks"][0]["value"] == 2
    assert client.get("/api/dashboard/widgets/backup").json()["card"] is not None    # explicit fetch of hidden
    assert client.get("/api/dashboard/widgets/nope").status_code == 404

    client.patch("/api/extensions/counter", json={"enabled": False})
    assert "counter" not in _by_id(client)


def test_day_timeline(client, org, fakes):
    from maxxing import widgets
    hourly = crons.create_job({"name": "Hourly", "command": "true", "schedule": "0 * * * *"})
    crons.create_job({"name": "Every minute", "command": "true", "schedule": "* * * * *"})
    crons.create_job({"name": "Off", "command": "true", "schedule": "0 3 * * *", "enabled": False})
    crons.run_job(hourly["id"])
    card = widgets.day()
    stats = {s["label"]: s["value"] for s in card["blocks"][0]["items"]}
    assert stats["Runs today"] == 1 and stats["Failed today"] == 0
    tl = card["blocks"][1]
    assert tl["type"] == "timeline" and tl["end"] - tl["start"] == 86400 and tl["start"] <= tl["now"] < tl["end"]
    lanes = {l["name"]: l for l in tl["lanes"]}
    assert "Off" not in lanes                                         # disabled, never ran today
    h = lanes["Hourly"]
    assert h["dense"] is False and h["color"] and h["href"] == f"/crons?job={hourly['id']}"
    states = [e["state"] for e in h["events"]]
    assert states[0] == "ok" and set(states[1:]) <= {"planned"}
    assert all(tl["start"] <= e["at"] < tl["end"] for e in h["events"])
    assert lanes["Every minute"]["dense"] is True                     # too many runs: drawn as a band
    assert len(lanes["Every minute"]["events"]) <= widgets.MAX_PLANNED


def test_day_timeline_empty(client, org, fakes):
    from maxxing import widgets
    card = widgets.day()
    assert card["blocks"][0]["type"] == "markdown"                    # nothing today: no zero counters
    nxt = card["blocks"][1]["items"][0]                               # the next run, or how to get one
    assert nxt.get("href")


def test_crons_cards_cached_until_their_files_change(client, org, fakes, monkeypatch):
    _show_all()
    from maxxing import widgets
    j = crons.create_job({"name": "Nightly", "command": "true"})
    calls = []
    real = widgets.crons
    monkeypatch.setattr(widgets, "BUILTINS", [widgets.Builtin(b.id, b.title, b.icon, b.span,
                        (lambda f, real=real: calls.append(1) or real(f)) if b.id == "crons" else b.fn,
                        b.available, b.sig) for b in widgets.BUILTINS])
    assert _by_id(client)["crons"]["card"]["blocks"][1]["items"] == [] and len(calls) == 1
    _by_id(client)
    assert len(calls) == 1                                         # nothing changed: cached
    crons.run_job(j["id"])                                         # runs.jsonl appended (any process)
    assert _by_id(client)["crons"]["card"]["blocks"][1]["items"][0]["title"] == "Nightly" and len(calls) == 2
    config.update_config(language="fr")                            # labels follow the language at once
    assert _by_id(client)["crons"]["card"]["title"] == "Tâches planifiées" and len(calls) == 3
    _by_id(client, "?force=1")
    assert len(calls) == 4                                         # force recomputes
    monkeypatch.setattr(widgets, "CARD_CACHE_S", 0)
    _by_id(client)
    assert len(calls) == 5                                         # at most CARD_CACHE_S old


def test_default_layout_and_customize(client, org, fakes, monkeypatch):
    from maxxing import extensions, shopify as shop
    # a saved layout is kept as it is; a widget it does not know comes after, "Make it yours" stays last
    client.put("/api/dashboard/layout", json={"order": ["server", "activity"], "hidden": ["activity"]})
    d = config.workspace() / "extensions" / "sales"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"id": "sales", "name": {"en": "Sales", "fr": "Ventes"}, "type": "widget"}))
    (d / "api.py").write_text("def card(ctx):\n    return {'title': 'Sales', 'blocks': []}\n")
    extensions.scan()
    ws = client.get("/api/dashboard").json()["widgets"]
    ids = [w["id"] for w in ws]
    assert ids[:2] == ["server", "activity"] and ids[-2:] == ["sales", "customize"]
    assert {w["id"] for w in ws if w["hidden"]} == {"activity"}
    config.update_config(language="fr")
    assert next(w for w in client.get("/api/dashboard").json()["widgets"] if w["id"] == "sales")["title"] == "Ventes"
    assert next(e for e in client.get("/api/extensions").json() if e["id"] == "sales")["name"] == "Ventes"
    # Shopify set up: shown by default
    config.update_config(dashboard={"order": [], "hidden": []})
    monkeypatch.setattr(shop, "configured", lambda: True)
    assert not next(w for w in client.get("/api/dashboard").json()["widgets"] if w["id"] == "shopify")["hidden"]
    # the examples open a new session in the Harness topic with the request typed in
    card = client.get("/api/dashboard/widgets/customize").json()["card"]
    hrefs = [i["href"] for i in card["blocks"][1]["items"]]
    assert len(hrefs) == 6 and all(h.startswith("/sessions?path=projects/system/topics/harness&new=1&prompt=") for h in hrefs)
    # icons of the app, not emoji (the built-in cards look like the rest of the UI)
    assert all(i["icon"] and "emoji" not in i for i in card["blocks"][1]["items"])


def test_reduced_motion_drops_the_entrance_delays():
    # the dashboard charts fade in with `backwards` fill and delays up to ~0.7 s: with "reduce motion" the
    # delays must go too, or the dots and bars stay invisible for that long
    from pathlib import Path
    css = (Path(__file__).resolve().parents[2] / "web/src/styles/globals.css").read_text()
    block = css.split("@media (prefers-reduced-motion: reduce)", 1)[1].split("\n}\n", 1)[0]
    assert "animation-delay: 0ms !important" in block


def test_dashboard_scans_the_extensions_folder_once_per_request(client, org, fakes, monkeypatch):
    from maxxing import extensions
    for i in range(6):
        d = org.ws / "extensions" / f"w{i}"
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({"type": "widget"}))
        (d / "api.py").write_text("def card(ctx):\n    return {'blocks': []}\n")
    _by_id(client)                                     # first scan
    calls = []
    real = extensions._signature
    monkeypatch.setattr(extensions, "_signature", lambda: calls.append(1) or real())
    widgets = _by_id(client)
    assert all(widgets[f"w{i}"]["card"] is not None for i in range(6))
    assert all("_ext" not in w for w in widgets.values())
    assert len(calls) == 1                             # was 1 + one per extension widget
    assert _by_id(client) and len(calls) == 2
    assert client.get("/api/dashboard/widgets/w0").json()["card"] is not None and len(calls) == 3


def test_a_stuck_card_holds_one_thread_however_often_it_is_reloaded(client, org, fakes, monkeypatch, tmp_path):
    from maxxing import extensions
    from maxxing.api import dashboard
    monkeypatch.setattr(dashboard, "TIMEOUT_S", 0.2)
    flag = tmp_path / "release"
    d = org.ws / "extensions" / "slow"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"type": "widget"}))
    (d / "api.py").write_text("import os, time\n\ndef card(ctx):\n    end = time.time() + 10\n"
                              f"    while not os.path.exists({str(flag)!r}) and time.time() < end:\n"
                              "        time.sleep(0.02)\n    return {'blocks': []}\n")
    try:
        errors = [client.get("/api/dashboard/widgets/slow").json()["error"]
                  for _ in range(extensions.EXT_WORKERS + 1)]
        assert errors[0].startswith("timed out") and all("previous call" in e for e in errors[1:])
        assert extensions._stuck == 1                  # was one more taken thread per reload, then "busy"
    finally:
        flag.write_text("")
    for _ in range(100):
        if extensions._stuck == 0:
            break
        time.sleep(0.05)
    assert extensions._stuck == 0 and not extensions._stuck_keys
    assert client.get("/api/dashboard/widgets/slow").json()["card"] is not None
