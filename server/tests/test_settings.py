from _org_helpers import client, org  # noqa: F401
from maxxing import config


def test_get_defaults(client, org):
    s = client.get("/api/settings").json()
    assert s == {"timezone": "UTC", "language": "en", "public_url": "", "files_root": str(org.tmp),
                 "presentation_default": False, "usage_widget": False, "git_page": False, "infra_page": False,
                 "maxxing_mode": False,
                 "memory_max_lines": 200, "result_line_hidden": [], "donation_hidden": False}


def test_maxxing_mode_is_an_opt_in_feature(client, org):
    assert config.load_config().get("maxxing_mode") is False             # beta: off by default
    r = client.put("/api/settings", json={"maxxing_mode": True})
    assert r.status_code == 200 and r.json()["maxxing_mode"] is True
    assert config.load_config()["maxxing_mode"] is True
    assert client.put("/api/settings", json={"timezone": "UTC"}).json()["maxxing_mode"] is True
    assert client.put("/api/settings", json={"maxxing_mode": "maybe"}).status_code == 422
    assert client.put("/api/settings", json={"maxxing_mode": False}).json()["maxxing_mode"] is False


def test_donation_hidden(client, org):
    assert config.load_config().get("donation_hidden") is False          # default: the donation links show
    r = client.put("/api/settings", json={"donation_hidden": True})
    assert r.status_code == 200 and r.json()["donation_hidden"] is True
    assert config.load_config()["donation_hidden"] is True               # persisted in config.json
    assert client.get("/api/settings").json()["donation_hidden"] is True
    r = client.put("/api/settings", json={"timezone": "UTC"})            # another change keeps it
    assert r.json()["donation_hidden"] is True
    assert client.put("/api/settings", json={"donation_hidden": "maybe"}).status_code == 422
    assert client.put("/api/settings", json={"donation_hidden": False}).json()["donation_hidden"] is False
    assert config.load_config()["donation_hidden"] is False


def test_result_line_hidden(client, org):
    r = client.put("/api/settings", json={"result_line_hidden": ["tokens", "cost", "cost"]})
    assert r.json()["result_line_hidden"] == ["cost", "tokens"]
    assert config.load_config()["result_line_hidden"] == ["cost", "tokens"]
    assert client.put("/api/settings", json={"result_line_hidden": ["price"]}).status_code == 422
    assert client.put("/api/settings", json={"result_line_hidden": []}).json()["result_line_hidden"] == []


def test_put_and_validate(client, org):
    r = client.put("/api/settings", json={"timezone": "Europe/Paris", "language": "fr",
                                          "public_url": "https://ui.example.com/", "usage_widget": True,
                                          "presentation_default": True})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["timezone"] == "Europe/Paris" and s["language"] == "fr" and s["public_url"] == "https://ui.example.com"
    assert s["usage_widget"] is True and s["presentation_default"] is True
    cfg = config.load_config()
    assert cfg["timezone"] == "Europe/Paris" and cfg["port"] == 8787          # other keys untouched

    assert client.put("/api/settings", json={"timezone": "Mars/Base"}).json()["error"] == "invalid_timezone"
    assert client.put("/api/settings", json={"language": "de"}).status_code == 422
    assert client.put("/api/settings", json={"public_url": "ftp://x"}).json()["error"] == "invalid_url"
    assert client.put("/api/settings", json={"files_root": "/does/not/exist"}).json()["error"] == "invalid_files_root"
    assert client.put("/api/settings", json={"files_root": "relative"}).status_code == 400
    assert client.put("/api/settings", json={"files_root": str(org.ws)}).json()["files_root"] == str(org.ws)
    assert client.put("/api/settings", json={"public_url": ""}).json()["public_url"] == ""
    assert client.get("/api/settings").json()["language"] == "fr"


def test_timezone_change_aligns_the_system_zone(client, monkeypatch):
    from maxxing import crons
    seen = []
    monkeypatch.setattr(crons, "align_system_timezone", lambda tz: seen.append(tz) or True)
    client.put("/api/settings", json={"language": "fr"})
    client.put("/api/settings", json={"timezone": "Europe/Paris"})
    assert seen == ["Europe/Paris"]


def test_kept_server_clock_is_never_switched(client, monkeypatch):
    from maxxing import config, crons
    config.update_config(system_clock="keep")
    seen, synced = [], []
    monkeypatch.setattr(crons, "align_system_timezone", lambda tz: seen.append(tz) or True)
    monkeypatch.setattr(crons, "sync_crontab", lambda *a: synced.append(1) or "")
    client.put("/api/settings", json={"timezone": "Europe/Paris"})
    assert seen == [] and synced == [1]


def test_align_system_timezone_is_skipped_in_isolation(monkeypatch):
    from maxxing import crons
    monkeypatch.setattr(crons.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    assert crons.align_system_timezone("Europe/Paris") is False         # MAXXING_SYSTEM_TZ=0 in conftest


def test_profile_pseudo(client):
    assert client.get("/api/settings/profile").json() == {"name": "", "color": "", "emoji": ""}
    r = client.put("/api/settings/profile", json={"name": "  Léa   <b>Martin</b> ", "color": "teal", "emoji": "🔥"})
    assert r.status_code == 200
    assert r.json() == {"name": "Léa bMartin/b", "color": "teal", "emoji": "🔥"}
    assert client.get("/api/settings/profile").json()["name"] == "Léa bMartin/b"
    assert client.put("/api/settings/profile", json={"name": "x", "color": "pink"}).status_code == 400
    assert client.put("/api/settings/profile", json={"name": "x", "emoji": "a b"}).status_code == 400
    assert client.put("/api/settings/profile", json={"name": "x" * 50}).json()["name"] == "x" * 32
    client.cookies.clear()
    assert client.get("/api/settings/profile").status_code == 401
