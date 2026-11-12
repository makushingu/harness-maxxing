"""Enterprises: digest, weekly / monthly reports, Overview, owner notifications (maxxing/enterprise_reports.py)."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
import time
import types

import httpx
import pytest

from _conn_helpers import (TG_TOKEN, FakeService, FakeTelegram, FakeWorkspace, bare_app,  # noqa: F401
                           mx_state, wait_for)
from maxxing import agents, config, enterprise_reports as reports, enterprises, feed
from maxxing.api import telegram as tg_api
from maxxing.sessions import service as real_service, store as real_store, titles  # noqa: F401 - before the fakes
from maxxing.telegram import gateway

E = "/api/enterprises"
S = "acme-group"
TOPIC = "projects/acme/topics/blog"
W = TOPIC + "/agents/writer"
R = TOPIC + "/agents/editor"


# ---- helpers ---------------------------------------------------------------------------------------------
def _setup(client, topic, **patch):
    """Enterprise `acme-group`: lead (editor) over writer, both in the department `content`."""
    assert client.put("/api/settings", json={"agents_page": True, "enterprises_page": True}).status_code == 200
    config.update_config(timezone="UTC")
    for n in ("writer", "editor"):
        assert client.post("/api/agents", json={"topic_path": topic, "name": n, "sandbox": False}).status_code == 200
    assert client.post(E, json={"id": S, "name": "Acme Group", "emoji": "🏢", "projects": ["acme"]}).status_code == 200
    for pid, agent, up in (("lead", R, None), ("writer", W, "lead")):
        r = client.post(f"{E}/{S}/positions", json={"id": pid, "title": pid.title(), "reports_to": up,
                                                     "department": "content", "agent": agent})
        assert r.status_code == 200, r.text
    body = {"departments": {"content": {"name": "Content"}}, **patch}
    assert client.patch(f"{E}/{S}", json=body).status_code == 200


def _calls(mx) -> list[dict]:
    f = mx["fake_dir"] / "calls.jsonl"
    return [json.loads(ln) for ln in f.read_text().splitlines()] if f.exists() else []


def _tasks(mx, *tasks) -> None:
    now = time.time()
    rows = [{"id": f"t{i}", "title": t.pop("title"), "status": t.pop("status", "doing"), "created": now - 60,
             "updated": now - 60, "enterprise": {"id": S, "owner": t.pop("owner"), "requester": "", "parent": "",
                                                  "deliverable": "", "stage": t.pop("stage", ""), "hops": 1,
                                                  "outside": False}, **t} for i, t in enumerate(tasks)]
    (mx["ws"] / "tasks.json").write_text(json.dumps({"version": 1, "projects": [], "tasks": rows}))


def _quiet(monkeypatch, esc=(), req=()):
    monkeypatch.setattr(reports, "_open_escalations", lambda slug: list(esc))
    monkeypatch.setattr(reports, "_waiting_requests", lambda slug: list(req))


def _events() -> list[dict]:
    return feed.list_events(source="enterprises")["events"]


def _ts(y, mo, d, h, mi=0) -> float:
    return dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc).timestamp()


# ---- collection ---------------------------------------------------------------------------------------------
def test_collect_since_the_cursor(client, topic, mx, monkeypatch):
    _setup(client, topic)
    now = time.time()
    _quiet(monkeypatch, esc=[{"id": "e1", "position": "writer", "text": "Need a call", "at": now}],
           req=[{"id": "r1", "position": "lead", "text": "Buy a font", "at": now - 90000}])
    agents.post(W, "result", "# Draft one done\nlong body", ok=True)
    agents.post(W, "result", "second", ok=True)
    agents.post(W, "result", "boom", ok=False)
    agents.post(W, "skip", "budget", reason="budget")
    _tasks(mx, {"title": "Spring kit", "owner": "writer", "status": "done", "done_at": now - 10},
           {"title": "New article", "owner": "writer"},
           {"title": "Old one", "owner": "writer", "due": "2020-01-01"})
    d = enterprises.load(S)
    c = reports._collect(S, d, now - 3600, now + 1)
    w = next(r for r in c["positions"] if r["id"] == "writer")
    assert w["results"] == ["Draft one done", "second"] and w["failed"] == 1 and w["skipped"] == 1
    assert w["done"] == ["Spring kit"] and w["opened"] == ["New article", "Old one"] and w["late"] == ["Old one"]
    assert c["new"] and len(c["escalations"]) == 1 and len(c["requests"]) == 1
    text = reports._lines(c, d)
    assert "## Content" in text and "result: Draft one done" in text and "Escalations open (1)" in text
    # nothing after the cursor: nothing new (the old escalation / request alone do not count)
    assert reports._collect(S, d, now + 5, now + 6)["new"] is False


def test_titles_only_drops_the_excerpts(client, topic, mx, monkeypatch):
    _setup(client, topic)
    _quiet(monkeypatch, esc=[{"id": "e1", "position": "writer", "text": "secret detail", "at": time.time()}])
    agents.post(W, "result", "private excerpt")
    _tasks(mx, {"title": "Visible title", "owner": "writer"})
    d = enterprises.load(S)
    c = reports._collect(S, d, time.time() - 120, time.time() + 1, titles_only=True)
    text = reports._lines(c, d)
    assert "private excerpt" not in text and "secret detail" not in text
    assert "1 result" in text and "Visible title" in text


# ---- the digest ------------------------------------------------------------------------------------------
def test_nothing_new_is_no_call_and_no_message(client, topic, mx, monkeypatch):
    _setup(client, topic)
    _quiet(monkeypatch)
    assert reports.build(S, "daily", time.time(), send=True) is None
    assert _calls(mx) == [] and reports.reports(S) == []
    assert _events() == []


def test_digest_one_call_saved_charged_and_announced(client, topic, mx, monkeypatch):
    _setup(client, topic)
    _quiet(monkeypatch)
    agents.post(W, "result", "Draft done")
    t = time.time() + 1
    r = reports.build(S, "daily", t, send=True)
    assert r and r["kind"] == "daily" and r["raw"] is False and r["cost"] > 0 and r["text"]
    calls = _calls(mx)
    assert len(calls) == 1 and "--tools" in calls[0]["argv"] and "Draft done" in calls[0]["prompt"]
    saved = (config.state_dir("enterprises") / S / "reports" / f"{r['name']}.md").read_text()
    assert saved.startswith("# Daily digest - Acme Group") and r["text"] in saved
    assert reports.report(S, r["name"])["text"].startswith("# Daily digest")
    assert reports.reports(S)[0]["name"] == r["name"] and reports.reports(S)[0]["cost"] == r["cost"]
    ev = _events()
    assert len(ev) == 1 and ev[0]["source"] == "enterprises" and ev[0]["title"].startswith("Daily digest")
    assert reports.overview(S)["digest_cost"] == r["cost"]
    assert reports.overview(S)["digest"]["text"].startswith("# Daily digest")
    # the cursor moved: the same activity is not reported twice
    assert reports.build(S, "daily", t + 5) is None and len(_calls(mx)) == 1


def test_ceiling_reached_sends_the_raw_list(client, topic, mx, monkeypatch):
    _setup(client, topic, envelope={"usd_per_day": 1})
    _quiet(monkeypatch)
    monkeypatch.setattr(agents, "day_cost", lambda path, when=None, metas=None, cold=False: 5.0)
    agents.post(W, "result", "Draft done")
    r = reports.build(S, "daily", time.time() + 1)
    assert r["raw"] is True and r["cost"] == 0 and "Draft done" in r["text"] and "budget is reached" in r["text"]
    assert _calls(mx) == []


def test_a_failed_call_falls_back_to_the_raw_list(client, topic, mx, monkeypatch):
    _setup(client, topic)
    _quiet(monkeypatch)
    agents.post(W, "result", "FAIL please")
    r = reports.build(S, "daily", time.time() + 1)
    assert r["raw"] is True and "FAIL please" in r["text"] and r["cost"] == 0


def test_per_lead_adds_one_call_per_lead(client, topic, mx, monkeypatch):
    _setup(client, topic, settings={"digest": {"per_lead": True}})
    _quiet(monkeypatch)
    agents.post(W, "result", "Draft done")
    r = reports.build(S, "daily", time.time())
    assert len(_calls(mx)) == 2 and "### Lead" in r["text"] and r["cost"] > 0.0123
    # without the option: one call
    client.patch(f"{E}/{S}", json={"settings": {"digest": {"per_lead": False}}})
    time.sleep(0.02)
    agents.post(W, "result", "More")
    reports.build(S, "daily", time.time() + 100)
    assert len(_calls(mx)) == 3


# ---- weekly / monthly and the tick --------------------------------------------------------------------------
def test_weekly_report_has_objectives_and_cost(client, topic, mx, monkeypatch):
    _setup(client, topic, objectives=[{"id": "o1", "text": "Ship 10 articles", "target": 10, "unit": "articles", "value": 4}])
    _quiet(monkeypatch)
    monkeypatch.setattr(agents, "day_cost", lambda path, when=None, metas=None, cold=False: 0.5)
    r = reports.build(S, "weekly", time.time())
    assert r["kind"] == "weekly" and r["name"].endswith("-weekly")
    prompt = _calls(mx)[0]["prompt"]
    assert "Ship 10 articles: 4 / 10 articles (40 %)" in prompt and "Content: $7.00" in prompt


def test_tick_schedule_is_once_per_period_and_survives_a_restart(client, topic, mx, monkeypatch):
    _setup(client, topic, settings={"digest": {"enabled": True, "hour": 18}, "weekly": True, "monthly": True})
    built = []
    monkeypatch.setattr(reports, "build", lambda slug, kind="daily", now=None, send=False: built.append((kind, send)))
    mon = _ts(2026, 11, 9, 7)                          # a Monday, 07:00
    reports.tick(mon)
    assert built == []                                  # before 08:00 and before 18:00
    reports.tick(mon + 3600 * 2)                        # Monday 09:00: the weekly review
    assert built == [("weekly", True)]
    reports.tick(mon + 3600 * 3)
    assert built == [("weekly", True)]                  # once per week
    reports.tick(mon + 3600 * 11)                       # 18:00: the daily digest
    assert built == [("weekly", True), ("daily", True)]
    reports.tick(mon + 3600 * 12)
    assert len(built) == 2
    reports.tick(_ts(2026, 11, 10, 9))                  # Tuesday morning: nothing before 18:00
    assert len(built) == 2
    assert reports._index(S)["done"] == {"weekly": "2026-W46", "daily": "2026-11-09"}   # what a restart reads
    reports.tick(_ts(2026, 12, 1, 9))                   # the 1st (a Tuesday): the monthly report
    assert built[-1] == ("monthly", True) and len(built) == 3
    reports.tick(_ts(2026, 12, 1, 10))
    assert len(built) == 3


def test_tick_does_nothing_while_the_feature_is_off(client, topic, monkeypatch):
    _setup(client, topic, settings={"digest": {"enabled": True, "hour": 0}})
    built = []
    monkeypatch.setattr(reports, "build", lambda *a, **k: built.append(1))
    client.put("/api/settings", json={"enterprises_page": False})
    reports.tick(_ts(2026, 11, 9, 12))
    assert built == []


# ---- overview and routes ------------------------------------------------------------------------------------
def test_overview_numbers(client, topic, mx, monkeypatch):
    _setup(client, topic, departments={"content": {"name": "Content", "envelope": {"usd_per_day": 3}}},
           objectives=[{"id": "o1", "text": "Ship", "target": 4, "unit": "", "value": 1}])
    esc = [{"id": "e1", "position": "writer", "text": "x", "at": 1}]
    _quiet(monkeypatch, esc=esc, req=[{"id": "r1"}, {"id": "r2"}])
    monkeypatch.setattr(agents, "day_cost", lambda path, when=None, metas=None, cold=False: {W: 1.25, R: 0.5}.get(path, 0))
    _tasks(mx, {"title": "a", "owner": "writer"}, {"title": "b", "owner": "writer", "due": "2020-01-01"},
           {"title": "c", "owner": "lead", "stage": "blocked"}, {"title": "d", "owner": "lead", "status": "done"})
    o = client.get(f"{E}/{S}/overview").json()
    assert o["cost_today"] == 1.75 and o["digest"] is None and o["digest_cost"] == 0
    assert o["requests_waiting"] == 2 and o["escalations_open"] == 1
    dept = next(x for x in o["departments"] if x["id"] == "content")
    assert dept == {"id": "content", "name": "Content", "cost_today": 1.75, "ceiling": 3.0, "open_tasks": 3,
                    "late_tasks": 1, "blocked": 1}
    assert o["objectives"][0]["progress"] == 25


def test_routes(client, topic, mx, monkeypatch):
    _setup(client, topic)
    _quiet(monkeypatch)
    assert client.post(f"{E}/{S}/reports", json={"kind": "yearly"}).json()["error"] == "invalid_kind"
    r = client.post(f"{E}/{S}/reports", json={"kind": "daily"}).json()
    assert r == {"built": False, "report": None}
    agents.post(W, "result", "Draft done")
    time.sleep(0.01)
    r = client.post(f"{E}/{S}/reports", json={"kind": "daily"}).json()
    assert r["built"] and r["report"]["kind"] == "daily"
    name = r["report"]["name"]
    assert client.get(f"{E}/{S}/reports").json()["items"][0]["name"] == name
    g = client.get(f"{E}/{S}/reports/{name}").json()
    assert g["kind"] == "daily" and g["text"].startswith("# Daily digest")
    assert client.get(f"{E}/{S}/reports/..%2Fenterprise").status_code == 404
    assert client.get(f"{E}/{S}/reports/2026-01-01-daily").json()["error"] == "not_found"
    assert client.get(f"{E}/nope/overview").status_code == 404
    client.put("/api/settings", json={"enterprises_page": False})
    for res in (client.get(f"{E}/{S}/overview"), client.get(f"{E}/{S}/reports"), client.post(f"{E}/{S}/reports", json={})):
        assert res.status_code == 404 and res.json()["error"] == "feature_off"


# ---- the owner notification and the enterprise thread -----------------------------------------------------------
@pytest.fixture
def tg(mx_state, monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setenv("MAXXING_TELEGRAM_API", fake.url)
    yield fake
    fake.close()


@pytest.fixture
def svc(monkeypatch):
    s = FakeService()
    monkeypatch.setitem(sys.modules, "maxxing.sessions.service", s)
    return s


@pytest.fixture
def ws(mx_state, monkeypatch):
    w = FakeWorkspace(mx_state / "ws", [("acme", "blog")])
    monkeypatch.setitem(sys.modules, "maxxing.workspace", w)
    f = mx_state / "ws" / "enterprises" / S
    f.mkdir(parents=True)
    (f / "enterprise.json").write_text(json.dumps({"version": 1, "name": "Acme Group", "emoji": "🚀"}))
    return w


@pytest.fixture
async def api(tg, svc, ws, monkeypatch):
    monkeypatch.setattr(gateway, "_hooks", False)
    app = bare_app(tg_api.router)
    await tg_api.startup()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await tg_api.shutdown()


async def _link(api, tg) -> None:
    assert (await api.post("/api/telegram/token", json={"token": TG_TOKEN})).status_code == 200
    link = (await api.post("/api/telegram/link")).json()
    tg.message(f"/start {link['code']}")
    await wait_for(lambda: gateway.link_status()["linked"], what="link")
    await wait_for(lambda: len(gateway.tg_config()["threads"]) == 3, what="threads")


def _flow(monkeypatch, **fns):
    mod = types.ModuleType("maxxing.enterprise_flow")
    for k, v in fns.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, "maxxing.enterprise_flow", mod)


async def test_notify_owner_feed_and_the_thread(api, tg):
    await _link(api, tg)
    await asyncio.to_thread(reports.notify_owner, S, "Daily digest", "**Done:** three posts", dedupe="d1")
    ev = _events()
    assert len(ev) == 1 and ev[0]["title"] == "Daily digest"
    tid = gateway.enterprise_threads()[S]["tid"]
    assert tg.topics[tid] == "🏢 Acme Group"
    msgs = [p for p in tg.sent() if p.get("message_thread_id") == tid]
    assert "the digest and what needs you" in msgs[0]["text"]
    assert msgs[-1]["text"].startswith("<b>Daily digest</b>") and "<b>Done:</b> three posts" in msgs[-1]["text"]
    assert msgs[-1].get("disable_notification") is True
    # the same dedupe key: not posted twice, nothing sent twice
    n = len(tg.sent())
    await asyncio.to_thread(reports.notify_owner, S, "Daily digest", "again", dedupe="d1")
    assert len(tg.sent()) == n and len(_events()) == 1
    # an alert with buttons: loud, with the keyboard, in the same thread
    await asyncio.to_thread(reports.notify_owner, S, "Escalation: need a decision", "Options A or B", level="warning",
                            ref=f"enterprise:esc:{S}:e1", actions=[{"id": "open", "label": "Open", "style": "link"},
                                                                   {"id": "seen", "label": "Seen"}])
    last = tg.sent()[-1]
    assert last["message_thread_id"] == tid and not last.get("disable_notification")
    assert "Escalation: need a decision" in last["text"] and "reply_markup" in last
    assert len(tg.sent("createForumTopic")) == 4        # three specials and the enterprise, once
    # renamed with the enterprise
    (config.workspace() / "enterprises" / S / "enterprise.json").write_text(json.dumps({"version": 1, "name": "Acme Inc"}))
    await asyncio.to_thread(reports.notify_owner, S, "Again", "x")
    assert tg.topics[tid] == "🏢 Acme Inc"


async def test_a_reply_in_the_thread_answers_the_escalation(api, tg, monkeypatch):
    await _link(api, tg)
    got = []
    _flow(monkeypatch, answer_from_telegram=lambda slug, ref, text: got.append((slug, ref, text)) or "Answered.")
    await asyncio.to_thread(reports.notify_owner, S, "Escalation", "Which one?", level="warning",
                            ref=f"enterprise:esc:{S}:e1", actions=[{"id": "seen", "label": "Seen"}])
    tid = gateway.enterprise_threads()[S]["tid"]
    mid = next(k for k, v in gateway._msgs_all().items() if v.get("enterprise") == S).split(":")[1]
    tg.message("Go with A", thread=tid, reply_to_message={"message_id": int(mid), "from": {"id": 1, "is_bot": True},
                                                          "text": "Escalation"})
    await wait_for(lambda: got, what="answer")
    assert got == [(S, f"enterprise:esc:{S}:e1", "Go with A")]
    await wait_for(lambda: tg.sent()[-1]["text"] == "Answered.", what="note")
    # a plain message in the thread: no ref, the replied text is empty
    tg.message("anything", thread=tid)
    await wait_for(lambda: len(got) == 2, what="second")
    assert got[1] == (S, "", "anything")


async def test_simple_mode_main_chat_and_reply_routing(api, tg, monkeypatch):
    await _link(api, tg)
    await asyncio.sleep(1.0)                           # the sync that follows the link ends first
    gateway.update_state(topics_enabled=False)
    answered = []
    _flow(monkeypatch, answer=lambda slug, esc, text, **k: answered.append((slug, esc, text)))
    await asyncio.to_thread(reports.notify_owner, S, "Escalation", "Which one?", level="warning",
                            ref=f"enterprise:esc:{S}:e7", actions=[{"id": "seen", "label": "Seen"}])
    p = tg.sent()[-1]
    assert p.get("message_thread_id") is None and p["text"].startswith("🚀 <b>Acme Group</b>\n")
    assert S not in gateway.enterprise_threads()
    mid, bind = next((k.split(":")[1], v) for k, v in gateway._msgs_all().items() if v.get("enterprise") == S)
    assert bind["ref"] == f"enterprise:esc:{S}:e7"
    tg.message("Option B", reply_to_message={"message_id": int(mid), "from": {"id": 1, "is_bot": True}, "text": "x"})
    await wait_for(lambda: answered, what="answer in simple mode")
    assert answered == [(S, "e7", "Option B")]            # no answer_from_telegram: the escalation id of the ref
    await wait_for(lambda: tg.sent()[-1]["text"] == "✅ Answer sent.", what="confirmation")
    # a reply to a digest (no escalation ref) answers nothing: a note, no call
    await asyncio.to_thread(reports.notify_owner, S, "Digest", "text")
    mid2 = list(gateway._msgs_all())[-1].split(":")[1]
    tg.message("thanks", reply_to_message={"message_id": int(mid2), "from": {"id": 1, "is_bot": True}, "text": "Digest"})
    await wait_for(lambda: "Reply to the message of an escalation" in tg.sent()[-1]["text"], what="note")
    assert len(answered) == 1


def test_telegram_answer_without_the_flow_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "maxxing.enterprise_flow", types.ModuleType("maxxing.enterprise_flow"))
    assert reports.telegram_answer(S, f"enterprise:esc:{S}:e1", "", "yes") == ("none", "")

    def refuse(*a):
        raise enterprises.EnterpriseError(409, "x", "Already answered")
    _flow(monkeypatch, answer_from_telegram=refuse)
    assert reports.telegram_answer(S, "", "", "yes") == ("error", "Already answered")


def test_notify_owner_never_raises(mx_state, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db gone")
    monkeypatch.setattr(feed, "post", boom)
    reports.notify_owner(S, "title", "body")


def test_gateway_forgets_a_deleted_enterprise_thread(mx_state):
    gateway.mutate_tg(lambda t: t.__setitem__("enterprise_threads", {S: {"tid": 42, "name": "x"}}))
    assert gateway.enterprise_of_thread(42) == S and gateway.enterprise_of_thread(43) is None
    gateway._forget_thread(42)
    assert gateway.enterprise_threads() == {}
