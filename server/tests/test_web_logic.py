"""Pure helpers of the interface, run by Node on their TypeScript source (skipped without a Node that strips types)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


def _run_ts(tmp_path: Path, source: Path, script: str):
    """Import `source` (only type imports allowed) as `m` and print JSON.stringify of `script`'s value."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    (tmp_path / "mod.ts").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "main.mjs").write_text(
        f"import * as m from './mod.ts'\nconsole.log(JSON.stringify(await (async () => {{ {script} }})()))\n",
        encoding="utf-8")
    r = subprocess.run([node, "--experimental-strip-types", "--no-warnings", "main.mjs"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    if r.returncode and ("strip-types" in r.stderr or "Unknown file extension" in r.stderr):
        pytest.skip("this node cannot strip types")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


SCHEDULE = WEB / "features" / "crons" / "schedule.ts"


def test_a_cron_step_that_does_not_divide_the_hour_or_the_day_is_custom(tmp_path):
    kinds = _run_ts(tmp_path, SCHEDULE, """return ['*/45 * * * *', '*/7 * * * *', '0 */7 * * *', '0 */5 * * *',
        '*/15 * * * *', '*/20 * * * *', '30 */6 * * *', '0 */12 * * *'].map((e) => m.toPreset(e).kind)""")
    assert kinds == ["custom"] * 4 + ["minutes", "minutes", "hours", "hours"]


def test_the_default_one_time_date_is_a_whole_hour_in_the_configured_zone(tmp_path):
    out = _run_ts(tmp_path, SCHEDULE, """const t = Date.UTC(2026, 10, 14, 10, 0) / 1000
        return ['Asia/Kolkata', 'Asia/Kathmandu', 'Australia/Adelaide', 'UTC', 'Europe/Paris']
          .map((z) => [m.defaultOnceAt(z, t), m.defaultOnceAt(z, t + 1)])""")
    assert out == [["2026-11-14T16:00", "2026-11-14T17:00"], ["2026-11-14T17:00", "2026-11-14T17:00"],
                   ["2026-11-14T21:00", "2026-11-14T22:00"], ["2026-11-14T11:00", "2026-11-14T11:00"],
                   ["2026-11-14T12:00", "2026-11-14T12:00"]]


def test_a_zone_the_browser_refuses_falls_back_instead_of_throwing(tmp_path):
    t = 1794816000                                         # 2026-11-16T08:00:00Z
    out = _run_ts(tmp_path, SCHEDULE, f"return [m.inputInZone({t}, 'Factory'), m.defaultOnceAt('Factory', {t})]")
    assert out == ["2026-11-16T08:00", "2026-11-16T09:00"]
    out = _run_ts(tmp_path, WEB / "lib" / "format.ts", f"return [m.fmtDate({t}, 'en', 'Factory', {{timeZone: 'Factory'}}) !== '',"
                  f" m.fmtDate({t}, 'en', 'UTC', {{dateStyle: 'short', timeStyle: 'short'}})]")
    assert out == [True, "11/16/26, 8:00 AM"]


def test_a_task_whose_project_is_gone_is_listed_where_it_is_counted(tmp_path):
    out = _run_ts(tmp_path, WEB / "features" / "tasks" / "model.ts", """
        const task = (id, project_id) => ({ id, title: id, notes: '', status: 'todo', priority: 0, project_id, labels: [], due: null })
        const projects = [{ id: 'p_a', name: 'A' }]
        const tasks = m.withKnownProjects([task('t1', 'p_gone'), task('t2', 'p_a'), task('t3', null)], projects)
        const none = { ...m.EMPTY_FILTERS, project: 'none' }
        return [m.projectStats(tasks, projects, '2026-11-14').get('')?.total,
                tasks.filter((x) => m.matches(x, none, '2026-11-14')).map((x) => x.id), tasks[1].project_id]""")
    assert out == [2, ["t1", "t3"], "p_a"]


def test_the_quick_add_of_a_board_column_keeps_the_focus_while_it_adds():
    src = (WEB / "features" / "tasks" / "Board.tsx").read_text(encoding="utf-8")
    end = src.index("placeholder={t('tasks.quickAddPlaceholder')}")
    field = src[src.rindex("<Input", 0, end):end]
    assert "readOnly={busy}" in field and "disabled=" not in field


def test_the_agents_layout_never_reads_a_project_name_from_the_prototype():
    # a project named "constructor" (a valid slug) with 2 agents: lay.agents[p] was Object, and the page crashed
    src = (WEB / "features" / "agents" / "layout.tsx").read_text(encoding="utf-8")
    assert not re.search(r"lay\.(?:agents|colors)\[", src)
    assert "Array.isArray(list)" in src


def test_a_group_limit_keeps_what_is_typed_until_the_field_is_left():
    # Bounding on every key turned an emptied field into 1, then typing 5 gave 15 (or 6).
    src = (WEB / "features" / "agents" / "GroupForm.tsx").read_text()
    assert "value={String(f.limits[k])}" not in src
    field = re.search(r"function LimitInput\(.*?\n}\n", src, re.S)
    assert field and "value={text}" in field[0] and "onBlur={() => setText(String(value))}" in field[0]


def test_save_a_copy_never_picks_the_name_of_a_hidden_file():
    """The copy is written without a mtime check: its name must avoid hidden files too, not only the shown ones."""
    view = (WEB / "pages" / "files" / "FileView.tsx").read_text(encoding="utf-8")
    page = (WEB / "pages" / "files" / "index.tsx").read_text(encoding="utf-8")
    assert "const taken = new Set((folder ?? siblings).map((s) => s.name))" in view
    assert re.search(r"<FileView [^>]*folder=\{list\?\.entries\}", page)


NAV_PICTURE = WEB / "features" / "browser" / "useNavPicture.ts"


def _nav_picture(tmp_path: Path, script: str):
    """Run useNavPicture with a stubbed React (one effect at a time), fetch and blob URLs; `script` returns the value."""
    src = NAV_PICTURE.read_text(encoding="utf-8")
    src = src.replace("import * as React from 'react'", "const React = (globalThis as any).R")
    src = src.replace("import { seg } from '@/lib/api'", "const seg = encodeURIComponent")
    (tmp_path / "hook.ts").write_text(src, encoding="utf-8")
    stubs = """
let cleanup
const sets = [], created = [], revoked = []
let n = 0
globalThis.R = { useState: (v) => [v, (x) => sets.push(x)], useEffect: (f) => { cleanup = f() } }
globalThis.document = { visibilityState: 'visible' }
URL.createObjectURL = () => { const u = 'blob:' + ++n; created.push(u); return u }
URL.revokeObjectURL = (u) => revoked.push(u)
const wait = () => new Promise((r) => setTimeout(r, 10))
const { useNavPicture } = await import('./hook.ts')
"""
    return _run_main(tmp_path, stubs + script)


def _run_main(tmp_path: Path, body: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    (tmp_path / "main.mjs").write_text(f"{body}\nconsole.log(JSON.stringify(out))\nprocess.exit(0)\n", encoding="utf-8")
    r = subprocess.run([node, "--experimental-strip-types", "--no-warnings", "main.mjs"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    if r.returncode and ("strip-types" in r.stderr or "Unknown file extension" in r.stderr):
        pytest.skip("this node cannot strip types")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_a_nav_picture_closed_while_it_downloads_leaves_no_blob_url(tmp_path):
    out = _nav_picture(tmp_path, """
let release
globalThis.fetch = async () => ({ status: 200, blob: () => new Promise((r) => (release = () => r(new Blob(['x'])))) })
useNavPicture('p1', 'me', true)
await wait()
cleanup()            // the panel is closed while the picture is still downloading
release()
await wait()
const out = { leaked: created.filter((u) => !revoked.includes(u)), shown: sets.filter(Boolean) }
""")
    assert out == {"leaked": [], "shown": []}


def test_a_nav_picture_never_shows_the_revoked_picture_of_the_previous_profile(tmp_path):
    out = _nav_picture(tmp_path, """
globalThis.fetch = async (u) => u.includes('/p1/') ? { status: 200, blob: async () => new Blob(['x']) } : { status: 503 }
useNavPicture('p1', 'me', true)
await wait()
cleanup()
useNavPicture('p2', 'me', true)      // p2 is still starting: no picture yet
await wait()
cleanup()
const last = sets[sets.length - 1]
const out = { last, revoked: revoked.includes(last) }
""")
    assert out == {"last": None, "revoked": False}


def test_a_long_code_block_is_shown_without_colours_and_markdown_sooner(tmp_path):
    out = _run_ts(tmp_path, WEB / "components" / "ui" / "highlightLimit.ts", """return [
        m.canHighlight('markdown', 20000), m.canHighlight('MD', 3001), m.canHighlight('md', 3000),
        m.canHighlight('java', 20001), m.canHighlight('java', 20000), m.canHighlight('python', 500)]""")
    assert out == [False, False, True, False, True, True]
    src = (WEB / "components" / "ui" / "markdown.tsx").read_text(encoding="utf-8")
    assert re.search(r"if \(!canHighlight\(lang, text\.length\)\) continue\s+code\.children = ll\.highlight\(lang, text\)", src)


def _html_to_text(tmp_path: Path, tree: str, body: str):
    """Run htmlToText (plainText.ts imports remark: only its HTML part is taken) on a small fake DOM built by `tree`
    (node has no DOMParser), then `body` (`run()` gives the text)."""
    src = (WEB / "features" / "files" / "plainText.ts").read_text(encoding="utf-8")
    part = src[src.index("// Trims written as loops"):src.index("export function markdownToText(")] + \
        src[src.index("const HTML_SKIP"):src.index("/** Cells separated by tabs")]
    dom = """
class T { constructor(v) { this.nodeType = 3; this.nodeValue = v; this.childNodes = [] } }
class E {
  constructor(tag, attrs, kids) {
    this.nodeType = 1; this.tagName = tag.toUpperCase(); this.attrs = attrs; this.childNodes = []; this.parentElement = null
    for (const k of kids) this.add(typeof k === 'string' ? new T(k) : k)
  }
  add(k) { if (k.nodeType === 1) { k.parentElement = this; k.previousElementSibling = this.last ?? null; this.last = k } this.childNodes.push(k) }
  getAttribute(a) { return this.attrs[a] ?? null }
  closest(sel) { for (let e = this; e; e = e.parentElement) if (e.tagName === sel.toUpperCase()) return e; return null }
}
const h = (tag, attrs, ...kids) => new E(tag, attrs, kids)
let BODY
globalThis.DOMParser = class { parseFromString() { return { body: BODY } } }
"""
    (tmp_path / "main.ts").write_text(dom + part + f"\nBODY = (() => {{ {tree} }})()\nconst run = () => htmlToText('')\n"
                                      f"console.log(JSON.stringify((() => {{ {body} }})()))\n", encoding="utf-8")
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, "--experimental-strip-types", "--no-warnings", "main.ts"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)
    if r.returncode and ("strip-types" in r.stderr or "Unknown file extension" in r.stderr):
        pytest.skip("this node cannot strip types")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_html_to_text_keeps_its_layout(tmp_path):
    tree = """return h('body', {}, h('h1', {}, 'Title '), h('p', {}, 'one  ', h('b', {}, 'two'), h('br', {}), 'three'),
      h('ul', {}, h('li', {}, 'a'), h('li', {}, 'b', h('ol', { start: '3' }, h('li', {}, 'x'), h('li', {}, 'y')))),
      h('table', {}, h('tr', {}, h('td', {}, 'c1'), h('td', {}, 'c2')), h('tr', {}, h('td', {}, 'd1'), h('td', {}, 'd2'))),
      h('pre', {}, '  code\\n  more'), h('div', {}, h('img', { alt: 'pic' }), ' end'))"""
    assert _html_to_text(tmp_path, tree, "return run()") == (
        "Title\n\none two\nthree\n\n- a\n- b\n  3. x\n  4. y\n\nc1\tc2\nd1\td2\n\n  code\n  more\n\npic end")


def test_html_to_text_of_a_long_page_takes_linear_time(tmp_path):
    """40 000 paragraphs (870 KB of HTML), 40 000 list items, a table of 40 000 cells: each took 10 to 90 s before
    (regexes and replaces over the whole text at each block, list numbers counted from the first item each time)."""
    tree = """const ps = []; for (let i = 0; i < 40000; i++) ps.push(h('p', {}, `paragraph ${i}`))
      const lis = []; for (let i = 0; i < 40000; i++) lis.push(h('li', {}, `item ${i}`))
      const trs = []; for (let i = 0; i < 4000; i++) { const tds = []; for (let j = 0; j < 10; j++) tds.push(h('td', {}, `v${i}-${j}`)); trs.push(h('tr', {}, ...tds)) }
      return h('body', {}, ...ps, h('ol', {}, ...lis), h('table', {}, ...trs))"""
    out = _html_to_text(tmp_path, tree, """const t0 = performance.now(); const s = run()
      return [Math.round(performance.now() - t0), s.split('\\n').length, s.endsWith('v3999-8\\tv3999-9'), s.includes('\\n40000. item 39999\\n')]""")
    assert out[1:] == [40000 * 2 + 1 + 40000 + 1 + 4000 - 1, True, True]
    assert out[0] < 10_000, out


def test_the_context_window_and_the_draft_attachments_read_stored_data_with_their_types():
    util = (WEB / "pages" / "sessions" / "util.ts").read_text(encoding="utf-8")
    body = util[util.index("export function contextWindow"):util.index("export function modelLabel")]
    assert "Object.hasOwn(windows" in body and not re.search(r"windows\[(chosen|real)\]", body)   # `constructor` is not a window
    store = (WEB / "pages" / "sessions" / "store.ts").read_text(encoding="utf-8")
    atts = store[store.index("export function loadAtts"):store.index("export function saveAtts")]
    assert "typeof a.name === 'string'" in atts and "Number.isFinite(a.size)" in atts


def test_durations_and_tokens_are_rounded_before_they_are_split(tmp_path):
    util = (WEB / "pages" / "sessions" / "util.ts").read_text(encoding="utf-8")   # (it has runtime imports: cut out two helpers)
    pick = lambda a, b: util[util.index(a):util.index(b)]  # noqa: E731
    mod = tmp_path / "fmt.ts"
    mod.write_text(pick("export function fmtTokens", "export function fmtCost")
                   + pick("export function fmtMs", "export function fmtElapsed"), encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    out = _run_ts(run, mod, "return [m.fmtMs(119600), m.fmtMs(59600), m.fmtMs(65000), m.fmtTokens(999999), m.fmtTokens(999400)]")
    assert out == ["2 min 0 s", "1 min 0 s", "1 min 5 s", "1.0M", "999k"]


def test_a_name_glued_to_a_word_is_not_a_mention():
    src = (WEB / "pages" / "sessions" / "mentions.tsx").read_text(encoding="utf-8")
    assert "(?<!\\\\S)@${label" in src                    # an "@Name" glued to a word (bob@Lea.fr) is no mention


def test_the_initials_of_a_sender_starting_with_an_emoji_are_not_cut_in_half(tmp_path):
    src = (WEB / "features" / "mail" / "shared.tsx").read_text(encoding="utf-8")
    mod = tmp_path / "initials.ts"
    mod.write_text(src[src.index("export function initials"):src.index("const HUES")].replace(
        "a: MailAddress | undefined", "a: any"), encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    out = _run_ts(run, mod, "return [m.initials({ name: '😀 Bob' }), m.initials({ name: 'Ann Lee' })]")
    assert out == ["😀B", "AL"]


def test_a_project_colour_named_like_an_object_property_falls_back_to_zinc(tmp_path):
    out = _run_ts(tmp_path, WEB / "features" / "tasks" / "model.ts",
                  "return ['constructor', '__proto__', 'toString', 'blue'].map((c) => m.projectColor(c))")
    zinc, blue = "oklch(0.6 0.01 286)", "oklch(0.62 0.185 258)"
    assert out == [zinc, zinc, zinc, blue]


def test_a_voice_call_failure_reads_the_message_the_server_sends(tmp_path):
    src = (WEB / "features" / "voice" / "call" / "api.ts").read_text(encoding="utf-8")
    mod = tmp_path / "failure.ts"
    mod.write_text(src[src.index("async function failure"):src.index("/** One exchange")].replace(
        "async function failure", "export async function failure"), encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    out = _run_ts(run, mod, """
        const res = (status, body) => new Response(JSON.stringify(body), { status })
        return [await m.failure(res(413, { error: 'too_large', message: 'audio too long' })),
                await m.failure(res(422, { detail: { message: 'old shape' } })),
                await m.failure(new Response('<html>', { status: 502 }))]""")
    assert out == ["audio too long", "old shape", "HTTP 502"]


def test_a_remote_picture_without_slashes_still_waits_for_a_click(tmp_path):
    """`http:evil.com/p.png` is absolute for a browser on an https page: remote, like `https://…` and `//…`."""
    src = (WEB / "components" / "ui" / "markdown.tsx").read_text(encoding="utf-8")
    rx = re.search(r"^const EXTERNAL = (/.+/i)$", src, re.M)[1]
    mod = tmp_path / "ext.ts"
    mod.write_text(f"export const EXTERNAL = {rx}\n", encoding="utf-8")
    out = _run_ts(tmp_path, mod, """return ['http:evil.com/?d=1', 'HTTPS:evil.com', 'https://evil.com', '//evil.com',
        '/\\\\evil.com', '/sessions', '/api/files/raw?p=a.png', 'img/a.png', '#top'].map((u) => m.EXTERNAL.test(u))""")
    assert out == [True, True, True, True, True, False, False, False, False]


def test_only_the_widget_itself_speaks_to_the_page_that_frames_it(tmp_path):
    """A link in widget.html can load another site INTO the frame (same window, origin 'null'): without the key of
    the mount from the fragment, its messages are ignored and it gets no data."""
    out = _run_ts(tmp_path, WEB / "pages" / "dashboard" / "widgetKey.ts", """const a = m.frameKey(), b = m.frameKey()
        return [/^[0-9a-f]{32}$/.test(a), a !== b, m.ours({loads: 1, hellos: 1}), m.ours({loads: 0, hellos: 1}),
                m.ours({loads: 2, hellos: 1}), m.ours({loads: 1, hellos: 0})]""")
    assert out == [True, True, True, True, False, False]
    src = (WEB / "pages" / "dashboard" / "HtmlWidget.tsx").read_text(encoding="utf-8")
    assert "if (m.key !== key) return" in src and "vars: themeVars(), key }" in src
    assert src.count("ours(seen.current) &&") == 2                 # data and theme
    from maxxing.api.extensions import WIDGET_BRIDGE
    assert "K=String(init.key||'')" in WIDGET_BRIDGE and "post({mx:'hello'})" in WIDGET_BRIDGE
    assert "parent.postMessage(m,'*')" in WIDGET_BRIDGE and WIDGET_BRIDGE.count("parent.postMessage") == 1


def test_a_link_to_a_chat_that_is_gone_keeps_the_team_header():
    """?chat=<gone> (a group left, an old notification): the chat cannot load, the page still has its header (title,
    New chat, and on a phone the button to the list and the menu)."""
    src = (WEB / "features" / "team" / "TeamPage.tsx").read_text(encoding="utf-8")
    assert "const known = !chatId || !team || team.chats.some((c) => c.id === chatId)" in src
    assert "{(!chatId || !known || (isError && !team)) && <PageHeader" in src


def test_a_dictation_cancelled_then_started_again_while_asking_leaves_no_mic_on(tmp_path):
    """start(); cancel(); start(); then the permission comes: one recorder only, the first stream is given back."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    src = (WEB / "features" / "voice" / "recorder.ts").read_text(encoding="utf-8")
    (tmp_path / "rec.ts").write_text(src.replace("from 'react'", "from './react.mjs'").replace("from './mic'", "from './mic.mjs'"))
    (tmp_path / "react.mjs").write_text(
        "export const useState = (v) => [v, () => {}]\nexport const useRef = (v) => ({ current: v })\n"
        "export const useCallback = (f) => f\nexport const useEffect = () => {}\n")
    (tmp_path / "mic.mjs").write_text(
        "export const asks = []\nexport const openMic = () => new Promise((res) => asks.push(res))\n")
    (tmp_path / "main.mjs").write_text("""
import { useRecorder } from './rec.ts'
import { asks } from './mic.mjs'
const recorders = []
globalThis.window = { isSecureContext: true, setInterval: () => 1, clearInterval() {} }
Object.defineProperty(globalThis, 'navigator', { value: { mediaDevices: { getUserMedia() {} } }, configurable: true })
globalThis.MediaRecorder = class { constructor(s) { this.state = 'inactive'; this.stream = s; recorders.push(this) }
  start() { this.state = 'recording' } stop() { this.state = 'inactive'; this.onstop?.() } requestData() {} }
globalThis.requestAnimationFrame = () => 0
globalThis.cancelAnimationFrame = () => {}
const stream = () => { const s = { on: true, getTracks: () => [{ stop: () => { s.on = false } }] }; return s }
const r = useRecorder()
const first = r.start(); r.cancel(); const second = r.start()
const a = stream(), b = stream()
asks[0](a); asks[1](b)
await first; await second
console.log(JSON.stringify({ recorders: recorders.length, firstOn: a.on, secondOn: b.on, records: recorders[0]?.stream === b }))
""")
    r = subprocess.run([node, "--experimental-strip-types", "--no-warnings", "main.mjs"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    if r.returncode and ("strip-types" in r.stderr or "Unknown file extension" in r.stderr):
        pytest.skip("this node cannot strip types")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"recorders": 1, "firstOn": False, "secondOn": True, "records": True}


def test_both_sidebars_dragged_wide_still_leave_the_page_its_room(tmp_path):
    """Sidebars dragged to 440 + 520 px: on a 1024 px window the page kept 48 px. Now it keeps MAIN_MIN (480)."""
    out = _run_ts(tmp_path, WEB / "components" / "shell" / "barWidths.ts", """
        const S = {min: 220, max: 440}, T = {min: 220, max: 520}
        return [1024, 1100, 1280, 1920, 700].map((vw) => {
          const side = Math.min(440, m.sideMax(vw, S, T)), second = Math.min(520, m.secondMax(vw, side, T))
          return [side, second, vw - side - second]
        })""")
    assert out == [[324, 220, 480], [400, 220, 480], [440, 360, 480], [440, 520, 960], [220, 220, 260]]
    for f, call in (("Sidebar.tsx", "sideMax(useViewportWidth(), SIDEBAR_W, SECOND_W)"),
                    ("PageList.tsx", "secondMax(useViewportWidth(), left, SECOND_W)")):
        src = (WEB / "components" / "shell" / f).read_text(encoding="utf-8")
        assert call in src and "max={maxW}" in src, f


def test_a_relative_date_that_is_not_a_number_is_empty_not_a_crash(tmp_path):
    out = _run_ts(tmp_path, WEB / "lib" / "format.ts", """return [undefined, NaN, 'x', null, Infinity].map((v) => m.fmtRelative(v, 'en', 1000))
        .concat([m.fmtRelative(1000 - 7200, 'en', 1000)])""")
    assert out == ["", "", "", "", "", "2 hr. ago"]


def test_a_member_stopped_in_a_group_message_is_not_shown_as_a_recipient(tmp_path):
    src = (WEB / "features" / "agents" / "mentions.tsx").read_text(encoding="utf-8")
    mod = tmp_path / "named.ts"
    mod.write_text(src[src.index("const ALL_WORDS"):src.index("/** A member (null = @all) as a chip")]
                   .replace("export function useMentionMap", "function useMentionMap_")
                   .replace("export type MentionMap = Map<string, AgentGroupMember | null>", "type MentionMap = Map<string, any>")
                   .replace("AgentGroupMember", "any"), encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    out = _run_ts(run, mod, """const bob = { handle: 'bob' }, ann = { handle: 'ann' }
        const map = new Map([['all', null], ['bob', bob], ['ann', ann]])
        return ['stop @Bob', 'stop @bob and @ann, go', '@bob please', 'nonstop @bob'].map((t) => m.namedIn(t, map, [bob, ann]).map((x) => x.handle))""")
    assert out == [[], ["ann"], ["bob"], ["bob"]]


def test_a_quick_add_made_only_of_tokens_is_refused_before_the_server(tmp_path):
    out = _run_ts(tmp_path, WEB / "features" / "tasks" / "model.ts", "return m.parseQuickAdd('#bug ^fri', [], '2026-11-25').title")
    assert out.strip() == ""                               # nothing left for a title
    page = (WEB / "pages" / "tasks" / "index.tsx").read_text(encoding="utf-8")
    add = page[page.index("const addParsed"):page.index("const endOf")]
    assert add.index("if (!p.title.trim())") < add.index("create.mutateAsync") and "tasks.titleRequired" in add
    for form in ("Board.tsx", "Calendar.tsx"):              # a refused add keeps the text, no unhandled rejection
        src = (WEB / "features" / "tasks" / form).read_text(encoding="utf-8")
        assert "await onAdd(text)\n" in src and "} catch {" in src[src.index("await onAdd(text)"):][:200]


def test_the_source_headings_are_the_ones_the_preview_draws(tmp_path):
    src = (WEB / "features" / "files" / "readPos.ts").read_text(encoding="utf-8")
    mod = tmp_path / "headings.ts"
    mod.write_text(src[src.index("export function sourceHeadings"):src.index("/** Heading index + progress")], encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    cases = ["# A\ntext\n\nTitle\n=====\n\n## B",                 # setext headings count
             "Para\nmore\n---\n\n# C",                            # ... on the first line of their paragraph
             "````\n```\n# no\n````\n# yes",                      # a shorter fence does not close a longer one
             "```js\n# no\n```js\n# still no\n```\n# yes",        # nor one with an info text
             "~~~\n# no\n```\n~~~\n# yes",                        # nor one of the other character
             "- a\nb\n---\n# H",                                  # a list's line underlined: a rule
             "***\n---\nP\n==="]                                  # rules are no paragraph
    out = _run_ts(run, mod, f"return {json.dumps(cases)}.map((c) => m.sourceHeadings(c))")
    assert out == [[1, 4, 7], [1, 5], [5], [6], [5], [4], [3]]


def test_the_team_chat_name_keeps_its_room_next_to_the_header_buttons():
    chat = (WEB / "features" / "team" / "Chat.tsx").read_text(encoding="utf-8")
    head = chat[chat.index("function ChatHeader"):]
    assert head.count("min-w-24 flex-1") == 2                 # a dm and a group: never squashed to 0 px
    page = (WEB / "features" / "team" / "TeamPage.tsx").read_text(encoding="utf-8")
    assert "newChat('max-xl:sr-only')" in page and "max-xl:sr-only\">{t('team.toBubble')}" in page


REACT_STUB = """export function useRef(v) { return { current: v } }
export function useEffect(f) { f() }
export function useLayoutEffect(f) { f() }
"""


def _run_ts_stubbed(tmp_path: Path, source: Path, script: str, prelude: str = "", swap: dict | None = None):
    """_run_ts for a module that imports React (a stub running effects at once) or an `@/` module (`swap`: its
    import line -> a replacement); `prelude` runs before the import (globals such as window, localStorage)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    text = source.read_text(encoding="utf-8")
    for old, new in (swap or {}).items():
        assert old in text, old
        text = text.replace(old, new)
    (tmp_path / "node_modules/react").mkdir(parents=True, exist_ok=True)
    (tmp_path / "node_modules/react/package.json").write_text('{"name": "react", "type": "module", "main": "index.js"}')
    (tmp_path / "node_modules/react/index.js").write_text(REACT_STUB)
    (tmp_path / "mod.ts").write_text(text, encoding="utf-8")
    (tmp_path / "pre.mjs").write_text(prelude, encoding="utf-8")
    (tmp_path / "main.mjs").write_text(
        "import './pre.mjs'\nconst load = (q = '') => import('./mod.ts' + q)\nconst m = await load()\n"
        f"console.log(JSON.stringify(await (async () => {{ {script} }})()))\n", encoding="utf-8")
    r = subprocess.run([node, "--experimental-strip-types", "--no-warnings", "main.mjs"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    if r.returncode and ("strip-types" in r.stderr or "Unknown file extension" in r.stderr):
        pytest.skip("this node cannot strip types")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_a_toggle_shortcut_held_down_runs_once(tmp_path):
    out = _run_ts_stubbed(tmp_path, WEB / "commands/shortcuts.ts", """
      const ev = (o) => ({ key: 'p', shiftKey: true, ctrlKey: false, metaKey: false, altKey: false, isComposing: false,
        defaultPrevented: false, repeat: false, target: { tagName: 'BODY', closest: () => null }, preventDefault() {}, ...o })
      let toggled = 0, zoom = 0
      m.useHotkey('shift+p', () => toggled++, { repeat: false })
      m.useHotkey('+', () => zoom++)
      const fire = (e) => globalThis.L.forEach((f) => f(e))
      fire(ev({})); for (let i = 0; i < 7; i++) fire(ev({ repeat: true }))
      fire(ev({ key: '+' })); fire(ev({ key: '+', repeat: true }))
      return [toggled, zoom]""", prelude="globalThis.L = []\nglobalThis.window = { addEventListener: (_, f) => L.push(f), "
                                         "removeEventListener() {} }\n")
    assert out == [1, 2]                                  # zoom keys still repeat


def test_a_row_back_before_its_exit_ends_is_shown_again(tmp_path):
    out = _run_ts_stubbed(tmp_path, WEB / "lib/presence.ts", """
      let cancelled = false
      const el = { inert: false, offsetLeft: 1, offsetTop: 2, offsetWidth: 3, offsetHeight: 4,
        style: { pointerEvents: '', position: 'relative', left: '', top: '', width: '', height: '', margin: '', zIndex: '' },
        animate: () => ({ cancel: () => { cancelled = true } }) }
      m.animateOut(el, 'y')
      const out = { inert: el.inert, position: el.style.position }
      m.animateBack(el)
      return [out, el.inert, el.style.position, el.style.pointerEvents, el.style.width, cancelled]""",
                          prelude="globalThis.window = { matchMedia: () => ({ matches: false }) }\n")
    assert out == [{"inert": True, "position": "absolute"}, False, "relative", "", "", True]


def test_media_positions_of_two_tabs_are_merged_not_erased(tmp_path):
    out = _run_ts_stubbed(tmp_path, WEB / "features/files/mediaMemory.ts", """
      const b = await load('?tab-b')
      m.resumePos('x', 100); b.resumePos('y', 100)            // each tab reads the (empty) key once
      m.setMediaPos('a', 40); await new Promise((r) => setTimeout(r, 1100))
      b.setMediaPos('b', 50); await new Promise((r) => setTimeout(r, 1100))
      m.clearMediaPos('a'); await new Promise((r) => setTimeout(r, 1100))
      return Object.keys(JSON.parse(globalThis.S.get('mx-media-pos'))).sort()""",
                          prelude="const s = new Map()\nglobalThis.S = { get: (k) => s.get(k) ?? null, "
                                  "set: (k, v) => s.set(k, v) }\n",
                          swap={"import { store } from '@/lib/utils'": "const store = globalThis.S"})
    assert out == ["b"]                                   # b's position kept, the one cleared in a stays cleared


def test_a_long_pasted_quick_add_normalizes_each_project_name_once(tmp_path):
    """The quick add is parsed at every key: the project names are normalized once per parse, not per @word."""
    out = _run_ts(tmp_path, WEB / "features" / "tasks" / "model.ts", """let reads = 0
        const projects = Array.from({ length: 30 }, (_, i) => {
          const p = { id: 'p' + i }
          Object.defineProperty(p, 'name', { get: () => { reads++; return 'Project ' + i } })
          return p
        })
        const r = m.parseQuickAdd('@ab '.repeat(25000) + '@project-7 x', projects, '2026-11-25')
        return [reads, r.project_id, r.title.length]""")
    assert out[0] <= 60 and out[1] == "p7" and out[2] == len("@ab " * 25000 + "x")


def test_the_spreadsheet_filter_follows_a_deferred_query_on_precomputed_rows():
    """The Filter field of a sheet: rows lowered once per sheet, the table filtered on a deferred value (not at each key)."""
    src = (WEB / "features" / "files" / "docs.tsx").read_text(encoding="utf-8")
    view = src[src.index("function SheetsView"):src.index("const open = (i: number)")]
    assert "React.useDeferredValue(q)" in view and "[rows, query])" in view
    assert "lows.current?.rows !== rows" in view and "c.toLowerCase()" not in view


def test_plain_text_trims_stay_linear_on_long_runs_of_blanks(tmp_path):
    """« Copy as plain text » on a file with a long run of spaces or empty lines that is not at its end: no freeze."""
    out = _html_to_text(tmp_path, "return h('body', {}, h('pre', {}, ' '.repeat(100000)), h('p', {}, 'end'))", """
        const t0 = Date.now()
        const blanks = ' '.repeat(100000), lines = '\\n'.repeat(100000)
        const r = [edges('a' + blanks + 'b  '), oneLine('a' + blanks + 'b\\n  \\n c'), cutEnd('x' + blanks + 'y' + blanks, (c) => c === ' '),
                   endBreaks('a' + lines + 'b' + lines).toString(), run()]
        return [r[0].length, r[1].slice(-5), r[2].length, r[3], r[4].trim(), Date.now() - t0 < 3000]""")
    assert out == [100002, "  b c"[-5:], 100002, "100000", "end", True]


def _md_light(tmp_path: Path, body: str):
    src = (WEB / "features" / "files" / "plainText.ts").read_text(encoding="utf-8")
    part = src[src.index("// Trims written as loops"):src.index("/** Above this size")] + \
        src[src.index("/** A longer line"):src.index("const mdBlocks")]
    (tmp_path / "main.ts").write_text(part + f"\nconsole.log(JSON.stringify((() => {{ {body} }})()))\n", encoding="utf-8")
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, "--experimental-strip-types", "--no-warnings", "main.ts"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)
    if r.returncode and ("strip-types" in r.stderr or "Unknown file extension" in r.stderr):
        pytest.skip("this node cannot strip types")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_a_big_markdown_is_made_plain_without_the_parser(tmp_path):
    """Over MD_PARSE_MAX characters, « Copy as plain text » takes the marks off line by line: 2 MB in well under a second."""
    src = (WEB / "features" / "files" / "plainText.ts").read_text(encoding="utf-8")
    fn = src[src.index("export function markdownToText("):src.index("/** A longer line")]
    assert "if (md.length > MD_PARSE_MAX) return markdownToTextLight(md)" in fn
    out = _md_light(tmp_path, """
        const small = markdownToTextLight('# Title\\r\\n\\n> **bold** and *it* `code` ~~gone~~\\n* item [x](https://a.b) [y](y) ![pic](p.png)\\n```\\n# kept\\n```\\n---\\n')
        const t0 = Date.now()
        const big = markdownToTextLight('Hello **world** [x](https://a.b) é\\r\\n\\r\\n'.repeat(50000))
        return [small, big.split('\\n')[0], Date.now() - t0 < 1500]""")
    assert out == ["Title\n\nbold and it code gone\n- item x (https://a.b) y pic\n# kept", "Hello world x (https://a.b) é", True]


def test_a_live_batch_of_text_does_not_copy_the_tool_index_nor_the_hidden_messages():
    """fold() runs for every live batch: the tool index and the hidden messages are copied only by a batch that
    changes them (once), not by each batch (its cost grew with the whole history loaded)."""
    src = (WEB / "pages" / "sessions" / "log.ts").read_text(encoding="utf-8")
    fold = src[src.index("function fold("):src.index("return { ...st, items, toolIdx")]
    assert "{ ...st.toolIdx }" not in fold and "hidden = { ...hidden, [" not in fold
    assert fold.count("if (!ownIdx) {") == 1 and fold.count("if (!ownHidden) {") == 1
    use = fold[fold.index("case 'tool_use':"):fold.index("case 'tool_result':")]
    assert use.index("toolIdx = { ...toolIdx }") < use.index("toolIdx[ev.id] = items.length")


def test_the_space_office_pauses_what_cannot_be_seen():
    """Each desk runs about ten endless animations: a bay far from the screen pauses them, and past CALM_ABOVE agents
    only the desks of agents at work or waiting keep theirs."""
    src = (WEB / "features" / "agents" / "OfficeFuture.tsx").read_text(encoding="utf-8")
    bay = src[src.index("function Bay("):src.index("<DropBar side={dnd.side} vertical={false} />")]
    assert "const away = useAway(ref)" in bay and "ref={ref}" in bay and "away && 'mx-wait'" in bay
    desk = src[src.index("function Console("):src.index('data-testid="office-desk"')]
    assert "calm && !working && st.id !== 'waiting' && 'mx-wait'" in desk
    assert "> CALM_ABOVE" in src and "calm={calm}" in src
    css = (WEB / "styles" / "globals.css").read_text(encoding="utf-8")
    assert ".mx-wait, .mx-wait * { animation-play-state: paused !important; }" in css
def test_the_demo_server_knows_the_phone_notifications(tmp_path):
    """The demo server (screenshots, UI checks): a phone registered, `push` kept at creation and by PATCH (with
    favorite and effort), so the per-session switch shows as on the real server."""
    import socket
    import time
    import urllib.request
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    env = {**os.environ, "MOCK_PORT": str(port), "MOCK_DIST": str(tmp_path)}
    proc = subprocess.Popen([node, str(WEB.parent / "mock" / "server.mjs")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def call(method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Maxxing": "1"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    try:
        for _ in range(100):
            try:
                devices = call("GET", "/api/push/devices")
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("the demo server did not start")
        assert len(devices) == 1
        topic = call("GET", "/api/sessions")[0]["path"]
        s = call("POST", "/api/sessions", {"path": topic, "push": False})
        assert s["push"] is False
        s = call("PATCH", f"/api/sessions/{s['id']}", {"push": True, "favorite": True, "effort": "high"})
        assert s["push"] is True and s["favorite"] is True and s["effort"] == "high"
    finally:
        proc.terminate()
        proc.wait(5)
