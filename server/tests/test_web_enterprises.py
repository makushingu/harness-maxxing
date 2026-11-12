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


def test_the_tabs_overview_decisions_reports_profile_follow_the_chart():
    tabs = (WEB / "features" / "enterprises" / "tabs.tsx").read_text(encoding="utf-8")
    ids = re.findall(r"\{ id: '([a-z]+)', label:", tabs)
    assert ids[:2] == ["chart", "overview"]
    assert {"decisions", "reports", "profile", "settings"} <= set(ids)


def test_the_queries_cover_the_flow_routes_of_the_contract():
    q = (WEB / "lib" / "queries" / "enterprises.ts").read_text(encoding="utf-8")
    for route in ("/overview", "/reports", "/requests", "/escalations", "/about", "/profile", "/insights"):
        assert f"'{route}" in q or f"`{route}" in q or f"`/reports/" in q, route
    for hook in ("useEnterpriseOverview", "useBuildReport", "useDecideRequest", "useAnswerEscalation", "usePutEnterpriseAbout", "usePutEnterpriseProfile", "useEnterpriseInsights"):
        assert f"export function {hook}" in q, hook


def test_the_enterprises_showcase_exists_in_both_languages():
    src = (WEB / "features" / "whatsnew" / "showcases.ts").read_text(encoding="utf-8")
    assert re.search(r"enterprises: \[\{ id: 'enterprises',[^\n]*show\.enterprises\.title[^\n]*show\.enterprises\.body", src)
    target = re.search(r"enterprises: \[\{ id: 'enterprises', targets: \['([a-z-]+)'\]", src)
    assert target and f'data-tour="{target[1]}"' in (WEB / "features" / "enterprises" / "EnterprisesList.tsx").read_text(encoding="utf-8")
    for lang in ("en", "fr"):
        text = (WEB / "i18n" / f"{lang}.ts").read_text(encoding="utf-8")
        for k in ("show.enterprises.title", "show.enterprises.body", "agents.office.org", "agents.office.orgLead", "agents.office.orgOthers", "agents.office.orgNoDept"):
            assert re.search(rf"""['"]{re.escape(k)}['"]\s*:""", text), f"{k} missing in {lang}.ts"


def test_the_office_org_view_is_sober_and_does_not_replace_classic_or_space():
    org = (WEB / "features" / "agents" / "OfficeOrg.tsx").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\b(rgb|hsl|oklch)a?\(|gradient", org)
    page = (WEB / "features" / "agents" / "AgentsPage.tsx").read_text(encoding="utf-8")
    assert "id: 'classic'" in page and "id: 'future'" in page and "id: 'org'" in page
    custom = (WEB / "features" / "agents" / "OfficeCustom.tsx").read_text(encoding="utf-8")
    assert "reports_to:" in custom and "enterprise:" in custom


def test_a_position_with_reports_is_removed_by_moving_them_to_its_lead():
    sheet = (WEB / "features" / "enterprises" / "PositionSheet.tsx").read_text(encoding="utf-8")
    assert "reparent_to: lead" in sheet and "'has_reports'" in sheet and "value=\"work\"" in sheet


def test_the_front_desk_and_workers_are_wired():
    q = (WEB / "lib" / "queries" / "enterprises.ts").read_text(encoding="utf-8")
    for route in ("/desk", "/desk/link", "/profile/suggestions", "/workers", "/insights"):
        assert f"'{route}" in q or f"`{route}" in q, route
    for hook in ("useEnterpriseDesk", "useDeskConversation", "useDeleteDeskConversation", "useSaveDeskSettings", "useDeskLink",
                 "useRunInsights", "useDeskSuggestions", "useDecideSuggestion", "useEnterpriseWorkers", "useStopWorker"):
        assert f"export function {hook}" in q, hook
    tabs = (WEB / "features" / "enterprises" / "tabs.tsx").read_text(encoding="utf-8")
    assert re.search(r"id: 'desk',[^\n]*show: \(e\) => [^\n]*desk[^\n]*positions\.some\(\(p\) => p\.desk\)", tabs)
    settings = (WEB / "features" / "enterprises" / "EnterpriseSettings.tsx").read_text(encoding="utf-8")
    assert "<DeskSettings" in settings
    desk = (WEB / "features" / "enterprises" / "DeskSettings.tsx").read_text(encoding="utf-8")
    assert "/api/public/desk/" in desk and "ent.deskSettings.warning" in desk and "CopyButton" in desk
    sheet = (WEB / "features" / "enterprises" / "PositionSheet.tsx").read_text(encoding="utf-8")
    assert all(x in sheet for x in ("<DeskSwitch", "<WorkerTemplateEditor", "<PositionWorkers"))
    dialogs = (WEB / "features" / "enterprises" / "dialogs.tsx").read_text(encoding="utf-8")
    assert "useAgentTemplates" in dialogs and "suggested_template" in dialogs


def test_the_envelope_skip_reason_has_its_web_text_and_the_mock_has_the_new_routes():
    parts = (WEB / "features" / "agents" / "parts.tsx").read_text(encoding="utf-8")
    assert "reason === 'envelope'" in parts
    for lang in ("en", "fr"):
        assert re.search(r"""['"]agents\.reason\.envelope['"]\s*:""", (WEB / "i18n" / f"{lang}.ts").read_text(encoding="utf-8"))
    mock = (WEB.parent / "mock" / "server.mjs").read_text(encoding="utf-8")
    for route in ("/api/enterprises/:e/desk'", "/api/enterprises/:e/desk/link'", "/api/enterprises/:e/desk/:conv'", "/api/enterprises/:e/insights'",
                  "/api/enterprises/:e/profile/suggestions'", "/api/enterprises/:e/profile/suggestions/:sid'", "/api/enterprises/:e/workers'",
                  "/api/enterprises/:e/workers/:wid'"):
        assert route in mock, route
