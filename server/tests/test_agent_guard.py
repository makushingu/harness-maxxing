"""Agents on Claude Code's own tools: sandbox, rules (PreToolUse hook), the maxxing CLI in a sandboxed turn,
the Claude Code agent file format, subagents of a topic, "Continue in Sessions" (agent_guard.py, agent_format.py)."""
from __future__ import annotations

import json
import subprocess
import sys

from conftest import wait_idle
from test_agents import A, _calls, _create, _on


def _settings(argv: list[str]) -> dict:
    return json.loads(argv[argv.index("--settings") + 1])


def test_new_agents_are_sandboxed_and_never_bypass(client, topic, mx):
    _on(client)
    a = _create(client, permission_mode="bypass", domains=["API.github.com", "https://*.example.com/"],
                writable=["drafts", "."])
    assert a["sandbox"] is True and a["domains"] == ["api.github.com", "*.example.com"]
    assert a["writable"] == ["drafts", "."]
    assert client.patch(f"/api/agents/acme/blog/writer", json={"domains": ["bad host!"]}).status_code == 400
    assert client.patch(f"/api/agents/acme/blog/writer", json={"writable": ["../x"]}).status_code == 400
    run = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL hi"}).json()
    wait_idle(client, run["session"]["id"])
    argv = _calls()[-1]["argv"]
    assert "--dangerously-skip-permissions" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"      # bypass ignores the domain list
    s = _settings(argv)
    sb = s["sandbox"]
    assert sb["enabled"] and sb["allowUnsandboxedCommands"] is False and sb["failIfUnavailable"] is True
    assert sb["excludedCommands"] == ["maxxing"]
    assert sb["network"]["allowedDomains"] == ["api.github.com", "*.example.com"]
    root = client.get("/api/workspace/tree").json()["root"]
    assert sb["filesystem"]["allowWrite"][0] == f"{root}/{A}"
    assert f"{root}/projects/acme/topics/blog" in sb["filesystem"]["allowWrite"]
    from maxxing import config
    assert str(config.STATE) in sb["filesystem"]["denyRead"]
    deny = s["permissions"]["deny"]
    assert f"Read(/{config.STATE}/**)" in deny and any(r.startswith("Edit(/") and ".maxxing.json" in r for r in deny)
    assert "WebFetch(domain:api.github.com)" in s["permissions"]["allow"]
    assert argv[argv.index("--add-dir") + 1].endswith("/drafts")
    # switched off: the agent's own mode, no sandbox
    client.patch("/api/agents/acme/blog/writer", json={"sandbox": False})
    run = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL hi"}).json()
    wait_idle(client, run["session"]["id"])
    argv = _calls()[-1]["argv"]
    assert "--dangerously-skip-permissions" in argv and "sandbox" not in _settings(argv)


def test_agents_made_before_the_sandbox_stay_without(tmp_path):
    from maxxing import agents
    assert agents.clean({"name": "old"})["sandbox"] is False
    assert agents.clean({"sandbox": True})["sandbox"] is True


def test_sandbox_missing_stops_the_turn(client, topic, mx, monkeypatch):
    _on(client)
    _create(client)
    monkeypatch.setenv("MAXXING_SANDBOX_CHECK", "1")
    monkeypatch.setenv("PATH", "/nonexistent")                 # no bwrap, no socat
    from maxxing import agent_guard
    agent_guard._avail = None
    assert client.get("/api/agents/sandbox").json()["missing"][:2] == ["bwrap", "socat"]
    n = len(_calls())
    run = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL hi"}).json()
    wait_idle(client, run["session"]["id"])
    s = client.get(f"/api/sessions/{run['session']['id']}").json()
    assert "sandbox-setup" in (s.get("error") or "") and len(_calls()) == n       # Claude never started


