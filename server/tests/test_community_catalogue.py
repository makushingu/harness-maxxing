"""Settings -> Community: the catalogue of the website, a listing checked and installed at its reviewed commit."""
import io
import json
import zipfile

import pytest

from maxxing import community, extensions

SHA = "a" * 40
MANIFEST = json.dumps({"id": "demo", "name": "Demo", "version": "1.0", "type": "page", "api": 1})


def _site(monkeypatch, files, items=None, path=""):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(f"repo-{SHA}/{name}", text)
    items = items if items is not None else [
        {"slug": "demo-page", "type": "page", "title": "Demo", "description": "d", "repo": "someone/repo", "path": path,
         "sha": SHA, "server_code": False, "stars": 3, "author": {"login": "someone"}, "banner": "/community/img/1/a.webp"}]
    asked = []

    def get(url, cap):
        asked.append(url)
        return json.dumps({"ok": True, "items": items}).encode() if url.endswith("/api/items") else buf.getvalue()
    monkeypatch.setattr(community, "_get", get)
    community._cache.update(at=0.0, items=[])
    return asked


def test_the_catalogue_keeps_only_listings_it_can_download(mx, monkeypatch):
    bad = [{"slug": "x", "type": "page", "repo": "a/b", "sha": "main"},
           {"slug": "y", "type": "page", "repo": "a/b", "sha": SHA, "path": "../up"},
           {"slug": "z", "type": "robot", "repo": "a/b", "sha": SHA}, "junk",
           {"slug": "ok", "type": "theme", "repo": "a/b", "sha": SHA, "banner": "https://evil.example/x.png"}]
    asked = _site(monkeypatch, {}, bad)
    items = community.catalogue()
    assert [(i["slug"], i["tab"], i["banner"]) for i in items] == [("ok", "theme", "")]
    community.catalogue()
    assert len(asked) == 1                                    # kept a minute
    community.catalogue(fresh=True)
    assert len(asked) == 2


def test_a_listing_is_checked_then_installed_at_its_reviewed_commit(mx, monkeypatch):
    asked = _site(monkeypatch, {"ext/manifest.json": MANIFEST, "ext/page.js": "export default {}\n", "README.md": "x"},
                  path="ext")
    r = community.check_listing("demo-page")
    assert (r["kind"], r["id"], r["listing"]["tab"]) == ("extension", "demo", "extension")
    assert asked[-1] == f"https://codeload.github.com/someone/repo/zip/{SHA}"
    assert not (extensions.root() / "demo").exists()          # a check installs nothing
    with pytest.raises(community.PackageChanged):
        community.install_listing("demo-page", "0" * 64)
    done = community.install_listing("demo-page", r["sha256"])
    assert (extensions.root() / "demo" / "page.js").is_file()
    assert done["record"]["source"] == f"https://harness-maxxing.com/community/demo-page @ {SHA[:12]}"
    with pytest.raises(community.PackageError, match="not in the catalogue"):
        community.check_listing("gone")


def test_the_api_shows_the_catalogue_and_installs_only_what_was_checked(client, monkeypatch):
    _site(monkeypatch, {"manifest.json": MANIFEST, "page.js": "export default {}\n"})
    assert client.get("/api/community/catalogue").json()["items"][0]["slug"] == "demo-page"
    r = client.post("/api/community/catalogue/demo-page/check").json()
    assert client.post("/api/community/catalogue/demo-page/install", json={"sha256": "0" * 64}).status_code == 409
    ok = client.post("/api/community/catalogue/demo-page/install", json={"sha256": r["sha256"]})
    assert ok.status_code == 200 and ok.json()["id"] == "demo"
    assert client.post("/api/community/catalogue/nope/check").status_code == 400


@pytest.mark.parametrize("stars, shown", [("²", 0), ("9" * 5000, 0), (True, 0), (-4, 0), ("12", 12), (7, 7), (None, 0)])
def test_an_odd_star_count_never_takes_the_catalogue_down(mx, monkeypatch, stars, shown):
    _site(monkeypatch, {}, [{"slug": "ok", "type": "theme", "repo": "a/b", "sha": SHA, "stars": stars}])
    assert [i["stars"] for i in community.catalogue(fresh=True)] == [shown]
