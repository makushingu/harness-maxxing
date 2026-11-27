"""A vault key limited to some projects / topics (`topics`) is given only to their sessions and jobs."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from maxxing import cli, config, crons, vault, vault_files
from maxxing.sessions import spawn

from conftest import wait_idle

T = "projects/acme/topics/blog"


def _calls() -> list[dict]:
    f = Path(os.environ["FAKE_CLAUDE_DIR"]) / "calls.jsonl"
    return [json.loads(ln) for ln in f.read_text().splitlines()] if f.exists() else []


def test_without_topics_nothing_changes(mx):
    vault.put("OPEN_KEY", "v1", expose=True)
    assert "topics" not in config.load_secrets()["vault"]["OPEN_KEY"]          # no new field on a plain key
    assert vault.list_secrets()[0]["topics"] == []
    for path in ("", None, "projects/acme", T, T + "/agents/writer"):
        assert vault.exposed_env(path) == {"OPEN_KEY": "v1"}
    assert vault.exposed_env() == {"OPEN_KEY": "v1"} and spawn.auth_env()["OPEN_KEY"] == "v1"


def test_a_key_follows_its_topics_by_segment(mx):
    vault.put("SHOP_KEY", "s", expose=True, topics=["projects/acme"])
    vault.put("BLOG_KEY", "b", expose=True, topics=[T, "projects/other/topics/x/"])
    vault.put("OPEN_KEY", "o", expose=True)
    assert vault.exposed_env("") == {"OPEN_KEY": "o"} == vault.exposed_env(None) == vault.exposed_env()
    assert vault.exposed_env("projects/acme") == {"OPEN_KEY": "o", "SHOP_KEY": "s"}
    assert vault.exposed_env(T) == {"OPEN_KEY": "o", "SHOP_KEY": "s", "BLOG_KEY": "b"}
    assert vault.exposed_env("/" + T + "/") == vault.exposed_env(T)
    assert vault.exposed_env("projects/acme/topics/shop") == {"OPEN_KEY": "o", "SHOP_KEY": "s"}
    assert vault.exposed_env("projects/acme/topics/blog-2") == {"OPEN_KEY": "o", "SHOP_KEY": "s"}   # not a prefix match
    assert vault.exposed_env("projects/acme2/topics/blog") == {"OPEN_KEY": "o"}
    assert vault.exposed_env("projects/ac") == {"OPEN_KEY": "o"}
    assert vault.exposed_env("projects/other/topics/x") == {"OPEN_KEY": "o", "BLOG_KEY": "b"}
    assert vault.list_secrets()[0] | {"updated": 0, "preview": ""} == {
        "name": "BLOG_KEY", "note": "", "expose": True, "topics": [T, "projects/other/topics/x"], "updated": 0,
        "preview": ""}
    # not exposed: never given, whatever its topics
    vault.put("SHOP_KEY", expose=False)
    assert "SHOP_KEY" not in vault.exposed_env("projects/acme")
    assert vault.list_secrets()[2]["topics"] == ["projects/acme"]              # an omitted field keeps its value
    vault.put("SHOP_KEY", expose=True, topics=[])                              # cleared: every topic again
    assert "topics" not in config.load_secrets()["vault"]["SHOP_KEY"]
    assert vault.exposed_env("")["SHOP_KEY"] == "s"


@pytest.mark.parametrize("bad", [
    [""], ["projects"], ["acme"], ["projects/Acme"], ["projects/acme/blog"], ["projects/acme/topics"],
    ["projects/acme/topics/blog/agents/writer"], ["projects/acme/../x"], ["projects/acme\nx"], [3], "projects/acme",
    [f"projects/p{i}" for i in range(51)],
])
def test_topics_are_validated(mx, bad):
    with pytest.raises(vault.VaultError) as e:
        vault.put("SOME_KEY", "v", expose=True, topics=bad)
    assert e.value.code == "invalid_topics" and vault.get("SOME_KEY") is None


def test_topics_need_no_folder_and_lose_duplicates(mx):
    vault.put("SOME_KEY", "v", expose=True, topics=["projects/gone/topics/deleted", "/projects/gone/topics/deleted/"])
    assert vault.list_secrets()[0]["topics"] == ["projects/gone/topics/deleted"]
    vault.put("SOME_KEY", topics=[f"projects/p{i}" for i in range(50)])
    assert len(vault.list_secrets()[0]["topics"]) == 50


def test_a_hand_edited_scope_fails_closed(mx):
    vault.put("ODD_KEY", "v", expose=True)
    for odd in ("projects/acme", {"a": 1}, [1], [""]):
        v = config.load_secrets()["vault"]
        v["ODD_KEY"]["topics"] = odd
        config.set_secret("vault", v)
        assert vault.exposed_env("projects/acme") == {} and vault.exposed_env("") == {}
        assert vault.list_secrets()[0]["topics"] == []


def test_secret_files_follow_the_same_rule(mx):
    vault_files.put("SA_JSON", b"{}", expose=True, topics=[T])
    vault_files.put("OPEN_FILE", b"x", expose=True)
    path = str(mx["state"] / "secret-files" / "SA_JSON")
    assert set(vault_files.exposed_files_env()) == {"OPEN_FILE"} == set(vault_files.exposed_files_env("projects/acme"))
    assert vault_files.exposed_files_env(T)["SA_JSON"] == path
    assert {f["name"]: f["topics"] for f in vault_files.list_files()} == {"OPEN_FILE": [], "SA_JSON": [T]}
    assert spawn.auth_env(path=T)["SA_JSON"] == path and "SA_JSON" not in spawn.auth_env()
    with pytest.raises(vault.VaultError):
        vault_files.put("SA_JSON", topics=["nope"])
    vault_files.put("SA_JSON", note="kept")                                   # metadata only: the scope stays
    assert vault_files.list_files()[1]["topics"] == [T]
    vault_files.put("SA_JSON", topics=[])
    assert "SA_JSON" in vault_files.exposed_files_env()


def test_spawn_env_takes_the_path_and_agents_keep_their_list(mx):
    vault.put("BLOG_KEY", "b", expose=True, topics=[T])
    assert "BLOG_KEY" not in spawn.claude_env() and "BLOG_KEY" not in spawn.claude_env(None, "default")
    assert spawn.claude_env(path=T)["BLOG_KEY"] == "b"
    assert "BLOG_KEY" not in spawn.claude_env(path="projects/acme/topics/shop")
    assert "BLOG_KEY" not in spawn.claude_env(keys=[], path=T)                 # an agent: its own list only
    assert spawn.claude_env(keys=["BLOG_KEY"], path="projects/zzz/topics/a/agents/b")["BLOG_KEY"] == "b"


def test_api_accepts_and_returns_topics(client):
    r = client.put("/api/secrets/SHOP_KEY", json={"value": "abcdefgh", "expose": True, "topics": ["projects/acme"]})
    assert r.status_code == 200, r.text
    assert client.get("/api/secrets").json()[0]["topics"] == ["projects/acme"]
    assert client.put("/api/secrets/SHOP_KEY", json={"note": "n"}).status_code == 200
    assert client.get("/api/secrets").json()[0]["topics"] == ["projects/acme"]
    r = client.put("/api/secrets/SHOP_KEY", json={"topics": ["projects/acme/x"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_topics"
    assert client.put("/api/secrets/SHOP_KEY", json={"topics": []}).status_code == 200
    assert client.get("/api/secrets").json()[0]["topics"] == []

    hdr = {"content-type": "application/octet-stream"}
    r = client.put("/api/secret-files/SA_JSON", params={"expose": "true", "topics": f"projects/acme, {T}"},
                   content=b"{}", headers=hdr)
    assert r.status_code == 200, r.text
    assert client.get("/api/secret-files").json()[0]["topics"] == ["projects/acme", T]
    assert client.put("/api/secret-files/SA_JSON", params={"note": "n"}, headers=hdr).status_code == 200
    assert client.get("/api/secret-files").json()[0]["topics"] == ["projects/acme", T]
    r = client.put("/api/secret-files/SA_JSON", params={"topics": "nope"}, headers=hdr)
    assert r.status_code == 400 and r.json()["error"] == "invalid_topics"
    assert client.put("/api/secret-files/SA_JSON", params={"topics": ""}, headers=hdr).status_code == 200
    assert client.get("/api/secret-files").json()[0]["topics"] == []


def test_a_session_gets_the_keys_of_its_topic_only(client, topic):
    assert client.post("/api/workspace/projects/acme/topics", json={"name": "shop"}).status_code == 200
    vault.put("MX_TEST_VAR", "secret-1", expose=True, topics=[topic])
    s = client.post("/api/sessions", json={"path": "projects/acme/topics/shop", "message": "NOTOOL hi"})
    assert s.status_code == 200, s.text
    wait_idle(client, s.json()["id"])
    assert _calls()[-1]["cwd"].endswith("/topics/shop") and _calls()[-1]["env"]["MX_TEST_VAR"] is None
    s = client.post("/api/sessions", json={"path": "", "message": "NOTOOL hi"})   # the workspace root
    wait_idle(client, s.json()["id"])
    assert _calls()[-1]["env"]["MX_TEST_VAR"] is None
    s = client.post("/api/sessions", json={"path": topic, "message": "NOTOOL hi"})
    wait_idle(client, s.json()["id"])
    assert _calls()[-1]["env"]["MX_TEST_VAR"] == "secret-1"
    vault.put("MX_TEST_VAR", topics=["projects/acme"])                         # the whole project
    s = client.post("/api/sessions", json={"path": "projects/acme/topics/shop", "message": "NOTOOL hi"})
    wait_idle(client, s.json()["id"])
    assert _calls()[-1]["env"]["MX_TEST_VAR"] == "secret-1"


def test_a_job_gets_the_keys_of_its_topic_only(mx):
    vault.put("BLOG_KEY", "b", expose=True, topics=[T])
    vault.put("OPEN_KEY", "o", expose=True)
    vault_files.put("BLOG_FILE", b"x", expose=True, topics=["projects/acme"])
    job = {"id": "c_1", "name": "n", "kind": "shell", "command": "true"}
    env = crons._job_env(job)
    assert env["OPEN_KEY"] == "o" and "BLOG_KEY" not in env and "BLOG_FILE" not in env
    assert "BLOG_KEY" not in crons._job_env({**job, "topic_path": ""})
    assert "BLOG_KEY" not in crons._job_env({**job, "topic_path": "projects/acme/topics/shop"})
    env = crons._job_env({**job, "topic_path": T})
    assert env["BLOG_KEY"] == "b" and env["OPEN_KEY"] == "o" and env["BLOG_FILE"].endswith("/BLOG_FILE")


def _keys(monkeypatch, *argv, stdin=""):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(stdin.encode()), encoding="utf-8"))
    return cli.main(["keys", *argv])


def test_cli_sets_shows_and_clears_the_scope(mx, monkeypatch, capsys, tmp_path):
    assert _keys(monkeypatch, "set", "SHOP_KEY", "--topics", f"projects/acme, {T}", stdin="v") == 0
    assert vault.list_secrets()[0]["topics"] == ["projects/acme", T]
    assert _keys(monkeypatch, "set", "SHOP_KEY", stdin="v2") == 0              # an update keeps the scope
    assert vault.list_secrets()[0]["topics"] == ["projects/acme", T]
    capsys.readouterr()
    assert _keys(monkeypatch, "list") == 0
    assert "[acme] [acme/blog]" in capsys.readouterr().out
    assert _keys(monkeypatch, "list", "--json") == 0
    assert json.loads(capsys.readouterr().out)[0]["topics"] == ["projects/acme", T]
    assert _keys(monkeypatch, "set", "SHOP_KEY", "--topics", "projects/acme/blog", stdin="v3") == 2
    assert vault.get("SHOP_KEY") == "v2"
    assert _keys(monkeypatch, "set", "SHOP_KEY", "--topics", "", stdin="v2") == 0
    assert vault.list_secrets()[0]["topics"] == [] and vault.exposed_env()["SHOP_KEY"] == "v2"
    f = tmp_path / "sa.json"
    f.write_bytes(b"{}")
    assert _keys(monkeypatch, "put-file", "SA_JSON", str(f), "--topics", T) == 0
    assert vault_files.list_files()[0]["topics"] == [T] and "SA_JSON" not in vault_files.exposed_files_env()
