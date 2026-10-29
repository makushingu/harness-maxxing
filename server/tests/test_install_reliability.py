"""install.sh (2.0.0a70): it reads deps.toml like the server, downloads only through fetch_verified, installs from a
local copy, one apt pass skipped on re-runs, swap on small servers, local voice refused under 3 GB without a yes, a
memory cap on the web service, validated inputs. install.sh is sourced with MAXXING_INSTALL_LIB=1 (definitions
only) in a bash subprocess: nothing on this machine is changed."""
from __future__ import annotations

import hashlib
import subprocess
import threading
import tomllib
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from maxxing import deps

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "install.sh"


def sh(snippet: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", f'MAXXING_INSTALL_LIB=1 source "{INSTALL}"; set +e; {snippet}'],
                          capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin", **env})


def test_installer_reads_the_manifest_like_the_server():
    """install.sh's small reader (python3 of the OS, maybe 3.10: no tomllib) must agree with tomllib on every value."""
    data = tomllib.loads(deps.MANIFEST.read_text())
    script, expect = [], []
    for name, c in data.items():
        if not isinstance(c, dict):
            continue
        for k, v in c.items():
            if isinstance(v, str):
                script.append(f'dep {name} {k}'); expect.append(v)
            elif isinstance(v, list):
                script.append(f'dep {name} {k} | paste -sd "|"'); expect.append("|".join(v))
            elif isinstance(v, dict):
                for sub, x in v.items():
                    script.append(f'dep {name} {k} {sub}'); expect.append(x)
    root = ROOT
    r = sh(f'INSTALL_DIR={root}; ' + "; ".join(script))
    assert r.stdout.splitlines() == expect, r.stderr
    assert sh(f'INSTALL_DIR={root}; dep uv nope || echo missing').stdout.strip() == "missing"
    r = sh(f'INSTALL_DIR={root}; dep_url node', )
    assert r.stdout.startswith("https://nodejs.org/dist/v") and "{" not in r.stdout


@pytest.fixture
def http_dir(tmp_path):
    d = tmp_path / "www"
    d.mkdir()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(d)))
    srv.RequestHandlerClass.log_message = lambda *a: None
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield d, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_installer_fetch_verified_checks_before_use(http_dir, tmp_path):
    d, base = http_dir
    (d / "tool").write_bytes(b"good build")
    good = hashlib.sha256(b"good build").hexdigest()
    dest = tmp_path / "work" / "tool"
    dest.parent.mkdir()
    r = sh(f'fetch_verified {base}/tool {good} {dest} && echo fetched')
    assert "fetched" in r.stdout and dest.read_bytes() == b"good build"
    dest.unlink()
    r = sh(f'fetch_verified {base}/tool {"0" * 64} {dest} || echo refused')
    assert "refused" in r.stdout and "checksum mismatch" in r.stdout
    assert not dest.exists() and not (tmp_path / "work" / "tool.part").exists()
    r = sh(f'fetch_verified http://example.com/tool {good} {dest} || echo refused')
    assert "refused" in r.stdout and "not HTTPS" in r.stdout
    r = sh(f'fetch_verified {base}/tool nothex {dest} || echo refused')
    assert "refused" in r.stdout and not dest.exists()


