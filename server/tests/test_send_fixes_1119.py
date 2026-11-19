"""Small fixes sent together (Radar, 19 Nov): feed group, Stripe id, packs link, trash names, emoji, import names, tidy."""
from __future__ import annotations

import json
import os

import pytest

from maxxing import agents, feed, feedhooks, importer, packs, trash, workspace


def test_the_feed_group_is_capped_and_a_falsy_dedupe_is_none(client, mx):
    ev = feed.post("t", group="x" * 10**6, dedupe=0)
    assert ev is not None
    with feed._conn() as c:
        assert c.execute("SELECT MAX(LENGTH(grp)) FROM events").fetchone()[0] <= 200


def test_a_stripe_event_with_a_falsy_or_odd_id_never_raises(client, mx):
    for eid in (0, "", [], {}):
        for n in range(2):
            ev = feedhooks._stripe({"type": "charge.refunded", "id": eid, "n": n, "data": {"object": {}}}, {})
            assert ev is not None and ev[4] is None


def test_a_dangling_link_in_projects_gives_another_name(mx):
    ws = workspace.root()
    (ws / "projects").mkdir(parents=True, exist_ok=True)
    os.symlink(ws / "nowhere", ws / "projects" / "shop")
    assert packs._free_name(ws, "shop") == "shop-2"


def test_a_restored_folder_with_a_dot_keeps_its_name(mx, tmp_path):
    d = tmp_path / "v1.2"
    d.mkdir()
    assert trash._free(d).name == "v1.2 (restored)"
    f = tmp_path / "b.txt"
    f.write_text("x")
    assert trash._free(f).name == "b (restored).txt"


def test_a_dangling_link_counts_as_taken_when_restoring(mx, tmp_path):
    link = tmp_path / "gone"
    os.symlink(tmp_path / "nowhere", link)
    assert trash._free(link) != link
    os.symlink(tmp_path / "nowhere", tmp_path / "proj")
    assert trash._free_dir_name(tmp_path / "proj").name == "proj-restored"
