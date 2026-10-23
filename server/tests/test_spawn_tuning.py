"""Runner launch parity: native Claude tuning survives transient systemd units."""
from types import SimpleNamespace

import pytest

from maxxing.sessions import spawn


TUNING = {
    "CLAUDE_CODE_EFFORT_LEVEL": "low",
    "MAX_THINKING_TOKENS": "4096",
    "CLAUDE_CODE_PROMPT_CACHE_TTL": "1h",
    "CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL": "5m",
    "FORCE_PROMPT_CACHING_5M": "1",
    "ENABLE_PROMPT_CACHING_1H": "1",
    "ENABLE_TOOL_SEARCH": "auto:5",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
}


def capture_unit(monkeypatch, env):
    calls = []
    monkeypatch.setattr(spawn, "_runner_env", lambda: dict(env))

    def run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn.subprocess, "run", run)
    spawn._start_unit("12345678-1234-1234-1234-123456789012")
    assert len(calls) == 1
    cmd = calls[0]
    return {cmd[i + 1].split("=", 1)[0]: cmd[i + 1].split("=", 1)[1]
            for i, arg in enumerate(cmd[:-1]) if arg == "--setenv"}


@pytest.mark.parametrize("name,value", list(TUNING.items()))
def test_systemd_preserves_native_tuning(monkeypatch, name, value):
    assert capture_unit(monkeypatch, {name: value})[name] == value


def test_unset_tuning_does_not_change_claude_defaults(monkeypatch):
    assert capture_unit(monkeypatch, {}) == {}


def test_unit_arguments_do_not_forward_credentials_or_unrelated_env(monkeypatch):
    env = {**TUNING, "ANTHROPIC_API_KEY": "test-secret", "CLAUDE_CODE_OAUTH_TOKEN": "test-secret",
           "UNRELATED_SETTING": "private"}
    assert capture_unit(monkeypatch, env) == TUNING


def test_direct_and_systemd_preserve_the_same_tuning(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(spawn, "_runner_env", lambda: dict(TUNING))
    monkeypatch.setattr(spawn.config, "state_dir", lambda *parts: tmp_path)

    def popen(cmd, **kwargs):
        captured.append(kwargs["env"])
        return SimpleNamespace(pid=12345, wait=lambda: 0)

    monkeypatch.setattr(spawn.subprocess, "Popen", popen)
    assert spawn._start_direct("12345678-1234-1234-1234-123456789012") == "pid:12345"
    assert captured == [TUNING]
    assert capture_unit(monkeypatch, TUNING) == captured[0]


def test_bash_output_is_capped_unless_tuned(monkeypatch):
    monkeypatch.delenv("BASH_MAX_OUTPUT_LENGTH", raising=False)
    assert spawn.claude_env()["BASH_MAX_OUTPUT_LENGTH"] == str(spawn.BASH_OUTPUT_MAX)
    monkeypatch.setenv("BASH_MAX_OUTPUT_LENGTH", "30000")
    assert spawn.claude_env()["BASH_MAX_OUTPUT_LENGTH"] == "30000"
    assert spawn.claude_env({"BASH_MAX_OUTPUT_LENGTH": "5000"})["BASH_MAX_OUTPUT_LENGTH"] == "5000"


def test_unit_still_stopping_is_awaited_by_polling(monkeypatch):
    """The previous runner unit of the session is still exiting: poll until it is gone (no fixed sleeps),
    then start under the same name; a unit that never goes away gets a suffixed name."""
    monkeypatch.setattr(spawn, "_runner_env", lambda: {})
    monkeypatch.setattr(spawn, "UNIT_POLL_S", 0.001)
    states = iter(["active", "deactivating", "not-found"])
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "systemctl":
            st = next(states)
            out = "LoadState=not-found\nActiveState=inactive\n" if st == "not-found" else f"LoadState=loaded\nActiveState={st}\n"
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        ok = sum(1 for c in calls if c[0] == "systemd-run") > 1
        return SimpleNamespace(returncode=0 if ok else 1, stdout="",
                               stderr="" if ok else "Unit maxxing-12345678.service was already loaded")

    monkeypatch.setattr(spawn.subprocess, "run", run)
    sleeps = []
    monkeypatch.setattr(spawn.time, "sleep", lambda s: sleeps.append(s))
    assert spawn._start_unit("12345678-1234-1234-1234-123456789012") == "maxxing-12345678"
    assert [c[0] for c in calls] == ["systemd-run", "systemctl", "systemctl", "systemctl", "systemd-run"]
    assert sleeps and max(sleeps) <= 0.001

    calls.clear()
    monkeypatch.setattr(spawn, "UNIT_GONE_WAIT_S", 0.0)
    monkeypatch.setattr(spawn, "_wait_unit_gone", lambda unit, timeout=0.0: False)
    monkeypatch.setattr(spawn.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(
        returncode=0 if "maxxing-12345678" != cmd[cmd.index("--unit") + 1] else 1, stdout="", stderr="already exists"))
    unit = spawn._start_unit("12345678-1234-1234-1234-123456789012")
    assert unit.startswith("maxxing-12345678-") and len(calls) == 3


def test_compact_window_follows_the_session_threshold():
    m = spawn.COMPACT_WINDOW_MARGIN
    assert spawn.compact_window({"auto_compact_tokens": 0}) is None
    assert spawn.compact_window({"auto_compact_tokens": 400000}) == 400000 + m
    assert spawn.compact_window({"auto_compact_tokens": 50000}) == 100000 + m          # raised like the runner does
    assert spawn.compact_window({"auto_compact_tokens": 2000000}) == spawn.COMPACT_WINDOW_MAX


def test_user_tuning_wins_over_our_defaults(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "700000")
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "0")
    env = spawn.claude_env()
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "700000" and env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "0"


def unit_cmd(monkeypatch):
    calls = []
    monkeypatch.setattr(spawn, "_runner_env", lambda: {})
    monkeypatch.setattr(spawn.subprocess, "run", lambda cmd, **k: calls.append(cmd) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    spawn._start_unit("12345678-1234-1234-1234-123456789012")
    cmd = calls[0]
    return [cmd[i + 1] for i, a in enumerate(cmd[:-1]) if a == "--property"]


def test_unit_survives_a_command_out_of_memory(monkeypatch):
    """A runaway command (an ffmpeg render) is killed alone; the turn and the server go on."""
    from maxxing import config
    monkeypatch.setattr(config, "load_config", lambda: {"unit_memory_max": "75%"})
    props = unit_cmd(monkeypatch)
    assert "OOMPolicy=continue" in props and "MemoryMax=75%" in props and "KillMode=mixed" in props
    for cap, want in (("4G", "MemoryMax=4G"), ("", None), ("infinity", None), ("75%; rm -rf /", None)):
        monkeypatch.setattr(config, "load_config", lambda cap=cap: {"unit_memory_max": cap})
        props = spawn.memory_properties()
        assert props[:2] == ["--property", "OOMPolicy=continue"]
        assert (props[3] if len(props) > 2 else None) == want


def test_default_memory_cap():
    from maxxing import config
    assert config.DEFAULT_CONFIG["unit_memory_max"] == "75%"


def test_turns_ask_for_foreground_agents_unless_background_agents_is_on():
    args = spawn.agents_args({})
    assert args[0] == "--append-system-prompt" and "run_in_background: false" in args[1]
    assert spawn.agents_args({"background_agents": False}) == args
    assert spawn.agents_args({"background_agents": True}) == []
