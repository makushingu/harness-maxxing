"""Infra hardening (round 4): platform readers and domains added by hand."""
from _conn_helpers import _Server
from _org_helpers import client, org  # noqa: F401
from maxxing import config, infra, vault
from maxxing.infra import probe


def test_vercel_pagination_stops_on_empty_pages(org, monkeypatch):
    """An empty page that still carries a `next` cursor (or the same cursor again) ends the listing - it used to
    loop forever, holding the refresh lock: the Infra page froze until a restart."""
    from maxxing.infra import platforms
    from maxxing.infra.providers import ProviderError
    calls = {"n": 0}

    def fake_get(self, path, params=None):
        calls["n"] += 1
        if calls["n"] > 200:
            raise ProviderError("stop", "test guard")
        if path.startswith("/v2/teams"):
            return {"teams": []}
        field = "projects" if "projects" in path else "domains"
        return {field: [], "pagination": {"next": 1760000000000}}
    monkeypatch.setattr(platforms._Client, "get", fake_get)
    vault.put("VERCEL_TOKEN", "v-tok")
    platforms.vercel()
    assert calls["n"] < 10, f"{calls['n']} calls to the Vercel API for two empty sections"


def test_vercel_token_never_in_the_stored_error(org, monkeypatch):
    from maxxing.infra import platforms
    s = _Server(lambda m, p, h, b: (200, {"teams": []}, "application/json"))
    monkeypatch.setenv("MAXXING_VERCEL_API", s.url)
    try:
        vault.put("VERCEL_TOKEN", "vcp_FIRSTLINE\nSECRET-TOKEN-1234")
        state = platforms.source_state(platforms.read_all())
    finally:
        s.close()
    assert "SECRET-TOKEN" not in str(state["vercel"])


def test_add_domain_bad_unicode_is_a_400(org, monkeypatch, client):  # noqa: F811
    monkeypatch.setattr(infra, "refresh_in_background", lambda: True)
    config.update_config(infra_page=True)
    for bad in ("é" * 64 + ".com", "é..com"):
        assert client.post("/api/infra/domains", json={"name": bad}).status_code == 400, bad


def test_repo_of_hides_a_password_holding_an_at_sign(tmp_path):
    git = tmp_path / "site" / ".git"
    git.mkdir(parents=True)
    (git / "config").write_text('[remote "origin"]\n\turl = https://bob:p4ss@word123@github.com/o/r.git\n')
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    repo = probe.repo_of(str(tmp_path / "site"))
    assert repo["remote"] == "https://github.com/o/r.git"
    assert repo["branch"] == "main"
