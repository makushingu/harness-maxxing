"""Addresses written by Claude in an answer: the patterns of the interface that decide what loads or becomes a link."""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


def _js_regex(path: Path, prefix: str) -> re.Pattern[str]:
    """The regex literal that follows `prefix` in a source file (the patterns used are valid Python ones too)."""
    src = path.read_text(encoding="utf-8")
    m = re.search(re.escape(prefix) + r"/((?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\\\n\[])+)/([a-z]*)", src)
    assert m, prefix
    return re.compile(m.group(1), re.I if "i" in m.group(2) else 0)


def test_a_markdown_address_that_the_browser_reads_as_another_host_is_external():
    external = _js_regex(WEB / "components" / "ui" / "markdown.tsx", "const EXTERNAL = ")
    # `/\host` and `\\host` are read by browsers as `//host`: an image there would load without a click
    for src in ("https://evil.com/a.png", "//evil.com/a.png", "/\\evil.com/a.png", "\\\\evil.com/a.png",
                "\\/evil.com/a.png", "/\t/evil.com/a.png", "HTTPS://evil.com/a.png"):
        assert external.match(src), src
    for src in ("/api/files/raw?path=a.png", "/sessions", "./a.png", "../a.png", "#top"):
        assert not external.match(src), src

