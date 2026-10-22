import pytest

from _org_helpers import client, org  # noqa: F401
from maxxing import config


@pytest.fixture
def docs(tmp_path, monkeypatch):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "02-sessions.md").write_text("# Sessions\n\nText.\n")
    (d / "01-getting-started.md").write_text("---\nsection: Basics\n---\n# Getting started\n\nHello.\n")
    (d / "10-extensions.md").write_text("Intro without heading\n")
    (d / "README.txt").write_text("ignored")
    (d / "Bad Name.md").write_text("# ignored")
    monkeypatch.setattr(config, "DOCS_DIR", d)
    return d


def test_list_and_read(client, docs):
    lst = client.get("/api/docs").json()
    assert lst == [{"slug": "getting-started", "title": "Getting started", "section": "Basics", "order": 1},
                   {"slug": "sessions", "title": "Sessions", "section": "General", "order": 2},
                   {"slug": "extensions", "title": "Extensions", "section": "General", "order": 10}]
    page = client.get("/api/docs/getting-started").json()
    assert page["title"] == "Getting started" and page["markdown"].startswith("# Getting started")
    assert client.get("/api/docs/nope").status_code == 404
    assert client.get("/api/docs/..%2F..%2Fetc").status_code == 404


def test_missing_dir(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DOCS_DIR", tmp_path / "none")
    assert client.get("/api/docs").json() == []


def test_full_and_cache(client, docs):
    full = client.get("/api/docs", params={"full": 1}).json()
    assert [x["slug"] for x in full] == ["getting-started", "sessions", "extensions"]
    assert full[1]["markdown"] == "# Sessions\n\nText.\n"
    (docs / "02-sessions.md").write_text("# Sessions renamed\n\nNew text, longer.\n")    # a new version is re-read
    assert client.get("/api/docs/sessions").json()["title"] == "Sessions renamed"
    (docs / "03-new.md").write_text("# New\n")
    assert "new" in [x["slug"] for x in client.get("/api/docs").json()]


def test_all_updates_in_settings(client, docs):
    """Settings -> Updates lists every version (the docs have no changelog page)."""
    import re
    n = len(re.findall(r"^## ", (config.CODE / "CHANGELOG.md").read_text(), re.M))
    r = client.get("/api/system/changelog", params={"limit": 500}).json()
    assert len(r["entries"]) == n and r["entries"][0]["current"]
    assert "changelog" not in [x["slug"] for x in client.get("/api/docs").json()]


def test_every_version_is_documented():
    """A release without its changelog entry or its upgrade note fails here: the docs never fall behind."""
    import re
    from maxxing import __version__
    from maxxing.cmd_core import version_key
    cl = (config.CODE / "CHANGELOG.md").read_text()
    seen = re.findall(r"^## (\d+\.\d+\.\d+(?:-alpha\.\d+)?)", cl, re.M)
    as_pep = [v.replace("-alpha.", "a") for v in seen]
    assert as_pep[0] == __version__, "CHANGELOG.md: add the entry of the current version at the top"
    assert as_pep == sorted(as_pep, key=version_key, reverse=True), "CHANGELOG.md: versions newest first"
    notes = {p.stem for p in (config.CODE / "docs" / "upgrade").glob("*.md") if p.stem != "README"}
    missing = [v for v in as_pep if v not in notes and v != "2.0.0a1"]
    assert not missing, f"docs/upgrade/<version>.md missing for {missing}"
    changes = (config.CODE / "docs" / "dev" / "CHANGES.md").read_text()
    assert f"## {seen[0]} " in changes, "docs/dev/CHANGES.md: add the entry of the current version"
