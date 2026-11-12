"""`maxxing enterprise …` (maxxing/cmd_enterprise.py) and its guard in agent turns (agent_guard.py)."""
from __future__ import annotations

import importlib
import json
import os
import sys
import time
import types

import pytest
from maxxing import agent_guard, cli, enterprises

E = "/api/enterprises"
W = "projects/acme/topics/blog/agents/writer"
R = "projects/acme/topics/blog/agents/editor"
S = "projects/acme/topics/blog/agents/stranger"


def _on(client, on=True):
    assert client.put("/api/settings", json={"agents_page": True, "enterprises_page": on}).status_code == 200


@pytest.fixture
def cl(client, topic, capsys):
    """Feature on, agents writer / editor / stranger in acme/blog; `run(*argv) -> (code, out, err)`."""
    _on(client)
    for n in ("writer", "editor", "stranger"):
        assert client.post("/api/agents", json={"topic_path": topic, "name": n, "sandbox": False}).status_code == 200

    def run(*argv):
        capsys.readouterr()
        code = cli.main(["enterprise", *argv])
        o = capsys.readouterr()
        return code, o.out, o.err

    run.client = client
    return run


@pytest.fixture
def chart(cl):
    assert cl("create", "acme-group", "--name", "Acme Group", "--project", "acme")[0] == 0
    assert cl("position", "add", "acme-group", "lead", "--title", "Head", "--agent", "acme/blog/editor",
              "--department", "marketing")[0] == 0
    assert cl("position", "add", "acme-group", "writer", "--title", "Articles", "--reports-to", "lead",
              "--agent", "acme/blog/writer")[0] == 0
    return cl


def _fake(monkeypatch, mod, **fns):
    """Functions of a sibling module, real or not yet written: replaced for the test."""
    name = f"maxxing.{mod}"
    try:
        real = importlib.import_module(name)
    except ImportError:
        real = types.ModuleType(name)
        monkeypatch.setitem(sys.modules, name, real)
    for k, v in fns.items():
        monkeypatch.setattr(real, k, v, raising=False)


# ---- structure -------------------------------------------------------------------------------------------------
def test_create_list_show_and_positions(cl):
    code, out, err = cl("create", "acme-group", "--name", "Acme Group", "--project", "acme", "--json")
    assert code == 0 and json.loads(out)["projects"] == ["acme"], err
    assert cl("create", "acme-group")[0] == 2                                  # exists
    assert cl("create", "Bad Name")[0] == 2
    assert json.loads(cl("list", "--json")[1])[0]["id"] == "acme-group"
    assert "acme-group  Acme Group  0 position(s)" in cl("list")[1]
    assert cl("position", "add", "acme-group", "lead", "--title", "Head", "--agent", "editor")[0] == 0
    assert cl("position", "add", "acme-group", "writer", "--title", "Articles", "--reports-to", "lead",
              "--agent", "acme/blog/writer")[0] == 0
    assert cl("position", "add", "acme-group", "x", "--agent", "acme/blog/writer")[0] == 2      # already seated
    assert cl("position", "add", "acme-group", "y", "--agent", "nobody")[0] == 2
    code, out, _ = cl("show")                                                  # the only enterprise
    assert code == 0 and "Head (lead)" in out and "  - Articles (writer)" not in out.splitlines()[1]
    assert any(ln.startswith("    - Articles (writer)") for ln in out.splitlines())
    chart = json.loads(cl("show", "acme-group", "--json")[1])
    assert {p["id"]: p["agent"] for p in chart["positions"]} == {"lead": R, "writer": W}
    assert cl("position", "vacate", "acme-group", "writer")[0] == 0
    assert enterprises.position("acme-group", "writer")["agent"] is None
    assert cl("position", "seat", "acme-group", "writer", "--agent", "writer")[0] == 0
    assert cl("position", "move", "acme-group", "writer", "--reports-to", "owner")[0] == 0
    assert enterprises.lead_of("acme-group", "writer") is None
    assert cl("position", "remove", "acme-group", "lead")[0] == 0
    assert cl("position", "remove", "acme-group", "nope")[0] == 2


