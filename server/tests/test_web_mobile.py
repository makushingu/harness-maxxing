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


def test_the_tasks_open_as_a_list_on_a_phone():
    # the board shows one column at a time on a phone: the list is the default there, a view picked by hand is kept
    tasks = (WEB / "pages" / "tasks" / "index.tsx").read_text()
    assert "view: isCompact() ? 'list' : 'board'," in tasks
    assert "{ ...def, ...JSON.parse(localStorage.getItem(PREFS_KEY)" in tasks


def test_a_session_header_on_a_phone_leaves_room_to_read():
    # one tab repeated the title under it, the tabs stayed while typing, and held sideways only ~90 px were left to read
    src = (WEB / "pages" / "sessions" / "index.tsx").read_text()
    assert "const several = useSessionsUI((s) => s.cols.length > 1)" in src
    assert "<MobileTabsSlot.Provider value={several ? <TabsBar" in src  # the phone always shows its open sessions as tabs
    column = (WEB / "pages" / "sessions" / "Column.tsx").read_text()
    assert '<div data-kbd-hide="" data-tabs="">{tabs}</div>' in column
    css = (WEB / "styles" / "globals.css").read_text()
    assert re.search(
        r"@media \(orientation: landscape\) and \(max-height: 500px\) and \(pointer: coarse\) \{\s*"
        r"\[data-col\] \[data-kbd-hide\]:not\(\[data-tabs\]\) \{\s*display: none;",
        css,
    )  # the place rows go, the tabs stay (switching session with several open)


def test_the_send_button_wraps_under_the_tools_instead_of_leaving_the_screen():
    # an agent conversation has model, gauge, new chat, call, Stop, microphone and Send: wider than a 412 px phone, the
    # right group shrank to nothing and Send was cut by the right edge; the bar wraps so every button stays in sight
    src = (WEB / "features" / "composer" / "MessageBox.tsx").read_text()
    assert '<div className="@container flex min-w-0 flex-wrap items-center gap-1 px-1.5 pb-1.5">' in src
    assert '<div className="ml-auto flex min-w-0 items-center gap-1.5">' in src


def test_a_diff_keeps_its_line_numbers_and_hunk_heads_in_sight_when_scrolled_sideways():
    src = (WEB / "features" / "code" / "DiffRows.tsx").read_text()
    gutter = re.search(r'className="([^"]*)" data-testid="diff-gutter"', src)
    assert gutter and {"sticky", "left-0", "bg-popover"} <= set(gutter[1].split())  # opaque: the code passes under it
    assert '<span className="sticky left-0 inline-block px-3">{r.text}</span>' in src  # a full-width block never sticks


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


def test_the_links_of_a_cut_turn_are_big_enough_to_tap():
    src = (WEB / "pages" / "sessions" / "Cut.tsx").read_text()
    usage = re.search(r'<a href=\{url\}[^>]*className="([^"]*)"', src)
    assert usage and "pointer-coarse:h-10" in usage[1].split()
    details = re.search(r'aria-expanded=\{open\}\s+onClick=\{\(\) => setOpen\(\(o\) => !o\)\}\s+className="([^"]*)"', src)
    assert details and "pointer-coarse:h-10" in details[1].split()


def test_the_name_of_a_source_keeps_room_next_to_its_buttons():
    src = (WEB / "features" / "infra" / "Overview.tsx").read_text()
    block = re.search(r'<div className="([^"]*)">\s*<span className="truncate text-\[13px\] font-medium">\{title\}', src)
    assert block and "basis-40" in block[1].split()


def test_the_counts_of_the_infra_matrix_are_big_enough_to_tap():
    src = (WEB / "features" / "infra" / "InfraPage.tsx").read_text()
    count = re.search(r'onClick=\{\(\) => onPlace\(x, p\.key\)\}\s+className="([^"]*)"', src)
    assert count and "pointer-coarse:min-h-10" in count[1].split()


def test_the_path_of_a_memory_file_takes_the_width_of_the_table():
    src = (WEB / "pages" / "settings" / "sections" / "Memory.tsx").read_text()
    cell = re.search(r'<td className="([^"]*)" title=\{mask\(f\.path, 12\)\}>', src)
    assert cell and "w-full" in cell[1].split()


