"""Git primitives shared by the Git page (gitview) and the Changes view (codediff). Standard library only: the turn
runner imports it to photograph repositories before and after a turn."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


class GitError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# A repository's own config can name programs git runs on a plain status / log / show (core.fsmonitor, signature
# checks, clean filters, diff drivers, hooks). Repositories found under the files root are not trusted (an extracted
# archive, a clone made by a turn): these settings are switched off on the command line, which wins over the repo.
SAFE_GIT = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "log.showSignature=false",
            "-c", "gpg.program=false", "-c", "gpg.ssh.program=false", "-c", "gpg.x509.program=false",
            "-c", "diff.external=", "-c", "core.quotepath=off")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"     # attributes read from it = none from the worktree
_filters: dict[str, tuple[tuple, list[str]]] = {}


def _filter_overrides(repo: Path) -> list[str]:
    """`-c filter.<name>.*` neutral values for every filter driver git would see for this repo: every config scope
    (local, worktree via `extensions.worktreeConfig`, included files), cached while those files are unchanged."""
    gd = repo / ".git"
    stamp = tuple((f.stat().st_mtime_ns if f.exists() else 0) for f in (gd / "config", gd / "config.worktree", gd))
    hit = _filters.get(str(repo))
    if hit and hit[0] == stamp:
        return hit[1]
    names: set[str] = set()
    cacheable = True
    try:
        r = subprocess.run(["git", *SAFE_GIT, "-C", str(repo), "config", "--includes", "--list"],
                           capture_output=True, text=True, timeout=10, errors="replace",
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1"})
        for ln in r.stdout.splitlines():
            m = re.match(r"filter\.(.+)\.(?:clean|smudge|process|required)=", ln)
            if m:
                names.add(m.group(1))
            if ln.startswith(("include.", "includeif.")):
                cacheable = False                         # an included file can change without touching these
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = [a for n in sorted(names) for a in ("-c", f"filter.{n}.clean=cat", "-c", f"filter.{n}.smudge=cat",
                                              "-c", f"filter.{n}.process=", "-c", f"filter.{n}.required=false")]
    if cacheable:
        _filters[str(repo)] = (stamp, out)
    return out
