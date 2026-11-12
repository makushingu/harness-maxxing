"""The Enterprises page lives in the web sources (no browser here): its lazy dictionary group, its sober look, its texts."""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web" / "src"
FILES = sorted((WEB / "features" / "enterprises").glob("*.ts*")) + [WEB / "lib" / "queries" / "enterprises.ts"]
KEY = re.compile(r"""['"](ent\.[A-Za-z0-9_.]+)['"]""")


def _keys(path: Path) -> set[str]:
    """Every quoted `ent.` key of a dictionary file (en.ts quotes with ', fr.ts with ")."""
    return {m.group(1) for m in re.finditer(r"""^\s+['"](ent\.[A-Za-z0-9_.#]+)['"]\s*:""", path.read_text(encoding="utf-8"), re.M)}


def test_the_enterprises_group_is_lazy_and_declared_on_its_route():
    groups = (WEB / "i18n" / "groups.ts").read_text(encoding="utf-8")
    assert re.search(r"enterprises:\s*\['ent'\]", groups)
    routes = (WEB / "routes.tsx").read_text(encoding="utf-8")
    m = re.search(r"path: 'enterprises/\*', lazy: page\(\(\) => import\('\./features/enterprises/EnterprisesLayout'\), \[([^\]]*)\]\)", routes)
    assert m, "the enterprises route is missing from routes.tsx"
    assert "'enterprises'" in m[1]
    # the shell's own words (sidebar, features list) are not in the lazy namespace
    assert "'nav.enterprises'" in (WEB / "components" / "shell" / "nav.ts").read_text(encoding="utf-8")
    assert re.search(r"""['\"]nav.enterprises['\"]""", (WEB / "i18n" / "en.ts").read_text(encoding="utf-8"))


def test_the_page_shows_only_while_the_feature_and_agents_are_on():
    nav = (WEB / "components" / "shell" / "nav.ts").read_text(encoding="utf-8")
    assert "setting: 'enterprises_page'" in nav and "'enterprises_page'" in nav.split("type FeatureSetting")[1].split("\n")[0]
    assert "s.agents_page" in nav
    feature = (WEB / "features" / "settings" / "FeaturePages.tsx").read_text(encoding="utf-8")
    assert "enterprises_page: 'features.page.enterprises'" in feature and "features.need.enterprises" in feature


def test_no_hard_coded_color_nor_gradient_in_the_enterprises_files():
    for path in FILES:
        src = path.read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), f"hex color in {path.name}"
        assert not re.search(r"\b(rgb|hsl|oklch)a?\(", src), f"color function in {path.name}"
        assert "gradient" not in src, f"gradient in {path.name}"
        assert not re.search(r"\b(?:bg|text|border|ring|fill|stroke|from|to|via)-(?:red|blue|green|amber|yellow|sky|zinc|slate|gray|orange|violet|rose)-\d", src), f"palette color in {path.name}"


def test_every_ent_key_used_exists_in_english_and_french():
    en, fr = _keys(WEB / "i18n" / "en.ts"), _keys(WEB / "i18n" / "fr.ts")
    used = {k for path in FILES for k in KEY.findall(path.read_text(encoding="utf-8"))}
    assert used, "no ent.* key found in the sources"
    assert not used - en, f"missing in en.ts: {sorted(used - en)}"
    assert not used - fr, f"missing in fr.ts: {sorted(used - fr)}"
    assert en == fr, f"en and fr differ: {sorted(en ^ fr)}"
    # no key left over: everything defined is shown somewhere
    base = {k.split("#")[0] for k in en}
    assert not base - used, f"unused keys: {sorted(base - used)}"


def test_the_tabs_of_an_enterprise_are_one_array():
    tabs = (WEB / "features" / "enterprises" / "tabs.tsx").read_text(encoding="utf-8")
    assert "export const ENTERPRISE_TABS" in tabs
    page = (WEB / "features" / "enterprises" / "EnterprisePage.tsx").read_text(encoding="utf-8")
    assert "ENTERPRISE_TABS" in page and "OrgChart" not in page  # the page knows no tab by name


def test_the_chart_is_a_list_on_a_phone_and_drags_with_the_mouse_only():
    chart = (WEB / "features" / "enterprises" / "OrgChart.tsx").read_text(encoding="utf-8")
    assert "useCompact()" in chart and "ListNode" in chart
    assert "pointerType !== 'mouse'" in chart  # no drag on a touch screen: the panel's Change lead does it
    assert "aria-expanded" in chart
