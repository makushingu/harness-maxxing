"""Labels read by screen readers come from the translations, like the visible texts (no English left in the markup)."""
from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


def test_the_close_button_of_dialogs_and_sheets_is_translated():
    for name in ("dialog.tsx", "sheet.tsx"):
        src = (WEB / "components" / "ui" / name).read_text(encoding="utf-8")
        assert '<span className="sr-only">Close</span>' not in src, name
        assert "<span className=\"sr-only\">{t('common.close')}</span>" in src, name


def test_the_resize_handles_of_session_columns_are_translated():
    src = (WEB / "pages" / "sessions" / "Column.tsx").read_text(encoding="utf-8")
    assert 'aria-label="Resize"' not in src
    assert "aria-label={t('shell.resize')}" in src and "aria-label={t('shell.resizeRows')}" in src


def test_the_presentation_mode_masks_are_translated():
    left = [str(p.relative_to(WEB)) for p in WEB.rglob("*.tsx") if "Hidden (presentation mode)" in p.read_text(encoding="utf-8")]
    assert not left, left
    assert "aria-label={t('presentation.hidden')}" in (WEB / "components" / "ui" / "sensitive.tsx").read_text(encoding="utf-8")