def test_rules_become_a_pretooluse_hook(client, topic, mx):
    _on(client)
    _create(client, rules=[{"tool": "Bash", "match": "sendmail", "reason": "Write a draft instead"},
                           {"tool": "nope", "match": "x"}][:1])
    assert client.patch("/api/agents/acme/blog/writer", json={"rules": [{"tool": "Nope", "match": "x"}]}).status_code == 400
    run = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL hi"}).json()
    wait_idle(client, run["session"]["id"])
    hooks = _settings(_calls()[-1]["argv"])["hooks"]["PreToolUse"]
    cmd = hooks[0]["hooks"][0]["command"]
    assert hooks[0]["matcher"] == "*" and "maxxing.agent_guard hook" in cmd and cmd.endswith(A)
    from maxxing import agent_guard
    rules = [{"tool": "Bash", "match": "sendmail", "reason": "Write a draft instead"},
             {"tool": "*", "match": "rm -rf", "reason": ""}]
    assert agent_guard.check_rules(rules, "Bash", {"command": "echo | SENDMAIL bob"}) == "Write a draft instead"
    assert agent_guard.check_rules(rules, "Write", {"content": "sendmail"}) is None
    assert "rm -rf" in agent_guard.check_rules(rules, "Write", {"content": "rm -rf /"})
    # the hook itself, as Claude Code runs it
    out = subprocess.run([sys.executable, "-m", "maxxing.agent_guard", "hook", A], capture_output=True, text=True,
                         input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                           "tool_input": {"command": "sendmail x"}}))
    d = json.loads(out.stdout)["hookSpecificOutput"]
    assert d["permissionDecision"] == "deny" and d["permissionDecisionReason"] == "Write a draft instead"
    out = subprocess.run([sys.executable, "-m", "maxxing.agent_guard", "hook", A], capture_output=True, text=True,
                         input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}))
    assert out.returncode == 0 and out.stdout == ""


def test_maxxing_cli_in_a_sandboxed_turn(client, topic, mx, monkeypatch, capsys):
    from maxxing import agent_guard, cli
    _on(client)
    _create(client)
    run = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL hi"}).json()
    wait_idle(client, run["session"]["id"])
    sid = run["session"]["id"]
    assert agent_guard.sandboxed_session(sid[:8]) == A
    assert agent_guard.UNIT_RE.search(f"0::/system.slice/maxxing-{sid[:8]}.service").group(1) == sid[:8]
    assert agent_guard.UNIT_RE.search("0::/system.slice/claude-maxxing.service") is None
    monkeypatch.setattr(agent_guard, "sandboxed_turn", lambda: A)
    assert agent_guard.check_cli(["feed", "post", "--title", "x"]) is None
    assert agent_guard.check_cli(["agents", "send", "other", "hi"]) is None
    assert agent_guard.check_cli(["status"]) is None
    for argv in (["cron", "add", "x"], ["mcp", "add", "x"], ["agents", "create", "a/b/c"], ["keys", "set", "X"],
                 ["custom", "save"], ["update"]):
        assert agent_guard.check_cli(argv), argv
    assert cli.main(["cron", "list"]) == 2
    assert "not allowed in a sandboxed agent turn" in capsys.readouterr().err
    client.patch("/api/agents/acme/blog/writer", json={"sandbox": False})
    assert agent_guard.sandboxed_session(sid[:8]) is None


