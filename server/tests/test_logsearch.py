"""Search in the journal: a period, a minimum level, a text, the units of one session (logsearch.py)."""
from __future__ import annotations

import json

import pytest

from maxxing import logsearch
from maxxing.sessions import store


def _j(msg, unit="claude-maxxing.service", prio="6", at=1_700_000_000):
    return json.dumps({"MESSAGE": msg, "_SYSTEMD_UNIT": unit, "PRIORITY": prio, "__REALTIME_TIMESTAMP": str(at * 1_000_000)})


JOURNAL = "\n".join([
    _j("INFO maxxing.app: started"),
    _j("WARNING maxxing.cron: job c_1 is late"),
    _j("ERROR maxxing.sessions: turn failed for 12345678"),
    _j("Traceback (most recent call last):"),
    _j('  File "x.py", line 1, in f'),
    _j("ValueError: boom"),
    _j("INFO:     127.0.0.1 - GET /api/health 200"),
    _j("plain line of a turn", unit="maxxing-12345678.service"),
    _j("the kernel killed it", unit="maxxing-12345678.service", prio="3"),
    _j([104, 105, 255], unit="maxxing-12345678.service"),
    "not json",
])


@pytest.fixture
def journal(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(logsearch, "_run", lambda args: calls.append(args) or JOURNAL)
    return calls


def test_levels_and_tracebacks(journal):
    rows = logsearch.search(["claude-maxxing"])["rows"]
    assert [r["level"] for r in rows] == ["info", "warning", "error", "error", "error", "error", "info", "info", "error", "info"]
    assert rows[0]["unit"] == "claude-maxxing" and rows[-1]["text"].startswith("hi")
    r = logsearch.search(["claude-maxxing"], level="error")
    assert r["matched"] == 5 and r["scanned"] == 10 and not r["truncated"]
    assert "ValueError: boom" in r["lines"][3] and r["lines"][3].startswith("2023-11-")
    assert logsearch.search(["claude-maxxing"], level="warning")["matched"] == 6


def test_text_period_and_limit(journal):
    assert logsearch.search(["claude-maxxing"], q="BOOM")["matched"] == 1
    assert len(logsearch.search(["claude-maxxing"], lines=2)["lines"]) == 2
    logsearch.search(["a", "b"], since="1h")
    args = journal[-1]
    assert args[:5] == ["-o", "json", "--no-pager", "-n", str(logsearch.SCAN_MAX)]
    assert args[5:9] == ["-u", "a", "-u", "b"] and args[9] == "--since" and args[10].startswith("@")
    for bad in ({"level": "loud"}, {"since": "1 hour ago; reboot"}):
        with pytest.raises(ValueError):
            logsearch.search(["claude-maxxing"], **bad)


def test_secrets_are_masked_again(monkeypatch):
    monkeypatch.setattr(logsearch, "_run", lambda args: _j("token ghp_" + "a" * 36, unit="maxxing-12345678.service"))
    assert "ghp_<redacted>" in logsearch.search(["x"])["lines"][0]


def test_api_search_and_session(client, journal):
    r = client.get("/api/system/logs?level=error&q=boom").json()
    assert r["matched"] == 1 and r["lines"][0].endswith("ValueError: boom") and r["scanned"] == 10
    m = store.new_meta("", "S")
    m["id"] = "12345678" + m["id"][8:]
    store.create(m)
    r = client.get(f"/api/system/logs?session={m['id']}").json()
    # the turn unit's lines + the server's lines that name the session
    assert [ln.split(": ", 1)[1] for ln in r["lines"]] == ["ERROR maxxing.sessions: turn failed for 12345678",
                                                         "plain line of a turn", "the kernel killed it", "hi�"]
    assert journal[-1][5:9] == ["-u", "claude-maxxing", "-u", "maxxing-12345678"]
    assert client.get("/api/system/logs?session=00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get("/api/system/logs?session=a;b").status_code == 404
    assert client.get("/api/system/logs?level=loud").json()["error"] == "bad_level"
    assert client.get("/api/system/logs?since=1y").json()["error"] == "bad_since"
    assert client.get("/api/system/logs?unit=ssh&q=x").status_code == 400


def test_entries_of_several_lines_are_not_taken_for_a_cut_journal(monkeypatch):
    """SCAN_MAX counts journal entries: 5,000 tracebacks of 5 lines are 5,000 entries read, nothing cut."""
    tb = "ERROR maxxing.x: failed\nTraceback (most recent call last):\n  File \"x.py\", line 1\n    f()\nValueError: boom"
    monkeypatch.setattr(logsearch, "_run", lambda args: "\n".join([_j(tb)] * 5000))
    r = logsearch.search(["claude-maxxing"], level="error")
    assert r["scanned"] == 5000 and not r["truncated"] and r["matched"] == 25000
    monkeypatch.setattr(logsearch, "_run", lambda args: "\n".join([_j("one")] * logsearch.SCAN_MAX))
    assert logsearch.search(["claude-maxxing"])["truncated"]
