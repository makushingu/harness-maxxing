"""Fixes of the agents benchmark of 2026-11-14: an agent that is neither sandboxed nor free can work in its topic,
what only the owner starts, the webhooks of deleted agents, the task cap, the memory of the levels above."""
from __future__ import annotations

import json
from pathlib import Path

from conftest import wait_idle
from maxxing import agent_guard, agents
from test_agents import A, _calls, _create, _on, _run


def test_an_agent_in_accept_edits_without_a_sandbox_reads_its_topic_and_writes_its_folders(client, topic, mx):
    _on(client)
    _create(client, permission_mode="acceptEdits", writable=["drafts"])
    root = client.get("/api/workspace/tree").json()["root"]
    blog = f"{root}/projects/acme/topics/blog"
    wait_idle(client, _run("NOTOOL hi")["session"]["id"])
    argv = _calls()[-1]["argv"]
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert argv[argv.index("--add-dir") + 1] == f"{blog}/drafts"                    # `writable`, sandbox or not
    p = json.loads(argv[argv.index("--settings") + 1])["permissions"]
    assert f"Read(/{blog}/**)" in p["allow"] and "Bash(maxxing agents:*)" in p["allow"]
    assert f"Read(/{blog}/.env)" in p["deny"] and f"Edit(/{blog}/agents/*/agent.json)" in p["deny"]
    client.patch("/api/agents/acme/blog/writer", json={"permission_mode": "bypass"})
    wait_idle(client, _run("NOTOOL free")["session"]["id"])
    argv = _calls()[-1]["argv"]
    assert f"Read(/{blog}/**)" not in json.loads(argv[argv.index("--settings") + 1])["permissions"].get("allow", [])


def test_an_agent_run_never_starts_a_session_or_a_scheduled_job(mx, monkeypatch):
    monkeypatch.setenv("MAXXING_AGENT", A)
    for argv in (["sessions", "new", "general/inbox", "hi"], ["sessions", "send", "x", "hi"], ["cron", "run", "c_1"]):
        assert "not allowed in an agent run" in agent_guard.check_cli(argv), argv
    assert agent_guard.check_cli(["sessions", "list"]) is None
    monkeypatch.setenv("MAXXING_AGENT_CHAT", "1")                               # the owner's conversation: his words
    assert agent_guard.check_cli(["sessions", "new", "general/inbox", "hi"]) is None
    monkeypatch.delenv("MAXXING_AGENT")
    monkeypatch.delenv("MAXXING_AGENT_CHAT")
    assert agent_guard.check_cli(["sessions", "new", "general/inbox", "hi"]) is None   # the owner, in a session


def test_the_sandbox_is_tried_not_only_looked_for(monkeypatch):
    monkeypatch.delenv("MAXXING_SANDBOX_CHECK", raising=False)
    monkeypatch.setattr(agent_guard.sys, "platform", "linux")
    monkeypatch.setattr(agent_guard.shutil, "which", lambda b: f"/usr/bin/{b}")
    monkeypatch.setattr(agent_guard, "_userns_restricted", lambda: False)
    monkeypatch.setattr(agent_guard, "_probe", lambda: False)
    monkeypatch.setattr(agent_guard, "_distro_profile_loaded", lambda: True)
    assert agent_guard.available(fresh=True) == {"ok": False, "missing": ["apparmor"]}
    monkeypatch.setattr(agent_guard, "_distro_profile_loaded", lambda: False)
    assert agent_guard.available(fresh=True) == {"ok": False, "missing": ["user namespaces"]}
    monkeypatch.setattr(agent_guard, "_probe", lambda: True)
    assert agent_guard.available(fresh=True) == {"ok": True, "missing": []}
    monkeypatch.setattr(agent_guard, "_avail", None)


def test_the_sandbox_is_tried_in_a_unit_like_the_turns(monkeypatch):
    # the service's own hardening (ProtectKernelTunables) fails bubblewrap; turn units do not have it
    seen = []

    class R:
        returncode = 0

    monkeypatch.setattr(agent_guard.shutil, "which", lambda b: f"/usr/bin/{b}")
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: seen.append(cmd) or R())
    monkeypatch.delenv("MAXXING_SPAWN", raising=False)
    assert agent_guard._probe() is True
    assert seen[-1][:2] == ["systemd-run", "--wait"] and "bwrap" in seen[-1]
    assert "ProtectKernelTunables=yes" not in seen[-1]
    monkeypatch.setenv("MAXXING_SPAWN", "direct")
    agent_guard._probe()
    assert seen[-1][0] == "bwrap"


