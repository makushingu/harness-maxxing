"""Phone layout rules that live in the web sources (no browser here): typing in a session on a touch screen."""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web" / "src"
TYPING = r"html\[data-kbd\] \[data-col\]:has\(\[data-kbd-cap\]:focus\)"  # only the session being typed in


def _rule(css: str, marker: str) -> str:
    """Declarations of the rule `<typing> [<marker>]` (whitespace and order of the file do not matter)."""
    m = re.search(TYPING + r"\s+\[" + marker + r"\]\s*\{([^}]*)\}", css)
    assert m, f"no typing rule for [{marker}] in globals.css"
    return m[1]


def test_typing_in_a_session_keeps_the_answer_in_sight():
    # the composer autosizes up to 12 rows: with the keyboard up (Android resizes the page) it covered the thread,
    # and held sideways its send button went below the keyboard
    css = (WEB / "styles" / "globals.css").read_text()
    m = re.search(r"html\[data-kbd\]\s+\[data-kbd-cap\]:focus\s*\{([^}]*)\}", css)
    assert m, "no cap on the focused composer in globals.css"
    cap = m[1]
    assert re.search(r"max-height:[^;]*var\(--vvh", cap)
    assert re.search(r"overflow-y:\s*auto\s*!important", cap)  # the autosize sets overflow-y inline: it must scroll
    assert re.search(r"display:\s*none", _rule(css, "data-kbd-hide"))
    short = re.search(r"@media\s*\(max-height:\s*480px\)\s*\{(.*?)\n\}", css, re.S)
    assert short and re.search(r"display:\s*none", _rule(short[1], "data-kbd-short-hide"))


def test_only_the_session_composer_and_its_headers_carry_the_typing_markers():
    composer = (WEB / "pages" / "sessions" / "Composer.tsx").read_text()
    column = (WEB / "pages" / "sessions" / "Column.tsx").read_text()
    assert "data-kbd-cap" in composer
    assert "data-kbd-hide" in column and "data-kbd-short-hide" in column
    others = [p for p in WEB.rglob("*.tsx") if p.name not in ("Composer.tsx", "Column.tsx")]
    assert not [p.name for p in others if "data-kbd-" in p.read_text()]  # nothing else steps aside while typing
