"""Usage history of Settings -> System: one sample every 5 min, the last 24 h as they are, older ones by half hour,
7 days kept, a small compact file."""
from __future__ import annotations

import json

import pytest

from maxxing import health

T0 = 1_800_000_000.0 - 1_800_000_000.0 % 1800  # a fixed clock, on a half hour


@pytest.fixture
def sample(monkeypatch):
    """collect() as the health card would give it; each test can change the values."""
    values = {"cpu_pct": 12.0, "mem": {"total": 4_000, "avail": 1_000}, "disk": {"total": 100, "free": 40, "pct": 60.0},
              "load": [0.5, 0.4, 0.3]}
    monkeypatch.setattr(health, "collect", lambda force=False: dict(values))
    monkeypatch.setattr(health, "_history_last", None)
    return values


def _rows() -> list:
    return json.loads(health.history_path().read_text())["points"]


def test_one_sample_every_five_minutes(mx, sample):
    assert health.record_history(T0)
    assert not health.record_history(T0 + 30)  # the next alerts pass: too soon
    assert health.record_history(T0 + 300)
    assert _rows() == [[T0, 12.0, 75.0, 60.0, 0.5], [T0 + 300, 12.0, 75.0, 60.0, 0.5]]
    assert health.history("24h", T0 + 300)["points"][0] == {"t": T0, "cpu": 12.0, "mem": 75.0, "disk": 60.0, "load": 0.5}


def test_the_week_is_averaged_by_half_hour_with_its_peak(mx, sample):
    for i, cpu in enumerate([10.0, 30.0, 80.0, 20.0, 10.0, 50.0]):  # 6 samples 5 min apart: one half-hour bucket
        sample["cpu_pct"] = cpu
        health.record_history(T0 + i * 300)
    day = health.history("24h", T0 + 1800)
    assert day["step"] == 300 and len(day["points"]) == 6
    week = health.history("7d", T0 + 1800)
    assert week["step"] == 1800 and len(week["points"]) == 1
    assert (week["points"][0]["cpu"], week["points"][0]["cpu_max"]) == (33.3, 80.0)


def test_samples_older_than_a_day_are_folded_by_half_hour(mx, sample):
    for i, cpu in enumerate([10.0, 30.0, 80.0, 20.0, 10.0, 50.0]):
        sample["cpu_pct"] = cpu
        health.record_history(T0 + i * 300)
    health.record_history(T0 + 86400 + 1800)                 # a day later: the first half hour is folded
    rows = _rows()
    assert rows[0] == [T0, 33.3, 75.0, 60.0, 0.5, 80.0, 6] and len(rows) == 2
    week = health.history("7d", T0 + 86400 + 1800)["points"]
    assert (week[0]["cpu"], week[0]["cpu_max"]) == (33.3, 80.0)     # the same as before folding
    assert health.history("24h", T0 + 86400 + 1800)["points"][0]["t"] == T0 + 86400 + 1800


def test_a_week_of_samples_stays_small(mx, sample):
    for i in range(7 * 288):
        health.record_history(T0 + i * 300)
    rows = _rows()
    assert len(rows) <= 288 + 6 + 6 * 48                      # a day (+ the open half hour) of samples + six days of half hours
    assert health.history_path().stat().st_size < 40_000      # rewritten every 5 min: compact
    health.record_history(T0 + 8 * 86400)
    assert _rows()[0][0] >= T0 + 86400                         # older than 7 days: gone


def test_a_clock_set_back_keeps_the_history(mx, sample):
    for i in range(3):
        health.record_history(T0 + i * 300)
    assert health.record_history(T0 - 3600)                    # NTP moved the clock back an hour: sampled at once
    assert [r[0] for r in _rows()] == [T0 - 3600, T0, T0 + 300, T0 + 600]


def test_a_damaged_history_starts_again(mx, sample):
    health.history_path().write_text("{not json")
    assert health.history("24h", T0)["points"] == []
    assert health.record_history(T0)
    assert len(health.history("24h", T0)["points"]) == 1


def test_the_route(client, sample):
    health.record_history()
    r = client.get("/api/system/health/history?range=7d")
    assert r.status_code == 200 and r.json()["range"] == "7d" and r.json()["step"] == 1800
    assert client.get("/api/system/health/history?range=1y").status_code == 400