def test_claude_code_agent_file_export_and_import(client, topic, mx):
    _on(client)
    _create(client, model="sonnet", permission_mode="acceptEdits", allowed_tools=["Read", "Bash(git log:*)"],
            description="You write the blog posts: one a week.\n\nKeep a friendly tone.")
    r = client.get("/api/agents/acme/blog/writer/export")
    assert r.status_code == 200 and 'filename="writer.md"' in r.headers["content-disposition"]
    md = r.text
    assert md.startswith("---\nname: writer\ndescription: ")
    assert "tools: Read, Bash(git log:*)" in md and "model: sonnet" in md and "permissionMode: acceptEdits" in md
    assert "Keep a friendly tone." in md and "@memory.md" not in md
    from maxxing import agent_format
    p = agent_format.parse_md(md)
    assert p["name"] == "writer" and p["fields"]["allowed_tools"] == ["Read", "Bash(git log:*)"]
    assert p["fields"]["model"] == "sonnet" and p["fields"]["permission_mode"] == "acceptEdits"
    assert p["description"].startswith("You write the blog posts: one a week.") and p["ignored"] == []
    cc = ("---\nname: Code Reviewer\ndescription: \"Reviews code: quality, security\"\ntools:\n  - Read\n  - Grep\n"
          "model: inherit\npermissionMode: bypassPermissions\nmemory: project\nmcpServers:\n  - github\n---\n"
          "You are a senior reviewer.\n")
    r = client.post("/api/agents/import", json={"topic_path": "projects/acme/topics/blog", "markdown": cc})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["path"] == "projects/acme/topics/blog/agents/code-reviewer" and a["display_name"] == "Code Reviewer"
    assert a["allowed_tools"] == ["Read", "Grep"] and a["model"] == "" and a["permission_mode"] == "bypass"
    assert a["sandbox"] is True and a["ignored"] == ["mcpServers", "memory"]
    assert a["description"] == "Reviews code: quality, security\n\nYou are a senior reviewer."
    assert client.post("/api/agents/import", json={"topic_path": "projects/acme/topics/blog",
                                                   "markdown": "no front matter"}).status_code == 400


def test_agents_as_subagents_of_their_topic(client, topic, mx):
    _on(client)
    _create(client, allowed_tools=["Read"])
    r = client.post("/api/sessions", json={"path": "projects/acme/topics/blog", "message": "NOTOOL hi"}).json()
    wait_idle(client, r["id"])
    assert "--agents" not in _calls()[-1]["argv"]                     # off by default
    client.patch("/api/agents/acme/blog/writer", json={"subagent": True})
    r = client.post("/api/sessions", json={"path": "projects/acme/topics/blog", "message": "NOTOOL hi"}).json()
    wait_idle(client, r["id"])
    argv = _calls()[-1]["argv"]
    sub = json.loads(argv[argv.index("--agents") + 1])["writer"]
    assert sub["description"].startswith("Writer: You write the blog posts.") and sub["tools"] == ["Read"]
    assert f"{A}/memory.md" in sub["prompt"]
    run = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL hi"}).json()
    wait_idle(client, run["session"]["id"])
    assert "--agents" not in _calls()[-1]["argv"]                     # never inside the agent's own runs


def test_continue_a_run_in_sessions(client, topic, mx):
    _on(client)
    _create(client)
    run = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL write it"}).json()
    sid = run["session"]["id"]
    wait_idle(client, sid)
    r = client.post(f"/api/agents/acme/blog/writer/runs/{sid}/continue")
    assert r.status_code == 200, r.text
    s = r.json()["session"]
    assert s["path"] == "projects/acme/topics/blog" and s["id"] != sid and s["title"].startswith("Writer: ")
    assert s.get("source") == "web" and not s.get("cron")
    logs = client.get(f"/api/sessions/{s['id']}/events").json()
    old = client.get(f"/api/sessions/{sid}/events").json()
    assert json.dumps(logs, sort_keys=True).count("write it") == json.dumps(old, sort_keys=True).count("write it") >= 1
    r2 = client.post(f"/api/sessions/{s['id']}/messages", json={"text": "NOTOOL and now?"})
    assert r2.status_code == 200, r2.text
    wait_idle(client, s["id"])
    c = _calls()[-1]
    assert c["cwd"].endswith("projects/acme/topics/blog") and "sandbox" not in _settings(c["argv"])
    assert "MAXXING_AGENT" not in (client.get(f"/api/sessions/{s['id']}").json().get("env") or {})
    assert client.post(f"/api/agents/acme/blog/writer/runs/{s['id']}/continue").status_code == 404


def test_templates_bring_their_domains():
    from maxxing import agent_templates
    t = agent_templates.get("pr-review", "en")
    assert agent_templates.fields(t)["domains"] == ["api.github.com", "github.com"]
    assert agent_templates.fields(agent_templates.get("writer", "en"))["domains"] == []
