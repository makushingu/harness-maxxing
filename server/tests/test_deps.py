"""External components (deps.toml, deps.py, `maxxing deps`, install.sh's `dep` / `fetch_verified`): the manifest is
complete and read the same way by both, downloads are checked before use, updates go side by side and keep the old
version when the new one fails, verify finds files another user could replace, clean / remove / uninstall leave
nothing behind, the weekly jobs exist. Nothing here touches the real system (conftest: _never_the_real_tools)."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import threading
import tomllib
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from maxxing import cli, cmd_core, config, deps

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "install.sh"


def sh(snippet: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", f'MAXXING_INSTALL_LIB=1 source "{INSTALL}"; set +e; {snippet}'],
                          capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin", **env})


@pytest.fixture
def st(tmp_path, monkeypatch):
    state = tmp_path / "state"
    (state / "tools").mkdir(parents=True)
    monkeypatch.setattr(config, "STATE", state)
    monkeypatch.setenv("MAXXING_STATE", str(state))
    deps.LINK_DIR.mkdir(parents=True, exist_ok=True)
    (tmp_path / "sysbin").mkdir()
    monkeypatch.setattr(deps, "SYSTEM_PATH", (str(deps.LINK_DIR), str(tmp_path / "sysbin")))   # no Node of the box
    return state


# ---- the manifest ----------------------------------------------------------------------------------------------
def test_manifest_pins_every_download_for_both_machines():
    comps = deps.load()
    assert {"uv", "python", "node", "claude", "caddy", "scrapling", "chromium", "remotion", "whisper", "garage"} <= set(comps)
    for name, c in comps.items():
        assert c.get("title") and c.get("path") and c.get("update") in ("auto", "self", "apt", "manual"), name
        assert c.get("remove"), name
        if "url" in c and name != "garage":
            assert c["url"].startswith("https://"), name
            for m in ("x86_64", "aarch64"):
                assert re.fullmatch(r"[0-9a-f]{64}", deps.sha_of(c, m)), (name, m)
                assert deps.url_of(c, m).startswith("https://") and "{" not in deps.url_of(c, m)
        if "lock" in c:
            assert deps.lock_path(c).is_file(), name
    assert re.fullmatch(r"[0-9A-F]{40}", comps["caddy"]["key_fingerprint"])
    assert all(re.fullmatch(r"[0-9a-f]{40}", r) for r in comps["whisper"]["revisions"].values())


def test_scrapling_lock_pins_every_package_with_a_hash():
    c = deps.get("scrapling")
    text = deps.lock_path(c).read_text()
    pins = deps.requirement_pins(deps.lock_path(c))
    assert ("scrapling", c["version"]) in pins and len(pins) > 10
    for block in re.split(r"\n(?=[A-Za-z0-9])", text.split("\n", 2)[2]):
        assert "--hash=sha256:" in block, block[:60]


def test_no_download_is_piped_into_a_shell_anywhere():
    """The dev's remark: no `curl | sh` of a third-party script, in the installer, scripts, server code or skills."""
    pat = re.compile(r"(curl|wget)[^\n|]*\|\s*(sudo\s+)?(\S+=\S+\s+)*(ba)?sh\b")
    files = [INSTALL, *ROOT.joinpath("scripts").glob("*.sh"), *ROOT.joinpath("server/maxxing").rglob("*.py"),
             *ROOT.joinpath("skills").rglob("*.md"), *ROOT.joinpath("templates").rglob("*.md")]
    bad = []
    for f in files:
        for i, ln in enumerate(f.read_text(errors="ignore").splitlines(), 1):
            if pat.search(ln) and "get.harness-maxxing.com" not in ln:      # our own signed installer
                bad.append(f"{f.relative_to(ROOT)}:{i}: {ln.strip()[:80]}")
    assert not bad, bad
    text = INSTALL.read_text()
    assert "claude.ai/install.sh" not in text and "astral.sh/uv/install" not in text
    assert not re.search(r"^(UV|NODE)_(VERSION|SHA256)", text, re.M)    # pins live in deps.toml only


def test_node_pin_satisfies_every_lockfile_floor():
    """F15: the lockfiles ask for Node.js >= 22.22.0 (react-router); a major-only check accepted 20.x."""
    floor = deps.node_required()
    assert floor >= (22, 22, 0)
    assert deps.vtuple(deps.get("node")["version"]) >= floor