def test_the_links_under_a_git_block_are_big_enough_to_tap():
    src = (WEB / "features" / "git" / "GitBlock.tsx").read_text()
    code = re.search(r'<button type="button" className="([^"]*)" onClick=\{\(\) => setShowCode\(true\)\}', src)
    page = re.search(r'<Link to=\{`/git\?repo=[^`]*`\} className="([^"]*)"', src)
    github = re.search(r'<a href=\{repo\.url\}[^>]*className="([^"]*)"', src)
    for m in (code, page, github):
        assert m and "pointer-coarse:min-h-10" in m[1].split()
    assert "pointer-coarse:min-w-10" in github[1].split()


def test_the_error_of_a_browser_exit_breaks_inside_the_card():
    src = (WEB / "features" / "browser" / "Exits.tsx").read_text()
    err = re.search(r"exit\.state === 'down' && <span className=\"([^\"]*)\">· \{exit\.error\}", src)
    assert err and {"min-w-0", "[overflow-wrap:anywhere]"} <= set(err[1].split())


def test_the_name_of_a_browser_profile_takes_the_width_of_a_phone():
    src = (WEB / "features" / "browser" / "ProfilePage.tsx").read_text()
    field = re.search(r'className="([^"]*)"\s+data-testid="browser-profile-name"', src)
    assert field and {"w-full", "sm:w-56", "pointer-coarse:h-10"} <= set(field[1].split()) and "w-56" not in field[1].split()


def test_the_links_of_the_browser_settings_are_big_enough_to_tap():
    browser = WEB / "features" / "browser"
    settings = (browser / "BrowserSettings.tsx").read_text()
    add = re.search(r"function AddRow[^\n]*\n  const cls = '([^']*)'", settings)
    back = re.search(r'<Link to=\{BROWSER_SETTINGS\} className="([^"]*)"', settings)
    more = re.search(r'<button type="button" className="([^"]*)" onClick=\{\(\) => setMore\(!more\)\}',
                     (browser / "BrowserFeature.tsx").read_text())
    ts = re.findall(r'<button type="button" className="([^"]*)" onClick=\{\(\) => (?:setAdvanced\(true\)|set\.mutate\(\{ id: exit\.id, action: \'logout\' \}\))\}',
                    (browser / "Exits.tsx").read_text())
    assert add and back and more and len(ts) == 2
    for cls in (add[1], back[1], more[1], *ts):
        assert "pointer-coarse:min-h-10" in cls.split()


def test_a_confirmation_with_a_long_name_stays_on_the_screen():
    src = (WEB / "components" / "ui" / "alert-dialog.tsx").read_text()
    content = re.search(r"'mx-glass fixed z-50 grid ([^']*)'", src)
    title = re.search(r"<AD\.Title className=\{cn\('([^']*)'", src)
    assert content and "grid-cols-[minmax(0,1fr)]" in content[1].split()
    assert title and "[overflow-wrap:anywhere]" in title[1].split()


def test_the_audio_player_with_a_long_name_stays_on_the_screen():
    src = (WEB / "features" / "files" / "MediaPlayer.tsx").read_text()
    root = re.search(r"cn\('(relative grid w-full max-w-lg [^']*)', className\)\} tabIndex=\{0\}", src)
    assert root and "grid-cols-[minmax(0,1fr)]" in root[1].split()


def test_a_settings_card_with_a_long_title_stays_on_the_screen():
    src = (WEB / "pages" / "settings" / "sections" / "ui.tsx").read_text()
    head = re.search(r'<div className="([^"]*)">\s*\{title && <h3 className=\{cn\(\'([^\']*)\'', src)
    assert head and {"min-w-0", "grid-cols-[minmax(0,1fr)]"} <= set(head[1].split())
    assert "[overflow-wrap:anywhere]" in head[2].split()


def test_the_browser_panel_with_a_long_profile_name_stays_on_the_screen():
    src = (WEB / "features" / "browser" / "BrowserPanel.tsx").read_text()
    root = re.search(r'<div className="([^"]*)" data-testid="browser-panel">', src)
    assert root and "grid-cols-[minmax(0,1fr)]" in root[1].split()
    line = re.search(r"<p className=\"([^\"]*)\">\{t\('browser\.panel\.projectProfile'", src)
    assert line and "break-words" in line[1].split()


def test_the_profile_settings_link_of_the_browser_panel_is_big_enough_to_touch():
    src = (WEB / "features" / "browser" / "BrowserPanel.tsx").read_text()
    link = re.search(r'<Link to=\{`/settings/browser\?[^`]*`\} className="([^"]*)">', src)
    assert link and {"pointer-coarse:inline-flex", "pointer-coarse:min-h-10"} <= set(link[1].split())


