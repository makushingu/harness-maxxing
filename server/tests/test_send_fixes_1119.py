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
