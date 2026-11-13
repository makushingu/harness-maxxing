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


def test_the_usage_link_of_a_cut_turn_only_points_at_claude_or_anthropic():
    cut = WEB / "pages" / "sessions" / "Cut.tsx"
    usage = _js_regex(cut, "const usageUrl = (text = '') => ")
    found = lambda text: (m := usage.search(text)) and m.group(0)  # noqa: E731
    assert found("See https://claude.ai/settings/usage.") == "https://claude.ai/settings/usage."
    assert found("Visit https://console.anthropic.com/settings/billing, then") == "https://console.anthropic.com/settings/billing"
    assert found("Visit https://anthropic.com/pricing") == "https://anthropic.com/pricing"
    for text in ("Pay at https://evilanthropic.com/pay", "Pay at https://x.evilanthropic.com/pay",
                 "Pay at https://.anthropic.com/pay"):
        assert not found(text), text