def test_a_long_claude_sign_in_error_stays_inside_the_card():
    src = (WEB / "features" / "claude" / "ClaudeConnect.tsx").read_text()
    root = re.search(r'<div className="([^"]*)">\s*<Callout\s+tone=\{s\.auth\.ok', src)
    assert root and "grid-cols-[minmax(0,1fr)]" in root[1].split()
    detail = re.search(r'\{s\.auth\.detail && \(\s*<span className="([^"]*)">', src)
    assert detail and "[overflow-wrap:anywhere]" in detail[1].split()


def test_the_mail_folder_and_mailbox_menus_are_visible_and_big_enough_to_tap():
    src = (WEB / "features" / "mail" / "MailPage.tsx").read_text()
    for label in ("mail.folder.menu", "mail.accountMenu"):
        cls = re.search(r'className="([^"]*)"\s*aria-label=\{t\(\'' + re.escape(label) + r"'\)\}", src)
        assert cls and "pointer-coarse:size-10" in cls[1].split(), label
        assert "hidden" not in cls[1].split() or "pointer-coarse:flex" in cls[1].split(), label


def test_the_voice_call_status_button_is_big_enough_to_touch():
    src = (WEB / "features" / "voice" / "VoiceCall.tsx").read_text()
    cls = re.search(r'onClick=\{\(\) => voice\.current\?\.interrupt\(\)\}\s*className="([^"]*)"', src)
    assert cls and "pointer-coarse:h-10" in cls[1].split()


def test_the_linked_resources_of_an_infra_detail_are_big_enough_to_tap():
    src = (WEB / "features" / "infra" / "InfraPage.tsx").read_text()
    cls = re.search(r'onClick=\{\(\) => onOpen\(l\.id\)\} className="([^"]*)"', src)
    assert cls and "pointer-coarse:min-h-10" in cls[1].split()


def test_the_controls_of_the_pdf_and_html_viewers_are_big_enough_to_tap():
    for name in ("viewers.tsx", "rich.tsx"):
        src = (WEB / "features" / "files" / name).read_text()
        assert "h-7" in src and "pointer-coarse:h-9" not in src
        assert "pointer-coarse:h-10" in src


def test_the_role_protection_line_and_new_group_link_of_an_agent_are_big_enough_to_tap():
    src = (WEB / "features" / "agents" / "AgentPage.tsx").read_text()
    for testid in ("agent-sandbox-line", "agent-new-group", "agent-role"):
        cls = re.search(r"className=(?:\{cn\()?['\"]([^'\"]*)['\"][^\n]*\n(?:[^\n]*\n)?\s*data-testid=\"" + testid + '"', src)
        assert cls and "pointer-coarse:min-h-10" in cls[1].split(), testid


def test_a_dictation_arriving_during_a_team_edit_does_not_replace_the_edited_text():
    src = (WEB / "features" / "team" / "Chat.tsx").read_text(encoding="utf-8")
    m = re.search(r"const onDraft = \(e: Event\) => \{(.*?)\n    \}\n", src, re.S)
    assert m
    body = m.group(1)
    assert body.index("editingNow.current") < body.index("setText(")


def test_signing_out_and_deleting_a_session_forget_the_side_questions():
    # the side questions persist in sessionStorage `mx-asides`; drafts.ts cleared the drafts but left them for the next user
    drafts = (WEB / "lib" / "drafts.ts").read_text()
    aside = (WEB / "pages" / "sessions" / "Aside.tsx").read_text()
    assert "sessionStorage.removeItem('mx-asides')" in drafts
    assert re.search(r"export function forgetAllDrafts\(\)[\s\S]*?forgetAside\(\)", drafts)
    assert re.search(r"export function forgetDraft\(key: string\)[\s\S]*?forgetAside\(key\)", drafts)
    assert "ASIDE_FORGET_EVENT" in aside


def test_the_chips_of_empty_task_projects_are_big_enough_to_tap():
    # the chips of projects without a task were 32 px high on a phone, under the 40 px of the other buttons
    overview = (WEB / "features" / "tasks" / "Overview.tsx").read_text()
    chip = re.search(r'<button[^>]*onClick=\{\(\) => onPick\(p\.id\)\}[^>]*className="([^"]*)"', overview)
    assert chip and "pointer-coarse:h-10" in chip[1].split()