# ---- fetch_verified --------------------------------------------------------------------------------------------
def test_server_fetch_verified_refuses_plain_http_and_bad_checksums(tmp_path, monkeypatch):
    with pytest.raises(deps.DepError, match="not HTTPS"):
        deps.fetch_verified("http://example.com/x", "0" * 64, tmp_path / "x")

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=60: Resp(b"payload"))
    with pytest.raises(deps.DepError, match="checksum mismatch"):
        deps.fetch_verified("https://example.com/x", "0" * 64, tmp_path / "x")
    assert not (tmp_path / "x").exists() and not (tmp_path / "x.part").exists()
    out = deps.fetch_verified("https://example.com/x", hashlib.sha256(b"payload").hexdigest(), tmp_path / "x")
    assert out.read_bytes() == b"payload"


def test_work_dir_is_private_under_the_state_and_removed(st):
    with deps.work_dir() as w:
        assert w.is_relative_to(st / "tmp") and (os.stat(st / "tmp").st_mode & 0o777) == 0o700
        (w / "f").write_text("x")
    assert not w.exists()


# ---- node: side by side, switch, rollback, legacy cleanup -------------------------------------------------------
def _node_tarball(version: str, broken: bool = False) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        script = b"#!/bin/sh\necho v" + version.encode() + b"\n" if not broken else b"#!/bin/sh\nexit 3\n"
        for name, data, mode in ((f"node-v{version}/bin/node", script, 0o755),
                                 (f"node-v{version}/bin/npm", b"#!/bin/sh\n", 0o755),
                                 (f"node-v{version}/lib/node_modules/npm/x.js", b"", 0o644)):
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode, ti.uid, ti.gid = len(data), mode, 1000, 1000      # like nodejs.org's tarballs
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def _fake_fetch(payload: bytes):
    def fetch(url, sha, dest, timeout=600):
        dest.write_bytes(payload)
        return dest
    return fetch


def test_node_update_side_by_side_links_and_legacy(st, monkeypatch, tmp_path):
    c = deps.get("node")
    v = c["version"]
    legacy = tmp_path / "usrlocal"                     # Node.js an older installer extracted into "/usr/local"
    (legacy / "bin").mkdir(parents=True)
    (legacy / "bin" / "node").write_text("old")
    (legacy / "lib/node_modules/npm").mkdir(parents=True)
    (st / "install-manifest").write_text(f"node {legacy}\nufw enabled\n")
    monkeypatch.setattr(deps, "LINK_DIR", legacy / "bin")
    monkeypatch.setattr(deps, "fetch_verified", _fake_fetch(_node_tarball(v)))
    monkeypatch.setattr(deps, "node_required", lambda: (0, 0, 0))
    res, text = deps._up_node(c)
    assert res in ("installed", "updated"), text
    final = st / "tools" / "nodejs" / v
    assert (st / "tools/nodejs/current").resolve() == final.resolve()
    assert all(p.lstat().st_uid == os.getuid() for p in final.rglob("*"))    # never the tarball's uid 1000
    link = legacy / "bin" / "node"
    assert link.is_symlink() and os.readlink(link).endswith("nodejs/current/bin/node")
    assert not (legacy / "lib/node_modules/npm").exists()
    assert (st / "install-manifest").read_text() == "ufw enabled\n"
    assert deps.installed("node")["version"] == v and deps._up_node(c)[0] == "ok"


def test_node_update_that_does_not_run_keeps_the_old_one(st, monkeypatch):
    c = deps.get("node")
    old = st / "tools/nodejs/20.0.0"
    (old / "bin").mkdir(parents=True)
    (old / "bin" / "node").write_text("#!/bin/sh\necho v20.0.0\n")
    deps._symlink(old, st / "tools/nodejs/current")
    monkeypatch.setattr(deps, "fetch_verified", _fake_fetch(_node_tarball(c["version"], broken=True)))
    with pytest.raises(deps.DepError, match="does not run"):
        deps._up_node(c)
    assert (st / "tools/nodejs/current").resolve() == old.resolve()
    assert not list((st / "tools/nodejs").glob(".*.new"))


