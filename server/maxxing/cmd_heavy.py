"""`maxxing heavy <command…>`: run a long, CPU-hungry command (a video render, an encode, a big build) with the
background priority, so the UI and the sessions stay quick while it runs.

The command runs in a systemd scope of `maxxing-jobs.slice` (CPU priorities, maxxing/cpu.py), in the foreground: same
terminal, same output, same exit code. Without systemd or root: under `nice -n 10` and `ionice -c3`. It is never
capped: it only gives way while the processor is full.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from . import cli, cpu

_exec = os.execvp                  # monkeypatched in tests


def run(cmd: list[str], cwd: str | Path | None = None) -> int:
    """Replace this process with `cmd` under the background priority (returns only when it cannot start)."""
    if not cmd:
        print("maxxing heavy: give the command to run, e.g. maxxing heavy ffmpeg -i in.mov out.mp4", file=sys.stderr)
        return 2
    if shutil.which(cmd[0]) is None and not os.path.exists(os.path.join(str(cwd or "."), cmd[0])):
        print(f"maxxing heavy: {cmd[0]}: command not found", file=sys.stderr)
        return 127
    argv = cpu.heavy_argv(cmd)
    if cwd:
        os.chdir(cwd)
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        _exec(argv[0], argv)
    except OSError as e:
        print(f"maxxing heavy: {argv[0]}: {e.strerror or e}", file=sys.stderr)
        return 127
    return 0                       # only reached when _exec is a test double


def _configure(p: argparse.ArgumentParser) -> None:
    p.add_argument("command", nargs=argparse.REMAINDER, help="the command and its arguments")


def _handler(a) -> int:
    cmd = list(a.command)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    return run(cmd)


cli.register("heavy", "Run a long CPU-hungry command (render, encode, build) after the UI and the sessions",
             _configure, _handler)
