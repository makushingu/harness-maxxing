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
