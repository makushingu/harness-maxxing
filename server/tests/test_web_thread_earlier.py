"""Show earlier reveals older rows by slices, never a whole page in one render (source checks, like test_web_mobile.py)."""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


def _thread() -> str:
    return (WEB / "pages" / "sessions" / "Thread.tsx").read_text()


def test_show_earlier_on_loaded_rows_grows_by_slices():
    src = _thread()
    fn = src[src.index("const loadEarlier = React.useCallback") :]
    fn = fn[: fn.index("}, [from, moreOnServer")]
    # the whole page (PAGE rows) is the target of the progressive render, only STEP rows are shown at once
    assert "setStart(Math.max(0, from - PAGE))" not in fn
    assert "growTo.current = target" in fn and "Math.max(0, from - PAGE)" in fn
    assert "setStart(Math.max(target, from - STEP))" in fn
    assert "prevHeight.current = el.scrollHeight" in fn          # the reading position is still kept


def test_a_page_from_the_server_grows_by_slices_too():
    src = _thread()
    block = src[src.index("if (headKey !== lastHead.current) {") :]
    block = block[: block.index("\n  }\n")]
    # rows prepended by the server: all but the last STEP of them hidden, then revealed by the progressive render
    assert "items.findIndex((it) => it.key === lastHead.current)" in block
    assert re.search(r"added > STEP\)\s*\{\s*growTo\.current = Math\.min\(growTo\.current \?\? start, start\)\s*setStart\(start \+ added - STEP\)", block)
    # the progressive render reveals STEP rows per idle moment down to growTo, keeping the position
    grow = src[src.index("const grow = () => {") :]
    assert "prevHeight.current = s.scrollHeight" in grow[:400] and "cur - STEP" in grow[:400]
