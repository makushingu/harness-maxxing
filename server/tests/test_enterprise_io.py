"""Enterprise templates, export and import (enterprise_templates.py, enterprise_io.py)."""
from __future__ import annotations

import io
import json
import zipfile

import pytest
from maxxing import agents, cli, enterprise_io, enterprises

E = "/api/enterprises"
W = "projects/acme/topics/blog/agents/writer"


def _on(client):
    assert client.put("/api/settings", json={"agents_page": True, "enterprises_page": True}).status_code == 200


@pytest.fixture
def cl(client, topic):
    _on(client)
    assert client.post("/api/agents", json={"topic_path": topic, "name": "writer", "sandbox": False}).status_code == 200
    return client


def _zip(files: dict[str, str | bytes], **attrs) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _names(data: bytes) -> list[str]:
    return zipfile.ZipFile(io.BytesIO(data)).namelist()


def _chart(**extra) -> str:
    return json.dumps({"id": "shop", "name": "Shop", "positions": [{"id": "boss", "title": "Boss", "job": "Runs it"}],
                       **extra})


# ---- templates ---------------------------------------------------------------------------------------------
def test_templates_list(cl):
    items = cl.get(f"{E}/templates").json()["templates"]
    assert [t["id"] for t in items] == ["marketing-agency", "ecommerce", "content-studio", "research-watch"]
    for t in items:
        assert t["name"] and t["description"]
        assert {"id", "title", "reports_to", "department"} == set(t["positions"][0])


def test_create_from_template(cl):
    r = cl.post(E, json={"id": "agency", "template": "marketing-agency"})
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["name"] == "Marketing agency"
    assert {p["id"] for p in e["positions"]} >= {"director", "content-lead", "writer"}
    assert all(p["agent"] is None and p["state"] == "vacant" and p["job"] for p in e["positions"])
    assert set(e["departments"]) == {"strategy", "content", "social"}
    assert e["settings"]["autonomy"] == "balanced" and e["settings"]["digest"]["enabled"] is True
    raw = enterprises.load("agency")
    assert next(p for p in raw["positions"] if p["id"] == "writer")["suggested_template"] == "writer"
    assert "honest" in (enterprises.folder("agency") / "CLAUDE.md").read_text(encoding="utf-8")


def test_every_template_is_a_valid_chart_with_known_agent_templates(cl):
    from maxxing import agent_templates
    known = {t["id"] for t in agent_templates.TEMPLATES}
    for t in cl.get(f"{E}/templates").json()["templates"]:
        r = cl.post(E, json={"id": "t-" + t["id"], "template": t["id"]})
        assert r.status_code == 200, r.text
        for p in enterprises.load("t-" + t["id"])["positions"]:
            assert p.get("suggested_template", "writer") in known


def test_unknown_template(cl):
    r = cl.post(E, json={"id": "x", "template": "nope"})
    assert r.status_code == 400 and r.json()["error"] == "bad_template"


