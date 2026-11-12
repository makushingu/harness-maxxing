"""Extension pages: the pinned ones sit in the sidebar's Extensions folder, every one stays reachable (web sources,
no browser)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web" / "src"


def test_every_extension_page_can_be_reached():
    # the folder lists only the pinned pages: Settings -> Pages opens every one, and the search finds them
    pages = (WEB / "pages" / "settings" / "sections" / "Extensions.tsx").read_text()
    assert "to={`/x/${x.id}`}" in pages, "Settings -> Pages has no Open page link"
    palette = (WEB / "components" / "shell" / "CommandPalette.tsx").read_text()
    assert re.search(r"id: 'nav:x'.*?navigate\('/settings/pages'\)", palette), "Ctrl K has no Extensions entry"
    # the old Extensions page goes to Settings -> Pages
    assert re.search(r"path: 'x', element: <Navigate to=\"/settings/pages\"", (WEB / "routes.tsx").read_text())
    assert not (WEB / "pages" / "ext" / "hub.tsx").exists()


def test_the_pinned_pages_are_in_the_extensions_folder():
    nav = (WEB / "components" / "shell" / "nav.ts").read_text()
    assert re.search(r"usePinnedPages\(\).*?e\.pinned", nav, re.S)
    src = (WEB / "components" / "shell" / "Sidebar.tsx").read_text()
    assert "pins.length > 0 && <ExtFolder" in src, "Sidebar.tsx has no Extensions folder"
    assert "setExtFolderOpen" in src and "orderPins.mutate" in src
    # the pages' drag order no longer mixes the extension pages in
    assert "sidebar_order: order" in src and "/x/" not in src.split("function ExtFolder")[0]
    # the touch drawer's menu is the same sidebar (the folder comes with it)
    assert "<Sidebar drawer" in (WEB / "components" / "shell" / "TouchNav.tsx").read_text()


def test_the_docs_say_where_the_extension_pages_are():
    doc = (ROOT / "docs" / "user" / "13-page-extensions.md").read_text()
    assert "**Extensions** folder" in doc
    assert "**All pages**" not in doc and "(`/x`)" not in doc