def test_link_unlink_settings_and_departments(chart, client):
    assert chart("link", "acme-group", "acme")[0] == 1                          # nothing to change
    assert chart("unlink", "acme-group", "acme")[0] == 2                        # occupied
    assert chart("unlink", "acme-group", "acme", "--vacate")[0] == 0
    assert enterprises.load("acme-group")["projects"] == []
    assert chart("link", "acme-group", "acme")[0] == 0
    code, _, err = chart("settings", "acme-group", "autonomy=careful", "digest.enabled=true", "escalation_timeout_h=8")
    assert code == 0, err
    s = enterprises.load("acme-group")["settings"]
    assert s["autonomy"] == "careful" and s["digest"]["enabled"] is True and s["digest"]["hour"] == 8
    assert s["escalation_timeout_h"] == 8
    assert chart("settings", "acme-group", "autonomy=reckless")[0] == 2
    assert chart("settings", "acme-group", "oops")[0] == 2
    assert chart("settings", "acme-group", "autonomy=autonomous", "notes=Tone: warm", "--department", "marketing")[0] == 0
    dep = enterprises.load("acme-group")["departments"]["marketing"]
    assert dep["settings"]["autonomy"] == "autonomous" and dep["notes"] == "Tone: warm"
    assert enterprises.setting("acme-group", "autonomy", "lead") == "autonomous"
    assert chart("settings", "acme-group", "name=Acme Inc", "envelope.usd_per_day=20")[0] == 0
    e = enterprises.load("acme-group")
    assert e["name"] == "Acme Inc" and e["envelope"]["usd_per_day"] == 20


def test_grant_and_decisions(chart):
    soon = time.strftime("%Y-%m-%d", time.localtime(time.time() + 3 * 86400))
    far = time.strftime("%Y-%m-%d", time.localtime(time.time() + 40 * 86400))
    code, out, err = chart("grant", "acme-group", "lead", "--category", "spending", "--ceiling", "50", "--until", soon,
                           "--json")
    assert code == 0, err
    g = json.loads(out)
    assert g["position"] == "lead" and g["ceiling"] == 50 and g["until"] > time.time()
    assert enterprises.load("acme-group")["grants"][0]["id"] == g["id"]
    assert chart("grant", "acme-group", "lead", "--category", "spending", "--ceiling", "5", "--until", far)[0] == 2
    assert chart("grant", "acme-group", "nobody", "--category", "spending", "--ceiling", "5", "--until", soon)[0] == 2
    assert chart("grant", "acme-group", "lead", "--category", "spending", "--ceiling", "5", "--until", "yesterday")[0] == 2
    assert chart("grant", "acme-group", "--revoke", g["id"])[0] == 0
    assert enterprises.load("acme-group")["grants"] == []
    code, out, _ = chart("decisions", "acme-group", "--json")
    items = json.loads(out)
    assert code == 0 and any(x["kind"] == "grant" for x in items) and any(x["kind"] == "structure" for x in items)
    assert chart("decisions", "acme-group", "--since", "2999-01-01")[0] == 1
    assert "grant" in chart("decisions", "acme-group", "--since", "2000-01-01")[1]


def test_report_export_import_call_their_modules(chart, monkeypatch, tmp_path):
    seen = {}
    _fake(monkeypatch, "enterprise_reports",
          reports=lambda slug: [{"name": "2026-01-01-daily", "date": "2026-01-01", "kind": "daily"},
                                {"name": "2026-01-02-daily", "date": "2026-01-02", "kind": "daily"},
                                {"name": "2026-01-01-weekly", "date": "2026-01-01", "kind": "weekly"}],
          report=lambda slug, name: {"name": name, "text": f"TEXT {name}"},
          build=lambda slug, kind="daily", now=None: seen.setdefault("kind", kind) and {"text": f"built {kind}"})
    assert chart("report", "acme-group")[1].strip() == "TEXT 2026-01-02-daily"
    assert chart("report", "acme-group", "--weekly")[1].strip() == "TEXT 2026-01-01-weekly"
    assert chart("report", "acme-group", "--monthly")[0] == 1
    assert chart("report", "acme-group", "--monthly", "--now")[1].strip() == "built monthly" and seen["kind"] == "monthly"
    _fake(monkeypatch, "enterprise_io", export_zip=lambda slug: b"ZIP:" + slug.encode(),
          import_zip=lambda data: {"id": "imported", "bytes": len(data)})
    out = tmp_path / "x.zip"
    assert chart("export", "acme-group", "-o", str(out))[0] == 0 and out.read_bytes() == b"ZIP:acme-group"
    code, o, _ = chart("import", str(out), "--json")
    assert code == 0 and json.loads(o) == {"id": "imported", "bytes": len(b"ZIP:acme-group")}
    assert chart("import", str(tmp_path / "missing.zip"))[0] == 2


def test_missing_module_is_a_clear_error(chart, monkeypatch):
    monkeypatch.setitem(sys.modules, "maxxing.enterprise_io", None)         # import fails
    code, _, err = chart("export", "acme-group", "-o", "/tmp/never.zip")
    assert code == 2 and "not available" in err


