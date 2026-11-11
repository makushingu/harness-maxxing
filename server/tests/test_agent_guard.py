"""Agents on Claude Code's own tools: sandbox, rules (PreToolUse hook), the maxxing CLI in a sandboxed turn,
the Claude Code agent file format, subagents of a topic, "Continue in Sessions" (agent_guard.py, agent_format.py)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import wait_idle
from test_agents import A, _calls, _create as _create_any, _on, _run


def _create(client, **extra) -> dict:
    """An agent in its sandbox (new agents are free unless they read outside text: test_new_agents_are_free...)."""
    return _create_any(client, **{"sandbox": True, **extra})


def _settings(argv: list[str]) -> dict:
    return json.loads(argv[argv.index("--settings") + 1])


def test_new_agents_are_free_unless_they_read_outside_text(client, topic, mx):
    _on(client)
    assert _create_any(client, name="free")["sandbox"] is False                 # free like a session
    feed = [{"kind": "feed", "source": "shop", "prompt": "NOTOOL handle it"}]
    assert _create_any(client, name="watcher", triggers=feed)["sandbox"] is True   # outside text: protected
    assert _create_any(client, name="mine", triggers=feed, sandbox=False)["sandbox"] is False


def test_sandboxed_agents_never_bypass(client, topic, mx):
    _on(client)
    a = _create(client, permission_mode="bypass", domains=["API.github.com", "https://*.example.com/"],
                writable=["drafts", "."])
    assert a["sandbox"] is True and a["domains"] == ["api.github.com", "*.example.com"]
    assert a["writable"] == ["drafts", "."]
    assert client.patch(f"/api/agents/acme/blog/writer", json={"domains": ["bad host!"]}).status_code == 400
    assert client.patch(f"/api/agents/acme/blog/writer", json={"writable": ["../x"]}).status_code == 400
    run = _run("NOTOOL hi")
    wait_idle(client, run["session"]["id"])
    argv = _calls()[-1]["argv"]
    assert "--dangerously-skip-permissions" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"      # bypass ignores the domain list
    s = _settings(argv)
    sb = s["sandbox"]
    assert sb["enabled"] and sb["allowUnsandboxedCommands"] is False and sb["failIfUnavailable"] is True
    assert sb["excludedCommands"] == ["maxxing:*"]
    assert sb["network"]["allowedDomains"] == ["api.github.com", "*.example.com"]
    root = client.get("/api/workspace/tree").json()["root"]
    assert sb["filesystem"]["allowWrite"][0] == f"{root}/{A}"
    assert f"{root}/projects/acme/topics/blog" not in sb["filesystem"]["allowWrite"]     # "." = its entries (below)
    from maxxing import config
    assert str(config.STATE) in sb["filesystem"]["denyRead"]
    deny = s["permissions"]["deny"]
    assert f"Read(/{config.STATE}/**)" in deny and any(r.startswith("Edit(/") and ".maxxing.json" in r for r in deny)
    assert s["permissions"]["allow"] == ["Bash(maxxing:*)", "WebFetch(domain:api.github.com)", "WebFetch(domain:*.example.com)"]
    assert argv[argv.index("--add-dir") + 1] == f"{root}/projects/acme/topics/blog"     # "." holds drafts
    # switched off: the agent's own mode, no sandbox
    client.patch("/api/agents/acme/blog/writer", json={"sandbox": False})
    run = _run("NOTOOL hi")
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
    assert hooks[0]["matcher"] == "*" and " -I -c " in cmd and cmd.endswith(f"hook {A}")
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
    # run from the agent folder, as Claude Code does: a `maxxing/` package the agent wrote there is never imported
    from maxxing import agents
    fake = agents.folder(A) / "maxxing"
    fake.mkdir()
    (fake / "__init__.py").write_text("")
    (fake / "agent_guard.py").write_text("import sys; print('PWNED'); sys.exit(0)\n")
    out = subprocess.run(cmd, shell=True, cwd=agents.folder(A), capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(agents.folder(A))},
                         input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "sendmail x"}}))
    assert "PWNED" not in out.stdout and json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


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
    assert agent_guard.UNIT_RE.search(f"0::/system.slice/maxxing-{sid[:8]}-4242.service").group(1) == sid[:8]
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


def test_a_sandboxed_turn_reads_only_its_own_agent_and_feed(client, topic, mx, monkeypatch, capsys):
    from maxxing import agent_guard, cli, feed
    _on(client)
    _create(client)
    _create(client, name="other", description="SECRET ROLE")
    client.patch("/api/agents/acme/blog/writer", json={"triggers": [{"kind": "feed", "source": "shop"}]})
    assert cli.main(["agents", "webhook", "other", "--json"]) == 0
    assert cli.main(["agents", "webhook", "writer", "--json"]) == 0
    feed.post("refund asked", source="shop", level="warning")
    feed.post("mail from the bank", body="account 1234", source="mail-notice")
    capsys.readouterr()
    monkeypatch.setattr(agent_guard, "sandboxed_turn", lambda: A)
    assert cli.main(["agents", "show", "other"]) == 2
    assert "this agent only" in capsys.readouterr().err
    assert cli.main(["agents", "show", "writer"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["webhooks"] and all("url" not in h for h in d["webhooks"])
    assert cli.main(["agents", "list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["path"] for r in rows} == {A, "projects/acme/topics/blog/agents/other"}
    assert all(set(r) == {"path", "display_name"} for r in rows)
    assert cli.main(["feed", "list", "--json"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert [e["title"] for e in r["events"]] == ["refund asked"] and [s["source"] for s in r["sources"]] == ["shop"]
    assert cli.main(["feed", "list", "--json", "--source", "mail-notice"]) == 0
    assert json.loads(capsys.readouterr().out)["events"] == []
    monkeypatch.setattr(agent_guard, "sandboxed_turn", lambda: None)      # the owner sees everything
    assert cli.main(["agents", "show", "other"]) == 0
    assert "SECRET ROLE" in capsys.readouterr().out
    assert cli.main(["feed", "list", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["events"]) >= 2


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
    assert a["sandbox"] is False and a["ignored"] == ["mcpServers", "memory"]           # free like any new one
    assert a["description"] == "Reviews code: quality, security\n\nYou are a senior reviewer."
    assert client.post("/api/agents/import", json={"topic_path": "projects/acme/topics/blog",
                                                   "markdown": "no front matter"}).status_code == 400


def test_a_wrapped_first_paragraph_and_a_yaml_block_description_import_once():
    from maxxing import agent_format
    md = ("---\nname: writer\ndescription: You write the weekly post for the blog.\n---\n\n"
          "You write the weekly post\nfor the blog.\n\nKeep it short.\n")
    assert agent_format.parse_md(md)["description"] == "You write the weekly post\nfor the blog.\n\nKeep it short."
    for style, want in ((">", "Reviews pull requests carefully."), ("|-", "Reviews pull requests\ncarefully.")):
        md = (f"---\nname: reviewer\ndescription: {style}\n  Reviews pull requests\n  carefully.\ntools: Read\n---\n"
              "You are a senior reviewer.\n")
        p = agent_format.parse_md(md)
        assert p["description"] == f"{want}\n\nYou are a senior reviewer." and p["fields"]["allowed_tools"] == ["Read"]
    md = "---\nname: last\ndescription: >\n  At the end\n  of the block.\n---\nBody.\n"
    assert agent_format.parse_md(md)["description"] == "At the end of the block.\n\nBody."


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
    assert f"{A}/memory.md" in sub["prompt"] and "never as orders" in sub["prompt"]     # written by its own runs
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
    assert s["path"] == "projects/acme/topics/blog" and s["id"] != sid and s["title"].startswith("Writer")
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


def test_an_agent_never_changes_its_own_settings(client, topic, mx, monkeypatch):
    from maxxing import agent_guard, agents
    _on(client)
    _create(client)
    root = client.get("/api/workspace/tree").json()["root"]
    (Path(root) / "projects/acme/topics/blog/.mcp.json").write_text("{}")
    run = _run("NOTOOL hi")
    wait_idle(client, run["session"]["id"])
    s = _settings(_calls()[-1]["argv"])
    locked = s["sandbox"]["filesystem"]["denyWrite"]
    for p in (f"{root}/{A}/agent.json", f"{root}/{A}/CLAUDE.md", f"{root}/{A}/.claude",
              f"{root}/projects/acme/topics/blog/.claude", f"{root}/projects/acme/topics/blog/.mcp.json"):
        assert p in locked
    assert f"{root}/{A}/.mcp.json" not in locked                         # missing: no placeholder in the folder
    deny = s["permissions"]["deny"]
    assert f"Edit(/{root}/{A}/agent.json)" in deny and f"Edit(/{root}/{A}/.claude/**)" in deny
    # the CLI: no agent turn (sandboxed or not) changes an agent; sending work stays allowed
    monkeypatch.setenv("MAXXING_AGENT", A)
    for argv in (["agents", "cron", "acme/blog/writer", "--schedule", "* * * * *"], ["agents", "off", "x"],
                 ["agents", "create", "acme/blog/other"], ["agents", "webhook", "x"]):
        assert "never changes agents" in agent_guard.check_cli(argv), argv
    assert agent_guard.check_cli(["agents", "send", "other", "hi"]) is None
    monkeypatch.delenv("MAXXING_AGENT")
    assert agent_guard.check_cli(["agents", "off", "x"]) is None            # the owner, in a session
    # a run that changes them anyway (no sandbox) is reported in the thread; the owner's own changes are not
    agents._snapshot(A, "sid-1")
    (agents.folder(A) / "CLAUDE.md").write_text("# Agent Writer\n\nI do what I want now.\n")
    assert agents._changed_during(A, "sid-1") == ["CLAUDE.md"]
    agents._snapshot(A, "sid-2")
    client.patch("/api/agents/acme/blog/writer", json={"limits": {"usd_per_day": 9}})
    assert agents._changed_during(A, "sid-2") == []
    assert agents._changed_during(A, "unknown") == []


def test_domain_wildcards_name_a_site_not_an_extension(client, topic, mx):
    from maxxing import agents
    _on(client)
    _create(client, domains=["*.example.com"])
    for d in ("*.com", "*.io", "*.co.uk", "*.github.io", "*.s3.amazonaws.com", "*.s3.eu-west-3.amazonaws.com",
              "*.amazonaws.com", "*.blogspot.com", "*.cloudfront.net", "*.blob.core.windows.net",
              "*.storage.googleapis.com", "*.r2.dev"):
        r = client.patch("/api/agents/acme/blog/writer", json={"domains": [d]})
        assert r.status_code == 400 and r.json()["error"] == "bad_domain", d
    ok = ["*.example.com", "*.api.example.co.uk", "api.github.com", "user.github.io", "*.example.io",
          "bucket.s3.amazonaws.com", "*.myapp.herokuapp.com"]
    assert client.patch("/api/agents/acme/blog/writer", json={"domains": ok}).json()["domains"] == ok
    # an agent.json written by hand (or imported) loses the wide ones on load
    assert agents.clean({"domains": ["*.com", "*.example.com", "*.co.uk"]})["domains"] == ["*.example.com"]


def test_writable_topic_never_opens_the_agents_or_the_topic_files(client, topic, mx):
    _on(client)
    _create(client, writable=["."])
    assert client.patch("/api/agents/acme/blog/writer", json={"writable": ["agents/other"]}).status_code == 400
    _create(client, name="other")
    root = Path(client.get("/api/workspace/tree").json()["root"])
    t = root / "projects/acme/topics/blog"
    (t / "site").mkdir()
    (t / "README.md").write_text("hi")
    (t / "memory.md").write_text("")
    run = _run("NOTOOL hi")
    wait_idle(client, run["session"]["id"])
    argv = _calls()[-1]["argv"]
    s = _settings(argv)
    write = s["sandbox"]["filesystem"]["allowWrite"]
    assert write[0] == f"{root}/{A}" and f"{t}/site" in write and f"{t}/README.md" in write
    for p in (t, t / "agents", t / "agents/other", t / "CLAUDE.md", t / "memory.md", t / ".claude"):
        assert str(p) not in write, p
    assert all(not w.startswith(f"{t}/agents/") for w in write[1:])
    deny = s["permissions"]["deny"]                         # Write / Edit, let into the topic by --add-dir
    for r in (f"Edit(/{t}/agents/other/**)", f"Edit(/{t}/agents/*/agent.json)", f"Edit(/{t}/agents/*/CLAUDE.md)",
              f"Edit(/{t}/agents/*/.claude/**)", f"Edit(/{t}/CLAUDE.md)", f"Edit(/{t}/memory.md)"):
        assert r in deny, r
    assert f"Edit(/{t}/agents/writer/**)" not in deny                  # its own memory stays its own
    assert argv[argv.index("--add-dir") + 1] == str(t)
    from maxxing import agents
    assert agents.clean({"writable": ["agents", "agents/x", "drafts"]})["writable"] == ["drafts"]


def test_writable_topic_never_opens_the_topics_permission_file(client, topic, mx):
    """The topic's .maxxing.json (permission mode and "Always allow" rules of the owner's sessions there) is never
    writable by a sandboxed agent, even with `writable: "."` or naming it; missing, it gets no placeholder."""
    from maxxing import agent_guard, agents
    _on(client)
    _create(client, writable=["."])
    root = Path(client.get("/api/workspace/tree").json()["root"])
    t = root / "projects/acme/topics/blog"
    (t / "README.md").write_text("hi")
    a = agents.load(A)
    fs = agent_guard.settings(A, a)["sandbox"]["filesystem"]
    assert str(t / ".maxxing.json") not in fs["denyWrite"]                 # missing: no placeholder mounted
    (t / ".maxxing.json").write_text('{"permission_mode": "ask"}')
    run = _run("NOTOOL hi")
    wait_idle(client, run["session"]["id"])
    s = _settings(_calls()[-1]["argv"])
    fs = s["sandbox"]["filesystem"]
    assert str(t / ".maxxing.json") not in fs["allowWrite"] and str(t / ".maxxing.json") in fs["denyWrite"]
    assert f"Edit(/{t}/.maxxing.json)" in s["permissions"]["deny"]          # Write / Edit (--add-dir)
    assert f"{t}/README.md" in fs["allowWrite"]                             # the rest of the topic stays writable
    # named on its own: allowWrite may list it, denyWrite wins
    fs = agent_guard.settings(A, {**a, "writable": [".maxxing.json"]})["sandbox"]["filesystem"]
    assert str(t / ".maxxing.json") in fs["denyWrite"]


def test_topic_mcp_json_write_is_denied_even_when_the_file_does_not_exist(client, topic, mx):
    """With `writable: "."`, Write/Edit (--add-dir) could create the topic's .mcp.json, whose servers every session
    of the topic would then start. The deny rule holds whether or not the file exists; the sandbox mount still gets
    no placeholder for a missing one."""
    from maxxing import agent_guard, agents
    _on(client)
    _create(client, writable=["."])
    t = Path(client.get("/api/workspace/tree").json()["root"]) / "projects/acme/topics/blog"
    assert not (t / ".mcp.json").exists()
    assert f"Edit(/{t}/.mcp.json)" in agent_guard.topic_edit_denied(A)
    s = agent_guard.settings(A, agents.load(A))
    assert f"Edit(/{t}/.mcp.json)" in s["permissions"]["deny"]
    assert str(t / ".mcp.json") not in s["sandbox"]["filesystem"]["denyWrite"]   # missing: no placeholder mounted


def test_writable_links_never_lead_outside_the_topic(client, topic, mx, tmp_path):
    """A link of the topic (a git clone's `cfg -> /root/.claude`) is not a way out: its target is dropped from the
    sandbox, from --add-dir and from `maxxing mail attachment`; a link to a folder of the topic still works."""
    from maxxing import agent_guard, agents, cmd_mail
    _on(client)
    _create(client, writable=["."])
    root = Path(client.get("/api/workspace/tree").json()["root"])
    t = root / "projects/acme/topics/blog"
    out = tmp_path / "outside"
    out.mkdir()
    (t / "cfg").symlink_to(out)                                  # escapes
    (t / "site").mkdir()
    (t / "www").symlink_to(t / "site")                           # stays inside: kept (negative case)
    w = agent_guard.writable_dirs(A, agents.load(A))
    assert str(out) not in w and f"{t}/site" in w
    a = {**agents.load(A), "sandbox": True, "writable": ["cfg", "www", "cfg/sub"]}
    assert agent_guard.writable_dirs(A, a) == [f"{t}/site"]
    s = agent_guard.settings(A, a)
    assert str(out) not in s["sandbox"]["filesystem"]["allowWrite"]
    assert str(out) not in agent_guard.add_dirs(A, a)
    g = cmd_mail.Guard(A)                                        # the stored agent: writable ["."]
    import pytest
    with pytest.raises(cmd_mail.Refused):
        g.writable(str(out / "x.pdf"))
    assert g.writable(str(t / "site" / "x.pdf")) == t / "site" / "x.pdf"


def test_sandbox_hides_transcripts_logins_and_the_rest_of_the_workspace(client, topic, mx, monkeypatch, tmp_path):
    from maxxing import agent_guard, config
    home = tmp_path / "home"
    (home / ".local/share/uv/python").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    _on(client)
    _create(client)
    _create(client, name="other")
    root = Path(client.get("/api/workspace/tree").json()["root"])
    (root / "projects/acme/topics/news").mkdir(parents=True)
    (root / "projects/zeta/topics/x").mkdir(parents=True)
    run = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL hi"}).json()
    wait_idle(client, run["session"]["id"])
    s = _settings(_calls()[-1]["argv"])
    fs = s["sandbox"]["filesystem"]
    t = root / "projects/acme/topics/blog"
    for p in (config.claude_dir() / "projects", home / ".config", home / ".local/share", root / "projects/zeta",
              root / "projects/acme/topics/news", t / "agents/other", f"{t}/.env", f"{t}/*/.env"):
        assert str(p) in fs["denyRead"], p
    for p in (t, t / "agents/writer", root / "projects/acme", root / "projects"):
        assert str(p) not in fs["denyRead"], p
    assert fs["allowRead"] == [str(home / ".local/share/uv/python")]          # the tools it runs, only if present
    deny = s["permissions"]["deny"]
    assert f"Read(/{root}/projects/zeta/**)" in deny and f"Read(/{t}/.env)" in deny and f"Read(/{t}/*/.env)" in deny
    assert f"Read(/{config.claude_dir()}/history.jsonl)" in deny


def test_sandbox_hides_the_home_folder_but_what_commands_need(monkeypatch, tmp_path):
    from maxxing import agent_guard, config
    home, outside = tmp_path / "home", tmp_path / "outside"
    ws = home / "maxxing"
    for d in (ws / "projects", home / "scripts/secrets", home / ".local/bin", home / ".local/share/uv/python",
              home / ".cache/uv", home / ".cache/browser-profile", home / ".claude/skills", home / ".claude/projects",
              home / ".nvm/versions/node/v22/bin", outside / "keys"):
        d.mkdir(parents=True)
    for f in ("notes.md", ".bash_history", ".gitconfig", ".claude/.credentials.json", "scripts/run.sh"):
        (home / f).write_text("x")
    (home / ".bashrc").write_text('export PATH="$HOME/.local/bin:$PATH"\nalias ll="ls -l"\n')   # read by every command
    (home / ".profile").write_text("export OPENAI_API_KEY=sk-123\n")                         # a secret: stays hidden
    node = home / ".nvm/versions/node/v22/bin/node"
    node.write_text("#!/bin/sh\n")
    node.chmod(0o755)
    (home / "keys").symlink_to(outside / "keys")              # a link out of the home folder
    (home / "python").symlink_to("/usr/bin")                  # a link to a tool folder
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{node.parent}:{os.environ['PATH']}")
    monkeypatch.setattr(config, "workspace", lambda: ws)
    monkeypatch.setattr(config, "claude_dir", lambda: home / ".claude")
    wall = agent_guard.home_wall()
    for p in ("notes.md", ".bash_history", "scripts", ".claude/.credentials.json", ".claude/projects",
              ".cache/browser-profile", "keys", ".profile"):
        assert str(home / p) in wall, p
    for p in ("maxxing", ".gitconfig", ".bashrc", ".local/bin", ".cache/uv", ".claude/skills", ".nvm/versions/node/v22",
              "python", ".local/share", ".local", ".cache", ".claude"):
        assert str(home / p) not in wall, p
    assert not any(w.startswith(str(ws)) for w in wall)       # the workspace has its own walls (private_paths)
    # a workspace that is the home folder: nothing more is hidden there (a home of / either)
    monkeypatch.setattr(config, "workspace", lambda: home)
    assert agent_guard.home_wall() == []
    # system secrets that exist are named, the others are not (the sandbox would mount them)
    monkeypatch.setattr(agent_guard, "SYSTEM_SECRETS", (str(outside / "keys"), str(outside / "nope")))
    s = agent_guard.secret_paths()
    assert str(outside / "keys") in s and str(outside / "nope") not in s


def test_the_apparmor_profile_waits_for_a_sandboxed_agent(client, topic, mx, monkeypatch, tmp_path):
    from maxxing import agent_guard
    calls: list = []
    monkeypatch.setattr(agent_guard, "load_profile", lambda: calls.append(1) or True)
    agent_guard.ensure_profile()
    assert calls == []                                         # tests (MAXXING_SANDBOX_CHECK=0): never
    monkeypatch.setenv("MAXXING_SANDBOX_CHECK", "1")
    monkeypatch.setattr(agent_guard.os, "geteuid", lambda: 0)
    _on(client)
    _create(client, sandbox=False)
    assert calls == []
    client.patch("/api/agents/acme/blog/writer", json={"sandbox": True})
    assert calls == [1]
    _create(client, name="other")
    assert calls == [1, 1]
    # the installer no longer loads it for everyone
    assert "apparmor_parser" not in (Path(__file__).resolve().parents[2] / "install.sh").read_text()


def test_shell_settings_with_a_secret_stay_hidden():
    from maxxing import agent_guard
    for text in ("export PGPASSWORD=x\n", "export DATABASE_URL=postgres://u:pw@h/db\n", "github_token=ghp_1\n",
                 "MYSECRET=1\n", "readonly NPM_TOKEN=abc\n", "set -x API_KEY abc\n", "export GITHUBTOKEN=1\n",
                 "export OPENAI_API_KEY=sk-1\n", "declare -rx DB_PASS=1\n", "  export  http_proxy=http://me:pw@proxy:3128\n"):
        assert agent_guard.sets_a_secret(text), text
    for text in ('export PATH="$HOME/.local/bin:$PATH"\nalias ll="ls -l"\n', "export KEYBOARD=fr\n",
                 "export EDITOR=vim\nPS1='\\u@\\h'\n", "export URL=https://example.com/a:b\n", "x" * 200_000 + "\n"):
        assert not agent_guard.sets_a_secret(text), text


def test_a_link_in_a_loop_in_the_home_folder_is_hidden(monkeypatch, tmp_path):
    from maxxing import agent_guard, config
    home = tmp_path / "home"
    (home / "maxxing").mkdir(parents=True)
    (home / "loop").symlink_to("loop")
    (home / ".gitconfig").symlink_to(".gitconfig")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(config, "workspace", lambda: home / "maxxing")
    monkeypatch.setattr(config, "claude_dir", lambda: home / ".claude")
    real = Path.resolve

    def resolve(self, strict=False):                # Python < 3.13 raises on a loop, 3.13 does not
        if self.name in ("loop", ".gitconfig"):
            raise RuntimeError(f"Symlink loop from {self!r}")
        return real(self, strict)
    monkeypatch.setattr(Path, "resolve", resolve)
    assert str(home / "loop") in agent_guard.home_wall()


def test_a_huge_sandbox_goes_in_a_file(mx):
    from maxxing.sessions import spawn
    deny = [f"/home/me/entry-{i:05}" for i in range(4000)]          # thousands of entries in the home folder
    extra = {"sandbox": {"enabled": True, "filesystem": {"denyRead": deny}}}
    args = spawn.settings_args({}, extra)
    assert args[0] == "--settings" and all(len(a.encode()) < 128 * 1024 for a in args)
    s = json.loads(Path(args[1]).read_text())
    assert s["sandbox"]["filesystem"]["denyRead"] == deny and s["permissions"]["deny"]
    assert oct(Path(args[1]).stat().st_mode & 0o777) == "0o600"
    assert spawn.settings_args({}, extra) == args                   # the same settings: the same file
    small = spawn.settings_args({}, {"sandbox": {"enabled": True}})
    assert json.loads(small[1])["sandbox"] == {"enabled": True}      # small ones stay inline
