"""The Extensions page (/x) lists every page extension: something in the app must lead to it (web sources, no browser)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web" / "src"


def test_the_extensions_page_can_be_reached():
    # the sidebar lists only the pinned pages: without another way in, an unpinned page cannot be opened from the app
    palette = (WEB / "components" / "shell" / "CommandPalette.tsx").read_text()
    assert re.search(r"navigate\('/x'\)", palette), "Ctrl K has no Extensions entry"
    pages = (WEB / "pages" / "settings" / "sections" / "Extensions.tsx").read_text()
    assert re.search(r"kind === 'pages'.*?navigate\('/x'\)", pages, re.S), "Settings -> Pages has no All pages link"


def test_the_docs_say_where_the_extensions_page_is():
    doc = (ROOT / "docs" / "user" / "13-page-extensions.md").read_text()
    assert "listed under **Extensions** in the sidebar" not in doc  # there is no such sidebar entry any more
    assert "**All pages**" in doc


def test_the_nav_shows_extensions_while_a_page_is_not_pinned():
    nav = (WEB / "components" / "shell" / "nav.ts").read_text()
    assert re.search(r"useUnpinnedPages\(\).*?!e\.pinned", nav, re.S)
    src = (WEB / "components" / "shell" / "Sidebar.tsx").read_text()
    assert "unpinned > 0 &&" in src and 'to="/x"' in src, "Sidebar.tsx has no Extensions entry for unpinned pages"
    # the touch drawer's menu is the same sidebar (the entry comes with it)
    assert "<Sidebar drawer" in (WEB / "components" / "shell" / "TouchNav.tsx").read_text()