def test_off_means_refused(chart, client):
    _on(client, on=False)
    code, _, err = chart("list")
    assert code == 2 and "off" in err


# ---- turn commands ---------------------------------------------------------------------------------------------
def test_turn_commands_call_flow_and_policy_as_the_callers_position(chart, monkeypatch):
    calls = []

    def rec(name, ret):
        def f(*a, **k):
            calls.append((name, a, k))
            return ret
        return f
    _fake(monkeypatch, "enterprise_flow", assign=rec("assign", {"id": "t_1"}), done=rec("done", {"id": "t_1"}),
          block=rec("block", {"id": "t_1"}), escalate=rec("escalate", {"id": "e_1"}), answer=rec("answer", {"id": "e_1"}))
    _fake(monkeypatch, "enterprise_policy", request=rec("request", {"id": "r_1", "status": "pending"}),
          decide=rec("decide", {"id": "r_1"}))
    monkeypatch.setenv("MAXXING_AGENT", R)                                   # the lead's run, started from outside
    monkeypatch.setenv("MAXXING_AGENT_OUTSIDE", "1")
    monkeypatch.setenv("MAXXING_SESSION", "sid-9")
    c = chart
    assert c("assign", "writer", "Three", "articles", "--due", "2026-12-01", "--parent", "t_0")[0] == 0
    assert calls[-1] == ("assign", ("acme-group", "lead", "writer", "Three articles"),
                         {"due": "2026-12-01", "parent": "t_0", "task": None, "session": "sid-9", "outside": True})
    assert c("done", "t_1", "all", "done")[0] == 0
    assert calls[-1] == ("done", ("acme-group", "lead", "t_1", "all done"), {"session": "sid-9"})
    assert c("block", "t_1", "waiting")[0] == 0 and calls[-1][1][2:] == ("t_1", "waiting")
    assert c("escalate", "need", "a", "decision", "--task", "t_1")[0] == 0
    assert calls[-1] == ("escalate", ("acme-group", "lead", "need a decision"),
                         {"task": "t_1", "session": "sid-9", "outside": True})
    assert c("answer", "e_1", "go", "A")[0] == 0 and calls[-1] == ("answer", ("acme-group", "e_1", "go A"),
                                                  {"by": "lead", "outside": True})
    assert c("request", "spending", "Boost", "post", "--amount", "20")[0] == 0
    assert calls[-1] == ("request", ("acme-group", "lead", "spending", "Boost post"),
                         {"amount": 20.0, "session": "sid-9", "outside": True})
    assert c("decide", "r_1", "allow", "within", "plan")[0] == 0
    assert calls[-1] == ("decide", ("acme-group", "r_1", "allow"), {"reason": "within plan", "by": "lead", "outside": True})
    code, out, _ = c("assign", "writer", "x", "--json")
    assert code == 0 and json.loads(out) == {"id": "t_1"}


def test_as_is_honoured_only_for_the_owner(chart, monkeypatch):
    calls = []
    _fake(monkeypatch, "enterprise_flow", done=lambda *a, **k: calls.append((a, k)) or {"id": "t_1"},
          assign=lambda *a, **k: calls.append((a, k)) or {"id": "t_2"},
          answer=lambda *a, **k: calls.append((a, k)) or {})
    assert chart("done", "t_1", "ok", "--as", "writer")[0] == 0              # the owner, no agent turn
    assert calls[-1][0][:2] == ("acme-group", "writer")
    assert chart("done", "t_1", "ok")[0] == 2                                # the owner must say which position
    assert chart("done", "t_1", "ok", "--as", "ghost")[0] == 2
    assert chart("assign", "writer", "x")[0] == 0 and calls[-1][0][1] is None
    assert chart("answer", "e_1", "yes")[0] == 0 and calls[-1][1] == {"by": None, "outside": False}
    n = len(calls)
    monkeypatch.setenv("MAXXING_AGENT", W)
    code, _, err = chart("done", "t_1", "ok", "--as", "lead")
    assert code == 2 and "--as" in err and len(calls) == n
    assert chart("done", "t_1", "ok", "--enterprise", "other")[0] == 2
    assert chart("done", "t_1", "ok")[0] == 0 and calls[-1][0][:2] == ("acme-group", "writer")


def test_several_enterprises_need_a_choice(chart, monkeypatch):
    assert chart("create", "zeta")[0] == 0
    code, _, err = chart("profile")
    assert code == 2 and "--enterprise" in err
    assert chart("profile", "--enterprise", "zeta")[0] == 0