def test_downloads_are_kept_for_a_re_run(http_dir, tmp_path):
    """A failed install run again does not download again: verified files stay in CACHE_DIR (named by their
    sha256, checked on every use) until cache_clear, after a successful install."""
    d, base = http_dir
    (d / "tool").write_bytes(b"good build")
    good = hashlib.sha256(b"good build").hexdigest()
    cache, work = tmp_path / "cache", tmp_path / "work"
    work.mkdir()
    r = sh(f'fetch_verified {base}/tool {good} {work}/a && echo fetched', CACHE_DIR=str(cache))
    assert "fetched" in r.stdout and (cache / good).read_bytes() == b"good build", r.stdout + r.stderr
    (d / "tool").unlink()                                           # the network is gone: the cache serves it
    r = sh(f'fetch_verified {base}/tool {good} {work}/b && echo fetched', CACHE_DIR=str(cache))
    assert "fetched" in r.stdout and (work / "b").read_bytes() == b"good build"
    (cache / good).write_bytes(b"tampered")                         # never used without its sha256
    r = sh(f'fetch_verified {base}/tool {good} {work}/c || echo refused', CACHE_DIR=str(cache))
    assert "refused" in r.stdout and not (cache / good).exists() and not (work / "c").exists()
    (d / "tool").write_bytes(b"good build")                         # a cut transfer left a .part: still a good file
    (cache / f"{good}.part").write_bytes(b"garbage")
    r = sh(f'fetch_verified {base}/tool {good} {work}/d && echo fetched', CACHE_DIR=str(cache))
    assert "fetched" in r.stdout and (work / "d").read_bytes() == b"good build"
    assert not (cache / f"{good}.part").exists()
    (cache / "mine.txt").write_text("not ours")
    sh('cache_clear', CACHE_DIR=str(cache))
    assert [p.name for p in cache.iterdir()] == ["mine.txt"]
    (cache / "mine.txt").unlink()
    sh('cache_clear', CACHE_DIR=str(cache))
    assert not cache.exists()
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "elsewhere")
    r = sh(f'fetch_verified {base}/tool {good} {work}/e && echo fetched', CACHE_DIR=str(link))
    assert "fetched" in r.stdout and not (tmp_path / "elsewhere").exists()   # a link is never used as the cache


# ---- install.sh pieces -----------------------------------------------------------------------------------------
def _meminfo(tmp_path, mb: int, swap_kb: int = 0) -> Path:
    f = tmp_path / "meminfo"
    f.write_text(f"MemTotal: {mb * 1024} kB\nSwapTotal: {swap_kb} kB\n")
    return f


def test_service_unit_has_a_memory_cap_sized_from_ram(tmp_path):
    """F01 (proxy side): the web service gets MemoryMax = 60 % of the memory, at least 1 GB."""
    for mb, cap in ((8000, "4800M"), (1000, "1024M")):
        r = sh(f'MEMINFO={_meminfo(tmp_path, mb)}; BIN=/usr/local/bin/maxxing; WORKSPACE=/root/maxxing; '
               f'STATE_DIR=/var/lib/claude-maxxing; HOME=/root; unit_text')
        assert f"\nMemoryMax={cap}\n" in r.stdout and "ExecStart=/usr/local/bin/maxxing serve" in r.stdout, r.stderr


def test_local_voice_on_a_small_server(tmp_path):
    small = _meminfo(tmp_path, 1900)
    base = f'MEMINFO={small}; STATE_DIR={tmp_path}/state; ASSUME_YES=1; '
    r = sh(base + 'VOICE=local; VOICE_GIVEN=""; voice_memory_check; echo "voice=$VOICE"')
    assert "voice=off" in r.stdout                                  # the default: off, said why
    r = sh(base + 'VOICE=local; VOICE_GIVEN=1; voice_memory_check; echo "voice=$VOICE"')
    assert "voice=" not in r.stdout and "needs about 3 GB" in r.stderr   # asked for explicitly: refused unattended
    r = sh(f'MEMINFO={_meminfo(tmp_path, 7800)}; STATE_DIR={tmp_path}; VOICE=local; VOICE_GIVEN=1; '
           'voice_memory_check; echo "voice=$VOICE"')
    assert "voice=local" in r.stdout


