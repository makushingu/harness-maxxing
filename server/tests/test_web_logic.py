"""Pure helpers of the interface, run by Node on their TypeScript source (skipped without a Node that strips types)."""
from __future__ import annotations

import json
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
    part = src[src.index("const HTML_SKIP"):src.index("/** Cells separated by tabs")]
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
const edges = (s: string) => s.replace(/^\\n+|\\s+$/g, '')
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
