"""Labels read by screen readers come from the translations, like the visible texts (no English left in the markup)."""
from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


def test_the_close_button_of_dialogs_and_sheets_is_translated():
    for name in ("dialog.tsx", "sheet.tsx"):
        src = (WEB / "components" / "ui" / name).read_text(encoding="utf-8")
        assert '<span className="sr-only">Close</span>' not in src, name
        assert "<span className=\"sr-only\">{t('common.close')}</span>" in src, name