def test_swap_is_added_only_on_small_servers_without_swap(tmp_path):
    stubs = ('systemd-detect-virt() { return 1; }; fallocate() { : > "$3"; }; mkswap() { :; }; swapon() { :; }; '
             'df() { printf "x\\n/ 1 1 99999 1%% /\\n"; }; manifest() { echo "manifest $1"; }; ')
    big = sh(stubs + f'MEMINFO={_meminfo(tmp_path, 8000)}; ensure_swap; echo done')
    assert big.stdout.strip() == "done"
    has = sh(stubs + f'MEMINFO={_meminfo(tmp_path, 2000, 1024)}; ensure_swap; echo done')
    assert has.stdout.strip() == "done"
    off = sh(stubs + f'MEMINFO={_meminfo(tmp_path, 2000)}; SWAP=0; ensure_swap; echo done')
    assert off.stdout.strip() == "done"
    ct = sh(stubs.replace("systemd-detect-virt() { return 1; }", "systemd-detect-virt() { return 0; }")
            + f'MEMINFO={_meminfo(tmp_path, 2000)}; ensure_swap; echo done')
    assert "container" in ct.stdout
    for used in ("EXISTING=1", "PRIOR=1"):          # adapted at integration: no swap may be deliberate there
        r = sh(stubs + f'MEMINFO={_meminfo(tmp_path, 2000)}; {used}; ensure_swap; echo done')
        assert "SWAP=1 adds" in r.stdout and "manifest" not in r.stdout


def test_packages_are_skipped_when_everything_is_installed(tmp_path):
    r = sh(f'WORK={tmp_path}/w; mkdir -p $WORK; FIREWALL=0; pkg_installed() {{ return 0; }}; apt_get() {{ echo APT "$@"; }}; '
           'systemctl() { :; }; ensure_swap() { :; }; install_packages')
    assert "already installed" in r.stdout and "APT" not in r.stdout


APT_STUBS = ('ubuntu_universe() { :; }; apt_get() { echo "APT $*"; }; systemctl() { :; }; ensure_swap() { :; }; '
             'pkg_known() { case "$1" in *t64|fonts-noto-color-emoji) return 1 ;; *) return 0 ;; esac; }; ')


def test_packages_base_now_the_rest_in_one_background_job(tmp_path):
    """The base packages are installed right away; tools, browser libraries and security in ONE background apt
    job (never two apt at a time), waited for by apt_wait; apt-get update runs once."""
    r = sh(f'WORK={tmp_path}/w; mkdir -p $WORK; FIREWALL=0; pkg_installed() {{ case "$1" in git|curl) return 0 ;; *) return 1 ;; esac; }}; '
           + APT_STUBS + 'install_packages; echo "bg=${BG_PID[apt]:+yes}"; apt_wait; echo "waited=${BG_PID[apt]:-none}"; '
           'cat "$WORK/apt.log" "$WORK/bg-apt.log"')
    assert "bg=yes" in r.stdout and "waited=none" in r.stdout, r.stdout + r.stderr
    installs = [ln for ln in r.stdout.splitlines() if ln.startswith("APT install")]
    assert len(installs) == 2, r.stdout
    base, rest = installs
    for p in ("python3", "gnupg", "openssh-client"):
        assert f" {p} " in base + " " and f" {p} " not in rest + " ", p
    for p in ("python3-systemd", "fail2ban", "libasound2", "libatk1.0-0", "ffmpeg"):
        assert f" {p} " in rest + " ", p
    assert " git " not in base + rest and "t64" not in rest
    assert len([ln for ln in r.stdout.splitlines() if ln.startswith("APT update")]) == 1
    assert "installing in the background" in r.stdout
    assert "not available on this system: fonts-noto-color-emoji" in r.stdout


def test_only_optional_packages_missing_updates_in_the_background(tmp_path):
    r = sh(f'WORK={tmp_path}/w; mkdir -p $WORK; FIREWALL=0; '
           'pkg_installed() { case "$1" in ffmpeg|fail2ban) return 1 ;; *) return 0 ;; esac; }; '
           + APT_STUBS + 'install_packages; apt_wait; echo ---; cat "$WORK/bg-apt.log"')
    before, bg = r.stdout.split("---")
    assert "APT" not in before                                      # nothing in the foreground
    assert "APT update" in bg and "ffmpeg fail2ban" in bg, r.stdout
    assert "2 system package(s) installed in the background" in before