# ---- export ------------------------------------------------------------------------------------------------
def test_export_content_has_no_secret(cl, topic, mx):
    assert cl.post(E, json={"id": "acme-group", "name": "Acme", "projects": ["acme"]}).status_code == 200
    assert cl.post(f"{E}/acme-group/positions", json={"id": "lead", "title": "Lead", "job": "Leads."}).status_code == 200
    assert cl.post(f"{E}/acme-group/positions",
                   json={"id": "writer", "title": "Writer", "reports_to": "lead", "agent": W, "job": "Writes."}).status_code == 200
    assert cl.put("/api/secrets/VAULT_KEY_X", json={"value": "s3cret-vault-value"}).status_code == 200
    enterprises.update("acme-group", {"envelope": {"usd_per_day": 5, "keys": ["VAULT_KEY_X"]},
                                      "grants": [{"id": "g1", "position": "lead", "category": "spending",
                                                  "ceiling": 10, "until": "2099-01-01"}]})
    enterprises.log("acme-group", "decision", "private decision")
    (enterprises.folder("acme-group") / "files" / "brand.md").write_text("Our voice is calm.", encoding="utf-8")
    (enterprises.folder("acme-group") / "files" / "leak.txt").write_text("key sk-ant-api03-" + "a" * 90, encoding="utf-8")
    (agents.folder(W) / "CLAUDE.md").write_text("# Agent writer\n\nYou write the blog.\n\n@memory.md\n", encoding="utf-8")

    r = cl.get(f"{E}/acme-group/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = _names(r.content)
    assert "enterprise.json" in names and "CLAUDE.md" in names and "files/brand.md" in names
    assert "agents/writer.md" in names and "files/leak.txt" not in names
    assert "agents/lead.md" not in names                      # vacant position: no agent file
    blob = b"".join(zipfile.ZipFile(io.BytesIO(r.content)).read(n) for n in names)
    for forbidden in (b"VAULT_KEY_X", b"s3cret-vault-value", b"g1", b"private decision", b"sk-ant", W.encode()):
        assert forbidden not in blob
    z = zipfile.ZipFile(io.BytesIO(r.content))
    chart = json.loads(z.read("enterprise.json"))
    assert chart["grants"] == [] and {p["id"] for p in chart["positions"]} == {"lead", "writer"}
    agent = z.read("agents/writer.md").decode()
    assert agent.startswith("---\nname: writer\ndescription: ") and "model: inherit" in agent
    assert "You write the blog." in agent and "@memory.md" not in agent


def test_export_unknown(cl):
    assert cl.get(f"{E}/nope/export").status_code == 404


# ---- import ------------------------------------------------------------------------------------------------
def test_round_trip(cl):
    assert cl.post(E, json={"id": "agency", "template": "ecommerce"}).status_code == 200
    (enterprises.folder("agency") / "files" / "sub").mkdir()
    (enterprises.folder("agency") / "files" / "sub" / "a.md").write_text("hello", encoding="utf-8")
    data = cl.get(f"{E}/agency/export").content
    r = cl.post(f"{E}/import", content=data, headers={"content-type": "application/zip"})
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["id"] == "agency-2" and e["projects"] == [] and e["skipped"] == []
    assert len(e["positions"]) == 5 and all(p["state"] == "vacant" for p in e["positions"])
    assert set(e["departments"]) == {"catalogue", "care", "logistics"}
    assert (enterprises.folder("agency-2") / "files" / "sub" / "a.md").read_text(encoding="utf-8") == "hello"
    assert enterprises.load("agency-2")["grants"] == []
    again = cl.post(f"{E}/import", content=data).json()
    assert again["id"] == "agency-3"


def test_import_keeps_agent_files_aside(cl):
    z = _zip({"enterprise.json": _chart(), "agents/boss.md": "---\nname: boss\n---\n\nRole\n"})
    e = cl.post(f"{E}/import", content=z).json()
    assert e["id"] == "shop"
    assert (enterprises.folder("shop") / "files" / "imported-agents" / "boss.md").is_file()


@pytest.mark.parametrize("files,code", [
    ({"enterprise.json": _chart(), "../evil.txt": "x"}, "unsafe_path"),
    ({"enterprise.json": _chart(), "files/../../evil.txt": "x"}, "unsafe_path"),
    ({"enterprise.json": _chart(), "/abs.txt": "x"}, "unsafe_path"),
    ({"enterprise.json": _chart(), "notes.txt": "x"}, "unexpected_file"),
    ({"enterprise.json": _chart(), "agents/Bad Name.md": "x"}, "unexpected_file"),
    ({"enterprise.json": _chart(), "files/.claude/agents/a.md": "x"}, "claude_config"),
    ({"enterprise.json": _chart(), "files/.claude/commands/c.md": "x"}, "claude_config"),
    ({"enterprise.json": _chart(), "files/.mcp.json": "{}"}, "claude_config"),
    ({"CLAUDE.md": "x"}, "not_an_export"),
    ({"enterprise.json": "not json"}, "not_an_export"),
])
def test_import_refusals(cl, files, code):
    r = cl.post(f"{E}/import", content=_zip(files))
    assert r.status_code == 400 and r.json()["error"] == code, r.text
    assert enterprises.names() == []                            # nothing was written


def test_import_refuses_a_symlink(cl):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("enterprise.json", _chart())
        info = zipfile.ZipInfo("files/link")
        info.external_attr = 0o120777 << 16
        z.writestr(info, "/etc/passwd")
    r = cl.post(f"{E}/import", content=buf.getvalue())
    assert r.status_code == 400 and r.json()["error"] == "symlink"


def test_import_too_big_and_not_a_zip(cl, monkeypatch):
    assert cl.post(f"{E}/import", content=b"hello").json()["error"] == "bad_zip"
    monkeypatch.setattr(enterprise_io, "MAX_ZIP", 100)
    r = cl.post(f"{E}/import", content=_zip({"enterprise.json": _chart(), "files/a": "x" * 500}))
    assert r.status_code == 413 and r.json()["error"] == "too_big"
    monkeypatch.setattr(enterprise_io, "MAX_ZIP", 50 * 1024 * 1024)
    monkeypatch.setattr(enterprise_io, "FILE_CAP", 10)
    r = cl.post(f"{E}/import", content=_zip({"enterprise.json": _chart(), "files/a": "x" * 500}))
    assert r.status_code == 413
    monkeypatch.setattr(enterprise_io, "MAX_UNZIPPED", 100)
    r = cl.post(f"{E}/import", content=_zip({"enterprise.json": _chart(), "files/a": "y" * 500}))
    assert r.status_code == 413


def test_import_skips_a_file_that_looks_like_a_secret(cl):
    z = _zip({"enterprise.json": _chart(), "files/leak.txt": "sk-ant-api03-" + "a" * 90, "files/ok.txt": "fine"})
    e = cl.post(f"{E}/import", content=z).json()
    assert [s["file"] for s in e["skipped"]] == ["files/leak.txt"]
    assert not (enterprises.folder("shop") / "files" / "leak.txt").exists()


def test_import_needs_the_feature(client):
    r = client.post(f"{E}/import", content=_zip({"enterprise.json": _chart()}))
    assert r.status_code == 404 and r.json()["error"] == "feature_off"


# ---- CLI ---------------------------------------------------------------------------------------------------
def test_cli_export_import(cl, tmp_path, capsys):
    assert cl.post(E, json={"id": "studio", "template": "content-studio"}).status_code == 200
    out = tmp_path / "studio.zip"
    assert cli.main(["enterprise", "export", "studio", "-o", str(out)]) == 0
    assert "enterprise.json" in zipfile.ZipFile(out).namelist()
    capsys.readouterr()
    assert cli.main(["enterprise", "import", str(out), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "studio-2"
    assert cli.main(["enterprise", "export", "missing", "-o", str(tmp_path / "m.zip")]) == 2
    bad = tmp_path / "bad.zip"
    bad.write_bytes(_zip({"enterprise.json": _chart(), "x.txt": "1"}))
    assert cli.main(["enterprise", "import", str(bad)]) == 2
