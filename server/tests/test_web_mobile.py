"""Phone layout rules that live in the web sources (no browser here): typing in a session on a touch screen."""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web" / "src"
# only the session being typed in; :focus-within of the whole box, not :focus of the text: a tap on Send moves the
# focus to the button first, the box grew back and the button moved away from under the finger (tap lost)
TYPING = r"html\[data-kbd\] \[data-col\]:has\(\[data-kbd-box\]:focus-within\)"


def _rule(css: str, marker: str) -> str:
    """Declarations of the rule `<typing> [<marker>]` (whitespace and order of the file do not matter)."""
    m = re.search(TYPING + r"\s+\[" + marker + r"\]\s*\{([^}]*)\}", css)
    assert m, f"no typing rule for [{marker}] in globals.css"
    return m[1]


def test_typing_in_a_session_keeps_the_answer_in_sight():
    # the composer autosizes up to 12 rows: with the keyboard up (Android resizes the page) it covered the thread,
    # and held sideways its send button went below the keyboard
    css = (WEB / "styles" / "globals.css").read_text()
    m = re.search(r"html\[data-kbd\]\s+\[data-kbd-box\]:focus-within\s+\[data-kbd-cap\]\s*\{([^}]*)\}", css)
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
    assert "data-kbd-cap" in composer and "data-kbd-box" in composer
    assert ":focus)" not in (WEB / "styles" / "globals.css").read_text()   # no rule left on the text's own focus
    assert "data-kbd-hide" in column and "data-kbd-short-hide" in column
    others = [p for p in WEB.rglob("*.tsx") if p.name not in ("Composer.tsx", "Column.tsx")]
    assert not [p.name for p in others if "data-kbd-" in p.read_text()]  # nothing else steps aside while typing


def test_the_tasks_header_leaves_room_for_the_menu_button():
    # on a 393-412 px phone the view switch in the header pushed the Menu button (the phone's navigation) off screen
    tasks = (WEB / "pages" / "tasks" / "index.tsx").read_text()
    out = re.search(r"max-\[(\d+)px\]:hidden\">\{viewSwitch\}", tasks)
    back = re.search(r"min-\[(\d+)px\]:hidden\">\{viewSwitch\}", tasks)
    assert out and back and int(out[1]) + 1 == int(back[1])  # in the header or below it, never both nor neither
    assert int(back[1]) >= 480


def test_show_more_is_big_enough_to_tap():
    # "Show more" in the notifications was a 50x16 px target on a phone: a bigger tap area on touch screens only
    feed = (WEB / "features" / "feed" / "FeedItems.tsx").read_text()
    more = re.search(r'<button[^>]*onClick=\{\(\) => setMore\(!more\)\}[^>]*className="([^"]*)"', feed)
    assert more and "pointer-coarse:before:absolute" in more[1] and "relative" in more[1].split()