def test_a_failed_background_apt_stops_the_install(tmp_path):
    r = sh(f'WORK={tmp_path}/w; mkdir -p $WORK; FIREWALL=0; pkg_installed() {{ [ "$1" != ffmpeg ]; }}; '
           + APT_STUBS + 'apt_get() { case "$1" in install) echo "E: broken ffmpeg"; return 100 ;; esac; }; '
           'install_packages; apt_wait; echo "not reached"')
    assert "not reached" not in r.stdout and "E: broken ffmpeg" in r.stdout and "apt-get install failed" in r.stderr


def test_background_jobs_report_their_exit_code(tmp_path):
    r = sh(f'WORK={tmp_path}; job() {{ echo "step one"; false; echo "never"; }}; bg_start j job; '
           'bg_wait j; echo "rc=$?"; bg_wait j; echo "again=$?"')
    assert "| step one" in r.stdout and "never" not in r.stdout and "rc=1" in r.stdout and "again=0" in r.stdout


def test_local_source_detection(tmp_path):
    src = tmp_path / "hm"
    (src / "server/maxxing").mkdir(parents=True)
    (src / "server/maxxing/__init__.py").write_text('__version__ = "9.9.9"\n')
    (src / "install.sh").write_text("")
    r = sh(f'SELF_DIR={src}; INSTALL_DIR={tmp_path}/opt; SOURCE_DIR=""; local_source && echo "src=$SOURCE_DIR"')
    assert f"src={src}" in r.stdout
    r = sh(f'SELF_DIR={src}; INSTALL_DIR={src}; SOURCE_DIR=""; local_source || echo "none"')   # re-run of the install
    assert "none" in r.stdout
    r = sh(f'SELF_DIR=""; INSTALL_DIR={tmp_path}/opt; SOURCE_DIR=""; local_source || echo none')  # piped from curl
    assert "none" in r.stdout


def test_install_from_a_local_copy(tmp_path):
    """Audit 2 §1.1: the code can come from a folder (an unpacked archive) - copied as a git repo without remote."""
    src = tmp_path / "hm"
    for f, text in (("server/maxxing/__init__.py", '__version__ = "9.9.9"\n'), ("install.sh", "#\n"),
                    ("web/dist/index.html", "<html>"), ("server/.venv/bin/python", "x"), (".git/HEAD", "x")):
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        (src / f).write_text(text)
    dest = tmp_path / "opt"
    r = sh(f'SOURCE_DIR={src}; INSTALL_DIR={dest}; BRANCH=main; fetch_local',
           HOME=str(tmp_path), GIT_CONFIG_GLOBAL="/dev/null")
    assert "9.9.9 copied" in r.stdout, r.stdout + r.stderr
    assert (dest / "web/dist/index.html").is_file() and not (dest / "server/.venv").exists()
    assert subprocess.run(["git", "-C", str(dest), "remote"], capture_output=True, text=True).stdout == ""
    (src / "server/maxxing/__init__.py").write_text('__version__ = "9.9.10"\n')
    r = sh(f'SOURCE_DIR={src}; INSTALL_DIR={dest}; BRANCH=main; fetch_local', HOME=str(tmp_path), GIT_CONFIG_GLOBAL="/dev/null")
    assert "9.9.10 copied" in r.stdout and '9.9.10' in (dest / "server/maxxing/__init__.py").read_text()
    (src / "web/dist/index.html").unlink()
    r = sh(f'SOURCE_DIR={src}; INSTALL_DIR={tmp_path}/other; fetch_local')
    assert "web/dist is missing" in r.stderr


@pytest.mark.parametrize("value, ok", [("Europe/Paris", True), ("UTC", True), ("../etc/passwd", False),
                                       ("Europe/Paris;id", False), ("/etc/localtime", False)])
def test_timezone_names_are_validated(value, ok):
    """F12: every value written into files and units is checked first."""
    r = sh('valid_tz_name "$V" && echo fine', V=value)
    assert ("fine" in r.stdout) is ok


@pytest.mark.parametrize("value, ok", [("main", True), ("feat/x-1", True), ("-x", False), ("a..b", False),
                                       ("a b", False), ("a;b", False)])
