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
