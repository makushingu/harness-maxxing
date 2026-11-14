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


def test_a_tap_in_a_context_menu_opened_by_a_long_press_reaches_its_item():
    # the menu is portaled but React touch events still bubble to the row: the row's long press saw the touchend of
    # the tap on an item and called preventDefault, so no click and the item never ran
    menu = (WEB / "components" / "ui" / "context-menu.tsx").read_text()
    for ev in ("onTouchStart", "onTouchMove", "onTouchEnd", "onTouchCancel"):
        assert f"{ev}={{stop}}" in menu, ev


def test_the_eye_of_a_multiline_secret_is_big_enough_to_tap():
    # a key pasted on several lines turns the field into a textarea: its show/hide button kept h-9 (44x36 px) on touch
    src = (WEB / "components" / "ui" / "secret-input.tsx").read_text()
    multi = re.search(r"multi \? '([^']*)'", src)
    assert multi and "pointer-coarse:h-11" in multi[1].split()


def test_retry_of_a_part_that_failed_is_big_enough_to_tap():
    # the inline "This part could not be shown" line offered Retry in a 43x20 px button on phones and tablets
    src = (WEB / "components" / "ui" / "error-boundary.tsx").read_text()
    inline = src[src.index('data-testid="part-error"'):]
    button = re.search(r'<button[^>]*className="([^"]*)"', inline)
    assert button and "pointer-coarse:min-h-10" in button[1].split()


def test_a_sheet_that_refuses_to_close_springs_back_after_a_swipe():
    # a dialog busy saving ignores the close: the sheet stayed where the finger left it, nearly off the screen
    src = (WEB / "components" / "ui" / "sheet-drag.ts").read_text()
    after = src[src.index("dismiss.current()"):]
    after = after[:after.index("} else set(0, true)")]
    assert "setTimeout" in after and "data-state" in after and "set(0, true)" in after


def test_search_in_the_touch_drawer_opens_the_search():
    # the drawer's "Search…" called openPalette directly: the drawer closed on the tap and the palette never showed
    src = (WEB / "components" / "shell" / "Sidebar.tsx").read_text()
    assert src.count("onClick={drawer ? searchNow : openPalette}") == 2



def test_the_effort_levels_are_big_enough_to_tap():
    # max-md: missed tablets: the effort buttons of the model menu were 36 px high at 820 px on touch
    src = (WEB / "pages" / "sessions" / "Widgets.tsx").read_text()
    row = src[src.index("function EffortRow"):]
    cls = re.search(r"'(h-7 [^']*)'", row)
    assert cls and "pointer-coarse:h-10" in cls[1].split()


def test_the_side_question_buttons_are_big_enough_to_tap():
    # Copy and Close of the side question panel were 28x28 px on phones and tablets
    src = (WEB / "pages" / "sessions" / "Aside.tsx").read_text()
    for label in ("t('common.copy')", "t('aside.close')"):
        part = src[src.index(f"aria-label={{{label}}}"):]
        cls = re.search(r'className="([^"]*)"', part)
        assert cls and "pointer-coarse:size-10" in cls[1].split(), label


def test_a_pull_request_on_a_phone_never_scrolls_sideways():
    # a long branch (dependabot/…) or check name widened the pane: the GitHub link of the check went off the screen
    src = (WEB / "features" / "code" / "PrPane.tsx").read_text()
    head = src[src.index("<GitBranch"):]
    assert re.match(r'<GitBranch[^>]*/><span className="min-w-0 truncate"><Sensitive>\{`\$\{pr\.head\}', head)
    checks = src[src.index("function Checks"):]
    assert '<span className="min-w-0 truncate"><Sensitive>{c.name}</Sensitive></span>' in checks
    link = re.search(r'<a href=\{c\.url\}[^>]*className="([^"]*)"', checks)
    assert link and "shrink-0" in link[1].split()


def test_a_file_and_the_link_of_a_check_are_big_enough_to_tap():
    src = (WEB / "features" / "code" / "PrPane.tsx").read_text()
    row = re.search(r'onClick=\{\(\) => onFile\(f\)\} className="([^"]*)"', src)
    assert row and "pointer-coarse:min-h-10" in row[1].split()
    link = re.search(r'<a href=\{c\.url\}[^>]*className="([^"]*)"', src)
    assert link and "pointer-coarse:size-10" in link[1].split()