def test_a_deleted_agent_takes_its_webhook_with_it(client, topic):
    from maxxing import feedhooks
    _on(client)
    _create(client)
    hook = client.post("/api/agents/acme/blog/writer/webhook", json={"kind": "generic"}).json()["hook"]
    token = hook["url"].rsplit("/", 1)[-1]
    assert feedhooks.deliver(token, {}, b'{"title": "x"}')[0] == 200
    assert client.delete("/api/agents/acme/blog/writer").status_code == 200
    assert feedhooks.deliver(token, {}, b'{"title": "x"}')[0] == 404
    assert not [h for h in feedhooks.list_hooks() if h["id"] == hook["id"]]


def test_a_task_has_a_size(client, topic):
    _on(client)
    _create(client)
    long = "x" * (agents.TASK_MAX + 1)
    assert _run(long) == {"started": False, "reason": "too_long"}
    assert [m["reason"] for m in agents.thread(A) if m["kind"] == "skip"] == ["too_long"]
    r = client.post("/api/agents/acme/blog/writer/run", json={"text": long})
    assert r.status_code == 413 and r.json()["error"] == "too_long"
    assert not _calls()


def test_light_templates_run_on_the_small_model():
    from maxxing import agent_templates
    for tid in ("uptime", "orders", "sales", "mail-sort"):
        assert agent_templates.fields(agent_templates.get(tid))["model"] == "haiku", tid
    assert "model" not in agent_templates.fields(agent_templates.get("writer"))


def test_a_turn_gets_the_memory_of_the_levels_above(client, topic, tmp_path, monkeypatch):
    from maxxing.sessions import spawn
    _on(client)
    _create(client)
    root = Path(client.get("/api/workspace/tree").json()["root"])
    (root / "memory.md").write_text("# Memory\n\n- MEM-GLOBAL\n")
    (root / "projects/acme/memory.md").write_text("- MEM-PROJECT\n")
    (root / "projects/acme/topics/blog/memory.md").write_text("- MEM-TOPIC\n")
    for d in (root, root / "projects/acme", root / "projects/acme/topics/blog"):
        if "@memory.md" not in (d / "CLAUDE.md").read_text():
            (d / "CLAUDE.md").write_text("# Level\n\n@memory.md\n")
    blog = root / "projects/acme/topics/blog"
    note = spawn.upper_memory(str(blog), str(root))
    assert note.startswith(spawn.UPPER_MEMORY) and "MEM-TOPIC" not in note       # its own: Claude Code loads it
    assert note.index("MEM-GLOBAL") < note.index("MEM-PROJECT")
    assert f"Contents of {root / 'projects/acme/memory.md'}:" in note
    # an agent: its topic's too; in one --append-system-prompt with the rest
    wait_idle(client, _run("NOTOOL hi")["session"]["id"])
    argv = _calls()[-1]["argv"]
    assert argv.count("--append-system-prompt") == 1
    said = argv[argv.index("--append-system-prompt") + 1]
    assert said.index("MEM-GLOBAL") < said.index("MEM-PROJECT") < said.index("MEM-TOPIC")
    # a level that does not import its memory, no workspace, a folder outside it, the imports approved by hand
    (root / "projects/acme/CLAUDE.md").write_text("# Project acme\n")
    assert "MEM-PROJECT" not in spawn.upper_memory(str(blog), str(root))
    assert spawn.upper_memory(str(blog), "") == "" and spawn.upper_memory(str(tmp_path), str(root)) == ""
    assert spawn.upper_memory(str(root), str(root)) == ""
    blank = (Path(__file__).resolve().parents[2] / "templates/workspace/memory.md").read_text()
    assert not spawn._has_facts(blank) and not spawn._has_facts("# Project acme - memory\n\n")   # nobody wrote in it
    assert spawn._has_facts(blank + "- 2026-11-14: a fact\n")
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text(json.dumps({"projects": {str(blog): {"hasClaudeMdExternalIncludesApproved": True}}}))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(home))
    assert spawn.upper_memory(str(blog), str(root)) == ""


def test_switching_the_distro_profile_off_is_never_half_done(tmp_path, monkeypatch):
    """apparmor_parser is in /usr/sbin (not on every PATH); when it fails, the link in disable/ is taken back."""
    import subprocess

    from maxxing import agent_guard
    prof = tmp_path / "bwrap-userns-restrict"
    prof.write_text("profile")
    off = tmp_path / "disable" / prof.name
    monkeypatch.setattr(agent_guard, "DISTRO_FILE", prof)
    monkeypatch.setattr(agent_guard, "DISTRO_OFF", off)
    monkeypatch.setenv("PATH", str(tmp_path))                       # no apparmor_parser on it
    assert agent_guard._parser() in ("/usr/sbin/apparmor_parser", "/sbin/apparmor_parser", "apparmor_parser")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", run)
    try:
        agent_guard.drop_distro_profile()
        raise AssertionError("the failure is not hidden")
    except subprocess.CalledProcessError:
        pass
    assert not off.is_symlink()                                     # taken back
    assert agent_guard.drop_distro_profile() and off.is_symlink()
    assert calls[1][1:] == ["-R", str(prof)]
