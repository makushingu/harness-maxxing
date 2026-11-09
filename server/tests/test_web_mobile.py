"""Phone layout rules that live in the web sources (no browser here): typing in a session on a touch screen."""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web" / "src"
TYPING = "html[data-kbd]:has([data-kbd-cap]:focus)"


def _block(css: str, selector: str) -> str:
    return css.split(selector + " {", 1)[1].split("}", 1)[0]


def test_typing_in_a_session_keeps_the_answer_in_sight():
    # the composer autosizes up to 12 rows: with the keyboard up (Android resizes the page) it covered the thread,
    # and held sideways its send button went below the keyboard
    css = (WEB / "styles" / "globals.css").read_text()
    cap = _block(css, f"{TYPING} [data-kbd-cap]")
    assert "max-height:" in cap and "var(--vvh" in cap
    assert "overflow-y: auto !important" in cap  # the autosize sets overflow-y inline: the capped text must scroll
    assert "display: none" in _block(css, f"{TYPING} [data-kbd-hide]")
    short = css.split("@media (max-height: 480px) {", 1)[1]
    assert "display: none" in _block(short, f"  {TYPING} [data-kbd-short-hide]")


def test_only_the_session_composer_and_its_headers_carry_the_typing_markers():
    composer = (WEB / "pages" / "sessions" / "Composer.tsx").read_text()
    assert len(re.findall(r'data-kbd-cap=""', composer)) == 1
    column = (WEB / "pages" / "sessions" / "Column.tsx").read_text()
    assert len(re.findall(r'data-kbd-hide=""', column)) == 2  # the place row of the column and of the phone header
    assert len(re.findall(r'data-kbd-short-hide=""', column)) == 2  # the column header and the phone header
    others = [p for p in WEB.rglob("*.tsx") if p.name not in ("Composer.tsx", "Column.tsx")]
    assert not [p for p in others if "data-kbd-" in p.read_text()]  # nothing else steps aside while typing