def test_branch_names_are_validated(value, ok):
    r = sh('check_inputs && echo fine', BRANCH=value, INSTALL_DIR="/opt/x", WORKSPACE="/root/w", STATE_DIR="/var/lib/x",
           PORT="8787", REPO="o/n", LICENSE_API="https://api.example.com", RESTORE_TRUST="0", ALLOW_UNPROTECTED="0",
           FIREWALL="auto", SSH_HARDEN="auto", TOOLS="background", SWAP="auto")
    assert ("fine" in r.stdout) is ok, r.stderr


@pytest.mark.parametrize("value, ok", [("/var/cache/harness-maxxing", True), ("/var/cache", False), ("/etc", False),
                                       ("relative", False), ("/var/cache/a b", False)])
def test_cache_dir_is_validated(value, ok):
    r = sh('check_inputs && echo fine', CACHE_DIR=value, BRANCH="main", INSTALL_DIR="/opt/x", WORKSPACE="/root/w",
           STATE_DIR="/var/lib/x", PORT="8787", REPO="o/n", LICENSE_API="https://api.example.com", RESTORE_TRUST="0",
           ALLOW_UNPROTECTED="0", FIREWALL="auto", SSH_HARDEN="auto", TOOLS="background", SWAP="auto")
    assert ("fine" in r.stdout) is ok, r.stderr


def test_a_new_install_needs_no_license_key(tmp_path):
    """Fair source: without LICENSE nor GH_TOKEN a new install clones the public git repository (no question, no
    license server); LICENSE=HM-... too since 2.0.0a88 (the Enterprise key is only recorded at the end); an existing
    licensed install (still on archives) is kept: it moves to git by itself."""
    stub = 'local_source() { return 1; }'
    base = dict(INSTALL_DIR=str(tmp_path / "opt"), STATE_DIR=str(tmp_path / "state"), REPO="o/n", BRANCH="main")
    r = sh(f'{stub}; choose_source; echo "licensed=$LICENSED local=$LOCAL"', **base)
    assert "licensed=0 local=0" in r.stdout, r.stdout + r.stderr
    assert "github.com/o/n" in r.stdout
    r = sh(f'{stub}; choose_source; echo "licensed=$LICENSED key=$LICENSE"', LICENSE=" hm-abcd-efgh-jkmn-pqrs ", **base)
    assert "licensed=0" in r.stdout and "github.com/o/n" in r.stdout
    r = sh(f'{stub}; choose_source; echo "licensed=$LICENSED"', GH_TOKEN="t", LICENSE="HM-X", **base)
    assert "licensed=0" in r.stdout      # a token: git (private fork / mirror)
    (tmp_path / "opt/.git").mkdir(parents=True)
    (tmp_path / "state").mkdir()
    (tmp_path / "state/secrets.json").write_text('{"license_token": "a1.tok"}')
    r = sh(f'{stub}; choose_source; echo "licensed=$LICENSED"', **base)
    assert "licensed=1" in r.stdout      # re-run of a licensed install: kept


def test_a_keyless_clone_uses_no_token(tmp_path):
    """fetch_code without GH_TOKEN clones the (public) repository with plain git."""
    origin = tmp_path / "origin"
    origin.mkdir()
    g = dict(cwd=origin, capture_output=True, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
                                                   "GIT_CONFIG_GLOBAL": "/dev/null"})
    subprocess.run(["git", "init", "-q", "-b", "main"], **g, check=True)
    (origin / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "."], **g, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "x"], **g, check=True)
    gitconfig = tmp_path / "gitconfig"                  # github.com/o/n -> the local origin (no network)
    gitconfig.write_text(f'[url "{origin}"]\n\tinsteadOf = https://github.com/o/n.git\n')
    r = sh('fetch_code; echo "token_used=$TOKEN_USED"', INSTALL_DIR=str(tmp_path / "opt"), STATE_DIR=str(tmp_path / "st"),
           REPO="o/n", BRANCH="main", HOME=str(tmp_path), GIT_CONFIG_GLOBAL=str(gitconfig))
    assert "cloned into" in r.stdout and "token_used=0" in r.stdout, r.stdout + r.stderr
    assert (tmp_path / "opt/README.md").is_file()

