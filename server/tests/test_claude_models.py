"""claude_models: newest model of each family read from Anthropic, default model follows its family."""
from __future__ import annotations

from maxxing import claude_models, config
from maxxing.sessions import service

T = 2_000_000_000.0
IDS = ["claude-opus-5-5", "claude-opus-5", "claude-opus-4-8", "claude-sonnet-6", "claude-sonnet-5-5",
       "claude-haiku-5-5", "claude-haiku-4-5-20251001", "claude-fable-5-2", "claude-fable-5-1", "not-a-model"]


def test_newest_per_family():
    assert claude_models.newest(IDS) == ["claude-opus-5-5", "claude-sonnet-6", "claude-haiku-5-5", "claude-fable-5-2"]
    assert claude_models.version_key("claude-haiku-4-5-20251001") == (4, 5, 0)


def test_refresh_lists_and_moves_the_default(mx, monkeypatch):
    assert claude_models.latest() == claude_models.FALLBACK
    config.update_config(default_model="claude-sonnet-5-5")
    monkeypatch.setattr(claude_models, "fetch_ids", lambda: IDS)
    d = claude_models.refresh(now=T)
    assert d["latest"] == ["claude-opus-5-5", "claude-sonnet-6", "claude-haiku-5-5", "claude-fable-5-2"]
    assert d["default_moved_to"] == "claude-sonnet-6"
    assert config.load_config()["default_model"] == "claude-sonnet-6"
    ids = [m["id"] for m in service.models()]
    assert "claude-sonnet-6" in ids and "claude-fable-5-2" in ids
    assert claude_models.refresh(now=T + 60)["checked_at"] == T         # not due yet


def test_a_default_picked_on_purpose_stays(mx, monkeypatch):
    config.update_config(default_model="claude-opus-4-8")
    monkeypatch.setattr(claude_models, "fetch_ids", lambda: IDS)
    claude_models.refresh(now=T)
    assert config.load_config()["default_model"] == "claude-opus-4-8"


def test_failure_keeps_the_last_list(mx, monkeypatch):
    monkeypatch.setattr(claude_models, "fetch_ids", lambda: IDS)
    claude_models.refresh(now=T)

    def boom():
        raise RuntimeError("HTTP 401")
    monkeypatch.setattr(claude_models, "fetch_ids", boom)
    d = claude_models.refresh(now=T + claude_models.CHECK_EVERY_S)
    assert d["error"] == "HTTP 401" and claude_models.latest_of("sonnet") == "claude-sonnet-6"


def test_no_credentials_no_call(mx, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert claude_models.refresh(force=True)["error"] == "no Claude credentials"


class _Answer:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


def test_an_answer_whose_data_is_not_a_list_is_noted_not_raised(mx, monkeypatch):
    import httpx
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    for body in ({"data": 5}, {"data": "claude-opus-9"}):
        monkeypatch.setattr(httpx, "get", lambda *a, **k: _Answer(body))
        assert claude_models.refresh(force=True)["error"] == "bad answer"


def test_a_variant_suffix_is_not_a_newer_model(mx, monkeypatch):
    assert claude_models.newest(["claude-opus-6-preview", "claude-opus-5-5", "claude-opus-5-5-fast"]) == ["claude-opus-5-5"]
    assert claude_models.newest(["claude-haiku-5-5-20260101", "claude-haiku-5-5"]) == ["claude-haiku-5-5"]
    config.update_config(default_model="claude-opus-5-5")
    monkeypatch.setattr(claude_models, "fetch_ids", lambda: ["claude-opus-6-preview", "claude-opus-5-5"])
    assert claude_models.refresh(force=True).get("default_moved_to") is None
    assert config.load_config()["default_model"] == "claude-opus-5-5"
