"""Smart resume (config `smart_resume_tokens`).  STDLIB ONLY (imported by the runner).

When a user message comes back to a big session after a pause, the whole history is re-read by the model on the
next call - uncached when the prompt cache expired. Some returns are worth a summary first (idle compaction: a new
subject, the details of the old work no longer matter), others are not (the message builds on what was just done:
a summary would lose exactly the details it needs). One small classifier call decides:

  CONTINUE -> the message runs in the same thread, no summary (even when the idle rule would have compacted);
  NEW      -> the same summary turn as idle compaction runs first, then the message in the fresh thread;
  failure  -> the idle compaction rule as before (runner._idle_compact).

`candidate()` says whether to ask (cheap, under the session lock); `classify()` is the call itself (never under
the lock; tests monkeypatch it or drive the fake claude with FAKE_CLAUDE_RESUME).
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from typing import Callable

from .. import config
from . import spawn, store

MODEL = "claude-haiku-4-5-20251001"     # the same small model as the short titles
TIMEOUT_S = 20.0
MIN_PAUSE_S = 300                       # below this, a message is just the next one of the conversation
BIG_CONTEXT = 100_000                   # this big, a return is worth asking even while the cache is still warm
MIN_TOKENS = 20_000                     # a lower non-zero setting is raised to this (like idle compaction)
CONVERSATION_CHARS = 4000               # recent exchanges sent to the classifier
EXCHANGES = 3
MESSAGE_CHARS = 1500
LOG_TAIL_BYTES = 512 * 1024
SYSTEM_PROMPT = (
    "You triage a returning user in a work chat with an assistant (code, files, servers, writing). The user comes "
    "back after a pause and sends a new message. The long conversation history can either be kept in full, or be "
    "replaced by a short summary (goal, decisions, files touched, what is left). Decide which one answering the "
    "new message needs.\n"
    "CONTINUE: the message builds on the details of the recent work - it asks to go on, to fix or change what was "
    "just done, refers to files, errors, outputs, commands, options or a plan just discussed, answers a question "
    "the assistant asked, or is a short follow-up (\"ok\", \"do it\", \"and the tests?\", \"same for the other one\").\n"
    "NEW: a different task or subject, or a request that stands on its own, where a summary of the session is "
    "enough.\n"
    "When unsure, answer CONTINUE. Reply with exactly one word: CONTINUE or NEW. Never answer the message itself.")
_WORD = re.compile(r"\b(CONTINUE|NEW)\b")


def threshold(cfg: dict) -> int:
    """The context (tokens) from which a return is classified; 0 = smart resume off."""
    n = int(cfg.get("smart_resume_tokens") or 0)
    return max(n, MIN_TOKENS) if n > 0 else 0


def away_text(seconds: float) -> str:
    return f"{seconds / 3600:.0f} h" if seconds >= 5400 else f"{seconds / 60:.0f} min"


def candidate(m: dict, item: dict, cfg: dict, now: float) -> tuple[float, int] | None:
    """(seconds away, context tokens) when the queue head `item` is a user message coming back to session `m`
    after a pause, big enough to be worth a classifier call; None otherwise (then the idle rule applies)."""
    limit = threshold(cfg)
    if not limit:
        return None
    if (item.get("kind") or "user") != "user" or item.get("source") in ("system", "cron") or item.get("steer") \
            or item.get("plan_approved") or item.get("held"):
        return None
    if m.get("fresh", True) or m.get("cron") or m.get("plan_ready"):
        return None
    ctx = int(m.get("context_tokens") or 0)
    last = max(float(m.get("finished_at") or 0), float(m.get("cache_at") or 0))
    if not last or ctx < limit or now - last < MIN_PAUSE_S:
        return None
    base = int(m.get("base_tokens") or 0)              # what a fresh thread costs anyway (CLAUDE.md, memory...)
    if base and ctx - base < limit // 2:
        return None                                    # mostly fixed context: a summary would save nothing
    after = float(cfg.get("idle_compact_after_s") or 3600)
    if now - last < after and ctx < BIG_CONTEXT:
        return None                                    # cache still warm and a medium context: just go on
    return now - last, ctx


# ---- what the classifier reads ---------------------------------------------------------------
def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    half = max(1, (n - 3) // 2)
    return text[:half] + " … " + text[-half:]


def exchanges(sid: str, n: int = EXCHANGES) -> list[tuple[str, str]]:
    """The last `n` (user message, final assistant text) pairs of the session log, oldest first. Only real user
    messages (no seed, summary or system item); the assistant side is the turn's result text."""
    try:
        path = store.log_path(sid)
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - LOG_TAIL_BYTES))
            raw = f.read().decode("utf-8", "replace").splitlines()
    except (OSError, KeyError):
        return []
    if size > LOG_TAIL_BYTES:
        raw = raw[1:]                                  # first line is probably partial
    pairs: list[list[str]] = []
    open_user = False
    for line in raw:
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        t = ev.get("type")
        if t == "mx_user":
            real = (ev.get("kind") or "user") == "user" and ev.get("source") not in ("system", "cron")
            open_user = real
            if real:
                pairs.append([str(ev.get("text") or ""), ""])
        elif open_user and t == "assistant":
            texts = [b.get("text") or "" for b in (ev.get("message") or {}).get("content") or []
                     if isinstance(b, dict) and b.get("type") == "text"]
            if any(x.strip() for x in texts):
                pairs[-1][1] = "\n".join(texts)
        elif open_user and t == "result" and isinstance(ev.get("result"), str) and ev["result"].strip():
            pairs[-1][1] = ev["result"]
    return [(u, a) for u, a in pairs[-n:]]