def test_an_agent_without_a_position_is_refused(chart, monkeypatch):
    called = []
    _fake(monkeypatch, "enterprise_flow", assign=lambda *a, **k: called.append(1), escalate=lambda *a, **k: called.append(1))
    monkeypatch.setenv("MAXXING_AGENT", S)
    for argv in (("assign", "writer", "x"), ("escalate", "help"), ("profile",), ("show",)):
        code, _, err = chart(*argv)
        assert code == 2 and "no position" in err, argv
    assert not called


def test_objective_set_only_by_the_owner_position(chart):
    enterprises.update("acme-group", {"objectives": [
        {"id": "o_1", "text": "Articles", "target": 10, "unit": "", "value": 0, "owner": "writer", "parent": ""}]})
    assert chart("objective", "set", "o_1", "7", "--as", "lead")[0] == 2
    assert chart("objective", "set", "o_1", "7", "--as", "writer")[0] == 0
    assert enterprises.load("acme-group")["objectives"][0]["value"] == 7
    assert chart("objective", "set", "o_1", "8")[0] == 0                       # the owner himself
    assert chart("objective", "set", "o_9", "1", "--as", "writer")[0] == 2
    assert enterprises.load("acme-group")["objectives"][0]["value"] == 8


def test_profile_and_show_for_a_position(chart, monkeypatch):
    from maxxing import enterprise_knowledge as ek
    ek.set_profile("acme-group", {"products": [{"name": "Kit", "price": "29 USD"}], "faq": [{"q": "Q?", "a": "A."}]})
    monkeypatch.setenv("MAXXING_AGENT", W)
    code, out, _ = chart("profile", "--section", "faq")
    assert code == 0 and json.loads(out) == [{"q": "Q?", "a": "A."}]
    assert json.loads(chart("profile")[1])["products"][0]["name"] == "Kit"
    assert chart("profile", "--section", "secrets")[0] == 2
    assert "Head (lead)" in chart("show")[1]                                   # not sandboxed: the whole chart
    monkeypatch.setattr(agent_guard, "sandboxed_turn", lambda: W if os.environ.get("MAXXING_AGENT") else None)
    assert chart("create", "acme-group")[0] == 2
    chart("position", "add", "acme-group", "other", "--title", "Other")        # refused: structure in an agent turn
    assert enterprises.position("acme-group", "other") is None
    monkeypatch.delenv("MAXXING_AGENT")
    assert chart("position", "add", "acme-group", "peer", "--reports-to", "lead")[0] == 0
    monkeypatch.setenv("MAXXING_AGENT", W)
    ids = {p["id"] for p in json.loads(chart("show", "--json")[1])["positions"]}
    assert ids == {"writer", "lead"}                                           # own position and lead, not the peer


# ---- the guard -------------------------------------------------------------------------------------------------
def test_structure_commands_are_refused_in_agent_turns(chart, monkeypatch):
    monkeypatch.setenv("MAXXING_AGENT", W)
    for sub in ("create", "link", "unlink", "position", "settings", "grant", "report", "decisions", "export", "import",
                "list"):
        msg = agent_guard.check_cli(["enterprise", sub, "acme-group"])
        assert msg and f"maxxing enterprise {sub}" in msg and "not allowed in an agent turn" in msg, sub
    for sub in ("assign", "done", "block", "escalate", "answer", "decide", "request", "objective", "show", "profile"):
        assert agent_guard.check_cli(["enterprise", sub, "x"]) is None, sub
    assert agent_guard.check_cli(["enterprise", "position", "add", "-h"]) is None            # help changes nothing
    code, _, err = chart("create", "evil")
    assert code == 2 and "not allowed in an agent turn" in err
    assert not (enterprises.folder("evil")).exists()
    monkeypatch.delenv("MAXXING_AGENT")
    assert agent_guard.check_cli(["enterprise", "create", "x"]) is None                       # the owner


def test_sandboxed_turns_allow_the_work_commands():
    allowed = agent_guard.CLI_ALLOWED["enterprise"]
    assert allowed == {"assign", "done", "block", "escalate", "answer", "decide", "request", "objective", "show",
                       "profile", "route", "worker"}
    assert not allowed & agent_guard.ENTERPRISE_OWNER_ONLY


def test_agent_turn_reports_outside(monkeypatch):
    monkeypatch.setenv("MAXXING_AGENT", W)
    assert agent_guard.agent_turn()["outside"] is False
    monkeypatch.setenv("MAXXING_AGENT_OUTSIDE", "1")
    assert agent_guard.agent_turn()["outside"] is True
