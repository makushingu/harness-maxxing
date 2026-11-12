"""DESIGN.md rules checked on the web sources: no browser dialogs (§8), no backdrop blur (§11)."""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web" / "src"
FILES = sorted(p for p in SRC.rglob("*") if p.suffix in (".ts", ".tsx"))
# features/agents is developed separately upstream and is not covered yet
BLUR_EXEMPT = "features/agents/"


def _code(p: Path) -> str:
    s = p.read_text(encoding="utf-8")
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$|\s//\s.*$", "", s)


def test_no_browser_dialogs():
    bad = [str(p.relative_to(SRC)) for p in FILES if re.search(r"\b(?:window\.)?(?:confirm|alert|prompt)\(", _code(p)) and re.search(r"window\.(?:confirm|alert|prompt)\(", _code(p))]
    assert not bad, f"window.confirm/alert/prompt in {bad}: use confirm() of ui/alert-dialog or a toast"


def test_no_backdrop_blur():
    bad = [str(p.relative_to(SRC)) for p in FILES if BLUR_EXEMPT not in p.as_posix() and re.search(r"backdrop-(?:blur|filter)", _code(p))]
    assert not bad, f"backdrop blur in {bad}: use a near-opaque background"