def conversation(pairs: list[tuple[str, str]], budget: int = CONVERSATION_CHARS) -> str:
    """The pairs as text within `budget` characters: the most recent exchange gets the most room."""
    out: list[str] = []
    left = budget
    for i, (user, assistant) in enumerate(reversed(pairs)):
        share = left if i == len(pairs) - 1 else max(400, left * 3 // 5)
        u = _clip(user, max(150, share // 3))
        a = _clip(assistant, max(150, share - len(u) - 30))
        block = f"[User] {u}\n[Assistant] {a or '(no text)'}"
        if len(block) > left:
            break
        out.append(block)
        left -= len(block) + 2
    return "\n\n".join(reversed(out))


def build_input(title: str, convo: str, message: str) -> str:
    return (f"Session title: {title or '(none)'}\n\n"
            f"Recent conversation (oldest first, trimmed):\n{convo or '(nothing readable)'}\n\n"
            f"New message from the user after the pause:\n{_clip(message, MESSAGE_CHARS)}\n\n"
            "Answer CONTINUE or NEW.")


def parse(answer: str) -> str | None:
    """CONTINUE / NEW from the model's answer, None when it is not clearly one of them (none, or both)."""
    words = set(_WORD.findall((answer or "").upper()))
    return words.pop() if len(words) == 1 else None


# ---- the call --------------------------------------------------------------------------------
def classify(title: str, convo: str, message: str, should_stop: Callable[[], bool] | None = None,
             timeout: float = TIMEOUT_S) -> str | None:
    """One small `claude -p` call (no tools, no saved thread, no MCP) -> "CONTINUE" | "NEW", or None on any failure,
    timeout, or when `should_stop()` turns true meanwhile (the process is killed)."""
    cmd = [spawn.claude_bin(), "-p", "--output-format", "json", "--model", MODEL, "--tools", "",
           "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
           "--system-prompt", SYSTEM_PROMPT]
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, cwd=config.state_dir("claude-resume"),
                             env=spawn.claude_env(None, "default"), start_new_session=True)
    except OSError:
        return None
    payload = build_input(title, convo, message)
    end = time.time() + timeout
    out = ""
    while True:
        try:
            out, _ = p.communicate(payload, timeout=0.2)     # the input is written once, the wait resumes
            break
        except subprocess.TimeoutExpired:
            if time.time() >= end or (should_stop and should_stop()):
                _kill(p)
                return None
        except (OSError, ValueError):
            _kill(p)
            return None
    try:
        data = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
    except ValueError:
        data = {}
    if p.returncode != 0 or not isinstance(data, dict) or data.get("is_error"):
        return None
    return parse(str(data.get("result") or ""))


def _kill(p: subprocess.Popen) -> None:
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        p.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass
