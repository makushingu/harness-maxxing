"""The dictionary the first page needs stays small: the preload map of the built index.html (vite.config.ts,
routePreload) gives, per language, the core dictionary and the groups of each route (src/i18n/groups.ts)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
BUDGET = 20_000  # brotli bytes of dictionary on the first load of the dashboard or a session (was ~35 kB in one piece)


def _preload_map() -> dict:
    html = (DIST / "index.html").read_text(encoding="utf-8")
    m = re.search(r"var m=(\{.*?\}),p=location", html)
    assert m, "route preload script missing from web/dist/index.html"
    return json.loads(m.group(1))


def _br(href: str) -> int:
    f = DIST / href.lstrip("/")
    br = f.with_name(f.name + ".br")
    return (br if br.is_file() else f).stat().st_size


@pytest.mark.skipif(not (DIST / "index.html").is_file(), reason="web/dist not built")
@pytest.mark.parametrize("path", ["/", "/sessions"])
@pytest.mark.parametrize("lang", ["en", "fr"])
def test_first_load_dictionary_is_split(path, lang):
    m = _preload_map()
    groups = next((r[2] if len(r) > 2 else [] for r in m["r"] if re.search(r[0], path)), [])
    chunks = m["l"][lang]
    assert isinstance(chunks, dict) and "core" in chunks, f"{lang}: the dictionary is one chunk"
    files = [chunks["core"], *(chunks[g] for g in groups)]
    assert sum(_br(f) for f in files) <= BUDGET, files


@pytest.mark.skipif(not (DIST / "index.html").is_file(), reason="web/dist not built")
def test_every_route_group_has_a_chunk_in_every_language():
    m = _preload_map()
    for lang, chunks in m["l"].items():
        for r in m["r"]:
            for g in r[2] if len(r) > 2 else []:
                assert (DIST / chunks[g].lstrip("/")).is_file(), (lang, r[0], g)