def test_uv_update_checks_the_new_binary_and_records_it(st, monkeypatch):
    c = deps.get("uv")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for n in ("uv", "uvx"):
            data = f"#!/bin/sh\necho 'uv {c['version']} (test)'\n".encode()
            ti = tarfile.TarInfo(f"uv-x/{n}"); ti.size, ti.mode = len(data), 0o755
            tf.addfile(ti, io.BytesIO(data))
    monkeypatch.setattr(deps, "fetch_verified", _fake_fetch(buf.getvalue()))
    assert deps._up_uv(c)[0] in ("installed", "updated")
    assert deps.installed("uv")["version"] == c["version"]
    assert [r["level"] for r in deps.verify(["uv"])] == ["ok"]
    (deps.LINK_DIR / "uv").write_text("#!/bin/sh\necho 'uv 0.13.1'\n# swapped\n")
    assert "changed since it was installed" in deps.verify(["uv"])[0]["text"]


# ---- verify: owners --------------------------------------------------------------------------------------------
@pytest.mark.skipif(os.geteuid() != 0, reason="chown needs root")
def test_verify_finds_files_another_user_could_replace(st):
    d = st / "tools/nodejs/22.0.0/bin"
    d.mkdir(parents=True)
    (d / "node").write_text("#!/bin/sh\necho v22.0.0\n")
    (d / "node").chmod(0o755)
    deps._symlink(d.parent, st / "tools/nodejs/current")
    assert deps.verify(["node"])[0]["level"] == "ok"
    try:
        os.chown(d / "node", 1000, 1000)
    except PermissionError:                          # root without CAP_CHOWN (a sandbox)
        pytest.skip("chown not permitted here")
    r = deps.verify(["node"])[0]
    assert r["level"] == "fail" and "not owned by root" in r["text"]
    os.chown(d / "node", 0, 0)
    (d / "node").chmod(0o777)
    assert deps.verify(["node"])[0]["level"] == "fail"
    assert cmd_core.check_managed_deps()["level"] == cmd_core.FAIL


# ---- remove, clean ---------------------------------------------------------------------------------------------
def test_remove_lists_and_refuses_essentials(st, capsys):
    rem = st / "tools/remotion/node_modules"
    rem.mkdir(parents=True)
    with pytest.raises(deps.DepError, match="needed by Harness Maxxing"):
        deps.remove("python")
    assert cli.main(["deps", "remove", "remotion"]) == 0
    assert not (st / "tools/remotion").exists()
    assert cli.main(["deps", "remove", "uv"]) == 1 and "needed" in capsys.readouterr().err


def test_clean_drops_old_versions_orphans_caches_and_big_logs(st, monkeypatch):
    home = deps.root_home()
    (home / ".cache/uv/x").mkdir(parents=True)
    (home / ".cache/uv/x/blob").write_bytes(b"0" * 1000)
    (home / ".npm/_cacache").mkdir(parents=True)
    nd = st / "tools/nodejs"
    for v in ("22.1.0", "22.2.0"):
        (nd / v / "bin").mkdir(parents=True)
    deps._symlink(nd / "22.2.0", nd / "current")
    br = st / "tools/browsers"
    for name in ("chromium-1200", "chromium-1243", "chromium_headless_shell-1243", "ffmpeg-1011"):
        (br / name).mkdir(parents=True)
    monkeypatch.setattr(deps, "playwright_revisions", lambda py=None: {"playwright": "1243"})
    (st / "tools/remotion.new").mkdir()
    (st / "tmp/old").mkdir(parents=True)
    os.utime(st / "tmp/old", (1, 1))
    (st / "logs").mkdir()
    (st / "logs/server.log").write_bytes(b"a" * (deps.LOG_MAX + 10))
    dry = deps.clean(dry=True)
    assert (nd / "22.1.0").exists() and dry
    assert (home / ".cache/uv").exists() and not any(Path(x["path"]).name == "uv" for x in deps.clean(dry=True))
    out = {Path(x["path"]).name for x in deps.clean(caches=True)}
    assert {"uv", "_cacache", "22.1.0", "chromium-1200", "chromium_headless_shell-1243", "remotion.new", "server.log", "old"} <= out
    assert (nd / "22.2.0").exists() and (br / "chromium-1243").exists() and (br / "ffmpeg-1011").exists()
    assert (st / "logs/server.log").stat().st_size == deps.LOG_KEEP


# ---- check (OSV) -----------------------------------------------------------------------------------------------
def test_check_notifies_once_per_advisory_set(mx, monkeypatch):
    from maxxing import depcheck, feed
    monkeypatch.setattr(depcheck, "osv_scan", lambda timeout=30: {"checked": 3, "vulnerable": []})
    monkeypatch.setattr(deps, "installed", lambda n: {"version": "0.13.1" if n == "uv" else None, "where": "",
                                                      "managed": True, "detail": ""})

    def post(url, body, timeout=30):
        return {"results": [{"vulns": [{"id": "GHSA-test"}]} if q["package"]["name"] == "uv" else {}
                            for q in body["queries"]]}
    monkeypatch.setattr(depcheck, "_post_json", post)
    r = deps.check()
    assert [v["name"] for v in r["vulnerable"]] == ["uv"] and r["checked"] > 3
    assert deps.notify_vulnerable(r) and not deps.notify_vulnerable(r)       # once per set of advisories
    evs = [e for e in feed.list_events()["events"] if "vulnerab" in e["title"]]
    assert len(evs) == 1 and "GHSA-test" in evs[0]["body"]


def test_default_jobs_include_weekly_clean_and_check():
    jobs = dict(cmd_core.default_jobs())
    assert jobs["deps-clean"]["command"].endswith("deps clean --quiet") and jobs["deps-clean"]["enabled"]
    assert jobs["deps-check"]["command"].endswith("deps check --notify") and jobs["deps-check"]["notify"] == "never"