def test_the_tasks_footer_hint_has_a_touch_text_without_ctrl_click():
    src = (WEB / "pages" / "tasks" / "index.tsx").read_text()
    assert re.search(r'className="pointer-coarse:hidden">\{t\(\'tasks\.footerHint\'\)\}', src)
    assert re.search(r'className="hidden pointer-coarse:inline">\{t\(\'tasks\.footerHintTouch\'\)\}', src)
    for lang in ("en", "fr"):
        touch = re.search(r"'tasks\.footerHintTouch': '((?:[^'\\]|\\.)*)'", (WEB / "i18n" / f"{lang}.ts").read_text())
        assert touch and "Ctrl" not in touch[1], lang


def test_settings_opens_on_the_list_of_its_sections_on_a_phone():
    routes = (WEB / "routes.tsx").read_text()
    assert "path: 'settings/:section?'" in routes and "path: 'settings', element: <Navigate" not in routes
    src = (WEB / "pages" / "settings" / "index.tsx").read_text()
    assert 'return mobile ? <SettingsList /> : <Navigate to="/settings/general" replace />' in src
    lst = src[src.index("function SettingsList"):src.index("function SettingsPage")]
    assert "SETTINGS_GROUPS.map" in lst and "min-h-12" in lst, "every section, grouped, big enough to tap"


def test_files_on_a_phone_is_the_folder_until_a_file_is_open():
    # a phone landed on an empty viewer ("pick a file on the left") with the folder behind the drawer (#151)
    src = (WEB / "pages" / "files" / "index.tsx").read_text()
    assert "const inline = mobile && !file" in src and "inline={inline}" in src and "{!inline && (" in src
    page_list = (WEB / "components" / "shell" / "PageList.tsx").read_text()
    assert "if (here && panel === 'list') useTouchNav.getState().setPanel(null)" in page_list


def test_the_agent_limits_ignore_a_number_that_overflows_once_scaled():
    # 1e308 * 60 (minutes -> seconds) is Infinity: JSON.stringify sends null for it
    src = (WEB / "features" / "agents" / "parts.tsx").read_text(encoding="utf-8")
    assert re.search(r"if \(Number\.isFinite\(v\)\) onChange\(\{ \.\.\.value, \[k\]: v \}\)", src)


def test_the_inline_page_list_keeps_its_filter_and_tools():
    # on a phone with nothing open, the list is the page: its ListHead (filter, view, sort, hidden files) must be there
    src = (WEB / "components" / "shell" / "PageList.tsx").read_text()
    inline = src[src.index("  if (here) {"):src.index("  if (!slot) return null")]
    assert "<ListHead" in inline and "search={search}" in inline and "{actions}" in inline


def test_the_key_checks_of_an_agent_are_big_enough_to_tap():
    src = (WEB / "features" / "agents" / "parts.tsx").read_text()
    row = re.search(r'<label key=\{n\} className="([^"]*)"', src)
    assert row and "pointer-coarse:min-h-10" in row[1].split()


def test_an_inline_edit_diff_wraps_its_lines_on_a_phone():
    # at 360 px about 34 characters of a diff line fit: every edit had to be scrolled sideways to be read
    src = (WEB / "pages" / "sessions" / "Items.tsx").read_text()
    view = src[src.index("export function DiffView"):src.index("function ToolOutput")]
    row = re.search(r"'flex min-w-max px-2([^']*)'", view)
    assert row and "max-md:min-w-0" in row[1].split()
    text = re.search(r'<span className="whitespace-pre ([^"]*)">\{l\.s', view)
    assert text and {"max-md:whitespace-pre-wrap", "max-md:[overflow-wrap:anywhere]"} <= set(text[1].split())


def test_the_quote_button_is_big_enough_to_tap():
    src = (WEB / "pages" / "sessions" / "Quote.tsx").read_text()
    btn = re.search(r"'(mx-queue-in [^']*)'", src)
    assert btn and "pointer-coarse:h-10" in btn[1].split() and "window.innerHeight - 56" in src


def test_the_open_url_link_of_the_infra_type_view_is_big_enough_to_tap():
    src = (WEB / "features" / "infra" / "TypeView.tsx").read_text()
    link = re.search(r'target="_blank".{0,200}?className="([^"]*)"', src, re.S)
    assert link and "pointer-coarse:size-10" in link[1].split()
