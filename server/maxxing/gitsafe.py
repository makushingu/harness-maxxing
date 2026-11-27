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
            "-c", "diff.external=", "-c", "core.quotepath=off",
            # a submodule has its own config (.git/modules/<sub>/config: filters, fsmonitor) that the overrides
            # below never see: status / diff never look inside submodules
            "-c", "diff.ignoreSubmodules=all", "-c", "submodule.recurse=false")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"     # attributes read from it = none from the worktree


def _filter_overrides(repo: Path) -> list[str]:
    """`-c filter.<name>.*` neutral values for every filter driver git would see for this repo: every config scope
    (local, worktree via `extensions.worktreeConfig`, included files). Read before every call, never cached: whoever
    writes the config can put its modification time back, and a `.git` file (worktree, submodule) has no config to
    watch. A read that fails raises: no git call runs with filters this module could not list."""
    try:
        r = subprocess.run(["git", *SAFE_GIT, "-C", str(repo), "config", "--includes", "--list"],
                           capture_output=True, text=True, timeout=10, errors="replace",
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1"})
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitError(500, "git_failed", f"git config could not be read: {e}") from e
    names = {m.group(1) for ln in r.stdout.splitlines()
             if (m := re.match(r"filter\.(.+)\.(?:clean|smudge|process|required)=", ln))}
    return [a for n in sorted(names) for a in ("-c", f"filter.{n}.clean=cat", "-c", f"filter.{n}.smudge=cat",
                                              "-c", f"filter.{n}.process=", "-c", f"filter.{n}.required=false")]
