"""Pure helpers of the interface, run by Node on their TypeScript source (skipped without a Node that strips types)."""
from __future__ import annotations

import json
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