# ---- CLI, doctor -----------------------------------------------------------------------------------------------
def test_cli_list_json_and_exit_code(st, capsys):
    rc = cli.main(["deps", "list", "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert rc == 0 and {r["name"] for r in rows} >= {"uv", "node", "chromium"}
    assert cli.main(["deps", "list"]) == 1                          # nothing installed in this state: missing


def test_python_m_maxxing_returns_the_exit_code(tmp_path):
    r = subprocess.run([os.sys.executable, "-m", "maxxing", "deps", "nope"], capture_output=True, text=True,
                       timeout=60, env={**os.environ, "MAXXING_STATE": str(tmp_path)})
    assert r.returncode == 2


# ---- tools paths: one Chromium ---------------------------------------------------------------------------------
def test_one_chromium_for_pdfs_and_remotion(st, monkeypatch):
    from maxxing import cmd_video
    exe = st / "tools/browsers/chromium-1243/chrome-linux64/chrome"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr(deps, "playwright_revisions", lambda py=None: {"playwright": "1243"})
    assert cmd_video.browser() == exe
    cfg = (ROOT / "templates/remotion/remotion.config.js").read_text()
    assert "setBrowserExecutable" in cfg and "chrome-for-testing" in cfg


def test_session_path_has_the_managed_node(st, monkeypatch, tmp_path):
    from maxxing.sessions import spawn
    (st / "tools/nodejs/current/bin").mkdir(parents=True)
    if shutil.which("node", path="/usr/local/bin"):
        pytest.skip("this box has a Node.js in /usr/local/bin")
    monkeypatch.setenv("PATH", str(tmp_path / "sysbin"))             # a server without Node.js
    monkeypatch.setenv("HOME", str(tmp_path))
    assert str(st / "tools/nodejs/current/bin") in spawn.base_env()["PATH"].split(":")


def test_session_path_keeps_the_node_the_server_has(st, monkeypatch, tmp_path):
    """Adapted at integration: a turn administering the server uses the server's Node.js, not ours."""
    from maxxing.sessions import spawn
    (st / "tools/nodejs/current/bin").mkdir(parents=True)
    sysbin = tmp_path / "sysbin"
    (sysbin / "node").write_text("#!/bin/sh\n")
    (sysbin / "node").chmod(0o755)
    monkeypatch.setenv("PATH", str(sysbin))
    assert str(st / "tools/nodejs/current/bin") not in spawn.base_env()["PATH"].split(":")


# ---- uninstall -------------------------------------------------------------------------------------------------
def test_uninstall_purge_removes_what_the_manifest_lists(st, tmp_path, monkeypatch):
    monkeypatch.setattr(cmd_core, "systemctl", lambda *a, timeout=60: (0, ""))
    calls = []
    monkeypatch.setattr(cmd_core, "run", lambda cmd, **kw: (calls.append(cmd), (0, ""))[1])
    for f in ("scrapling", "scrapling-python"):
        (deps.LINK_DIR / f).write_text("#!/bin/bash\n# Harness Maxxing wrapper: x\n")
    (deps.LINK_DIR / "rg").write_text("not ours")
    (st / "tools/nodejs/22.0.0/bin").mkdir(parents=True)
    deps._symlink(st / "tools/nodejs/22.0.0", st / "tools/nodejs/current")
    deps._symlink(st / "tools/nodejs/current/bin/node", deps.LINK_DIR / "node")
    (deps.LINK_DIR / "uv").write_text("uv")
    deps.write_record("uv", {"version": "x", "files": {}})
    cmd_core.F2B_JAIL.parent.mkdir(parents=True)
    cmd_core.F2B_JAIL.write_text("[sshd]\n")
    cmd_core.FSTAB.write_text("UUID=1 / ext4 defaults 0 1\n/swapfile none swap sw 0 0\n")
    (st / "install-manifest").write_text(f"swapfile {tmp_path / 'swapfile'}\n")
    (tmp_path / "swapfile").write_bytes(b"0")
    cmd_core.FSTAB.write_text(f"UUID=1 / ext4 defaults 0 1\n{tmp_path / 'swapfile'} none swap sw 0 0\n")
    cmd_core._uninstall_components((st / "install-manifest").read_text().splitlines(), purge=True)
    left = sorted(p.name for p in deps.LINK_DIR.iterdir())
    assert left == ["rg"], left
    assert not (st / "tools/nodejs").exists() and not cmd_core.F2B_JAIL.exists()
    assert cmd_core.FSTAB.read_text() == "UUID=1 / ext4 defaults 0 1\n" and not (tmp_path / "swapfile").exists()
    assert ["swapoff", str(tmp_path / "swapfile")] in calls


def test_python_update_finds_the_newest_managed_build(st, monkeypatch):
    root = st / "tools/python"
    for v in ("3.12.9", "3.12.15"):
        b = root / f"cpython-{v}-linux-x86_64-gnu/bin/python3.12"
        b.parent.mkdir(parents=True)
        b.write_text("")
    (deps.LINK_DIR / "uv").write_text("")
    monkeypatch.setattr(deps, "_run", lambda cmd, **kw: (0, ""))
    monkeypatch.setattr(deps, "installed", lambda n: {"version": "3.12", "where": "", "managed": False, "detail": ""})
    seen = []
    monkeypatch.setattr(deps, "_sync_venv", lambda uv, py, env: seen.append(py) or True)
    assert deps._up_python(deps.get("python"), explicit=True)[0] == "updated"
    assert seen == [str(root / "cpython-3.12.15-linux-x86_64-gnu/bin/python3.12")]


def test_python_move_that_fails_puts_back_the_exact_venv(st, monkeypatch):
    root = st / "tools/python"
    b = root / "cpython-3.12.15-linux-x86_64-gnu/bin/python3.12"
    b.parent.mkdir(parents=True)
    b.write_text("")
    (deps.LINK_DIR / "uv").write_text("")
    venv = st / "code/server/.venv"
    monkeypatch.setattr(deps, "_venv_python", lambda: venv / "bin/python")
    (venv / "bin").mkdir(parents=True)
    (venv / "bin/python").symlink_to("/usr/bin/python3")
    (venv / "marker").write_text("old venv")
    monkeypatch.setattr(deps, "_run", lambda cmd, **kw: (0, ""))
    monkeypatch.setattr(deps, "installed", lambda n: {"version": "3.12", "where": "/usr/bin/python3", "managed": False,
                                                     "detail": ""})

    def broken_sync(uv, py, env):                    # uv removed the old venv, then the install failed
        shutil.rmtree(venv)
        venv.mkdir()
        return False
    monkeypatch.setattr(deps, "_sync_venv", broken_sync)
    with pytest.raises(deps.DepError):
        deps._up_python(deps.get("python"), explicit=True)
    assert (venv / "marker").read_text() == "old venv"
    assert os.readlink(venv / "bin/python") == "/usr/bin/python3"
    assert not venv.with_name(".venv.pre-python").exists()


# ---- adapted at integration (2.0.0a70): a server already in use keeps its own tools ----------------------------
def test_node_links_never_shadow_a_node_the_server_has(st, monkeypatch, tmp_path):
    """/usr/local/bin comes before /usr/bin: a link there would move every program of the server onto our Node."""
    c = deps.get("node")
    sysbin = tmp_path / "sysbin"
    (sysbin / "node").write_text("#!/bin/sh\necho v18.0.0\n")
    (sysbin / "node").chmod(0o755)
    monkeypatch.setattr(deps, "fetch_verified", _fake_fetch(_node_tarball(c["version"])))
    monkeypatch.setattr(deps, "node_required", lambda: (0, 0, 0))
    assert deps._up_node(c)[0] in ("installed", "updated")
    assert not os.path.lexists(deps.LINK_DIR / "node")           # the server's Node.js stays the one on PATH
    assert os.path.islink(deps.LINK_DIR / "npm")                 # nothing else named npm: linked
    assert deps.node_bin() == st / "tools/nodejs/current/bin/node"   # Harness Maxxing still uses its own


def test_auto_update_keeps_a_uv_that_is_not_ours(st, monkeypatch):
    (deps.LINK_DIR / "uv").write_text("#!/bin/sh\necho 'uv 0.9.0'\n")
    (deps.LINK_DIR / "uv").chmod(0o755)
    monkeypatch.setattr(deps, "fetch_verified", lambda *a, **k: pytest.fail("downloaded"))
    res, text = deps._up_uv(deps.get("uv"))
    assert res == "skipped" and "not ours" in text
    assert "0.9.0" in (deps.LINK_DIR / "uv").read_text()


def test_auto_update_keeps_a_working_venv_in_place(st, monkeypatch):
    """`maxxing update` (--auto) never rebuilds the server venv while the service and the crons use it."""
    monkeypatch.setattr(deps, "installed", lambda n: {"version": "3.12", "where": "/usr/bin/python3.12",
                                                     "managed": False, "detail": ""})
    monkeypatch.setattr(deps, "_run", lambda *a, **k: pytest.fail("ran " + str(a[0])))
    monkeypatch.setattr(deps, "_sync_venv", lambda *a: pytest.fail("venv rebuilt"))
    res, text = deps._up_python(deps.get("python"))
    assert res == "ok" and "kept" in text
    assert [r["result"] for r in deps.update(["python"], log=lambda s: None, explicit=False)] == ["ok"]


def test_verify_rehashes_only_changed_files_and_doctor_asks_versions_once(st, tmp_path, monkeypatch):
    f = tmp_path / "tool.bin"
    f.write_bytes(b"A" * 1000)
    deps.write_record("uv", {"version": "1", "files": {str(f): deps.file_sha(f)}})
    monkeypatch.setattr(deps, "owned_paths", lambda name: [])
    asked = {"n": 0}

    def fake_installed(name):
        asked["n"] += 1
        return {"version": "1" if name == "uv" else None, "where": "", "managed": True, "detail": ""}
    monkeypatch.setattr(deps, "installed", fake_installed)
    hashed = {"n": 0}
    real = deps.file_sha

    def counting(p):
        hashed["n"] += 1
        return real(p)
    monkeypatch.setattr(deps, "file_sha", counting)
    assert [r["level"] for r in deps.verify(["uv"])] == ["ok"]
    assert [r["level"] for r in deps.verify(["uv"])] == ["ok"]
    assert hashed["n"] == 1                                     # unchanged: the second check reuses the hash
    assert [r["level"] for r in deps.verify(["uv"], fresh=True)] == ["ok"]
    assert hashed["n"] == 2                                     # `maxxing deps verify`: hashed again, no cache
    m = f.stat().st_mtime_ns
    f.write_bytes(b"B" * 1000)                                  # same size, mtime put back: ctime still moves
    os.utime(f, ns=(m, m))
    assert [r["level"] for r in deps.verify(["uv"])] == ["fail"]
    asked["n"] = 0
    cmd_core.check_managed_deps()
    assert asked["n"] == len(deps.load())                        # doctor: one `installed()` per component
