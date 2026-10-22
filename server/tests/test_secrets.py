import os

from _org_helpers import client, org  # noqa: F401
from maxxing import config, vault


def test_crud(client, org):
    assert client.get("/api/secrets").json() == []
    assert client.put("/api/secrets/OPENAI_KEY", json={"note": "x"}).json()["error"] == "value_required"
    assert client.put("/api/secrets/OPENAI_KEY", json={"value": "sk-1234567890", "note": " main "}).json() == {"ok": True}
    assert client.put("/api/secrets/SHORT", json={"value": "abc"}).status_code == 200
    lst = client.get("/api/secrets").json()
    assert [x["name"] for x in lst] == ["OPENAI_KEY", "SHORT"]
    assert lst[0]["preview"] == "sk-1…" and lst[0]["note"] == "main" and lst[0]["expose"] is False
    assert lst[1]["preview"] == "…" and "value" not in lst[0]
    assert client.get("/api/secrets/OPENAI_KEY/reveal").json() == {"value": "sk-1234567890"}
    assert client.get("/api/secrets/NOPE/reveal").status_code == 404

    client.put("/api/secrets/OPENAI_KEY", json={"expose": True})            # value kept
    assert client.get("/api/secrets/OPENAI_KEY/reveal").json()["value"] == "sk-1234567890"
    assert vault.exposed_env() == {"OPENAI_KEY": "sk-1234567890"}
    assert oct(os.stat(config.secrets_path()).st_mode)[-3:] == "600"

    assert client.delete("/api/secrets/OPENAI_KEY").json() == {"ok": True}
    assert client.delete("/api/secrets/OPENAI_KEY").status_code == 404
    assert vault.exposed_env() == {}
    client.delete("/api/secrets/SHORT")
    assert "vault" not in config.load_secrets()


def test_names(client):
    for bad in ("lower", "1ABC", "A", "WITH-DASH", "PATH", "MAXXING_STATE", "X" * 65):
        r = client.put(f"/api/secrets/{bad}", json={"value": "v"})
        assert r.status_code == 400, bad
    assert client.put("/api/secrets/A1", json={"value": "v"}).status_code == 200


def test_vault_tolerates_garbage(org):
    config.set_secret("vault", {"OK_ONE": {"value": "v", "expose": True}, "BAD": "string", "ALSO": {"no": 1}})
    assert [x["name"] for x in vault.list_secrets()] == ["OK_ONE"]
    assert vault.exposed_env() == {"OK_ONE": "v"}
    config.set_secret("vault", "nonsense")
    assert vault.list_secrets() == [] and vault.exposed_env() == {}


def test_state_files_are_private(mx):
    """Files the server writes in its state folder are 0600; older 0644 ones are tightened at startup."""
    import os
    import stat
    from maxxing import config
    config.update_config(language="fr")
    assert stat.S_IMODE(os.stat(config.config_path()).st_mode) == 0o600
    old = config.STATE / "claude-auth.json"
    old.write_text("{}")
    os.chmod(old, 0o644)
    assert config.tighten_state() >= 1 and stat.S_IMODE(os.stat(old).st_mode) == 0o600
    from maxxing.sessions import store
    store.append_log("12345678-1234-1234-1234-123456789012", {"type": "mx_note", "text": "x"})
    log = store.log_path("12345678-1234-1234-1234-123456789012")
    assert stat.S_IMODE(os.stat(log).st_mode) == 0o600
