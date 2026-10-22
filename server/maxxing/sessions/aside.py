"""Side questions: ask Claude about a session without interrupting it.

The question runs in a throwaway copy of the session's Claude thread (`--resume <csid> --fork-session
--no-session-persistence`): Claude knows the whole conversation, but nothing is written - the running turn,
the queue and the thread are untouched, and the exchange is not added to the session log. Read-only
(`--permission-mode plan`). One side question at a time per session, two in all (each is a claude
process next to the running turn: memory on a small server).
"""
from __future__ import annotations

import json
import subprocess
import threading
import time

from .. import config
from . import spawn, store
from .runner import Runner
from .service import SessionError, _require

ASK_TIMEOUT_S = 240
MAX_PARALLEL = 2
QUESTION_MAX = 8000

ASK_PREFACE = ("[Side question from the user, answered apart: your main task goes on in another process and this "
               "exchange is not part of it. Answer from what you already know of this conversation - briefly, in "
               "the user's language. Change nothing; use a read-only tool only if you really need to check "
               "something.]\n\n")

_lock = threading.Lock()
_busy: set[str] = set()


def ask(sid: str, question: str) -> dict:
    """-> {answer, cost_usd, duration_ms}. 409 when the session has no Claude thread yet or is already
    answering a side question, 429 when two side questions are running."""
    m = _require(sid)
    question = (question or "").strip()[:QUESTION_MAX]
    if not question:
        raise SessionError(400, "empty", "Empty question")
    csid = m.get("csid")
    if not csid or m.get("fresh", True):
        raise SessionError(409, "no_thread", "Nothing to ask about yet: this session has not answered once.")
    cfg = config.load_config()
    cwd = Runner._cwd(cfg, m)
    if cwd is None:
        raise SessionError(409, "no_topic", "The topic folder of this session no longer exists.")
    with _lock:
        if sid in _busy:
            raise SessionError(409, "busy", "A side question is already being answered for this session.")
        if len(_busy) >= MAX_PARALLEL:
            raise SessionError(429, "throttled", "Two side questions are already running - try again in a moment.")
        _busy.add(sid)
    try:
        out = _run(m, csid, cwd, cfg, question)
        try:
            store.update(sid, cache_at=time.time())      # the fork read the thread: its prompt cache is warm again
        except KeyError:                                 # the session was deleted while Claude answered
            pass
        return out
    finally:
        with _lock:
            _busy.discard(sid)


def _run(m: dict, csid: str, cwd: str, cfg: dict, question: str) -> dict:
    model = (m.get("model") or cfg.get("default_model") or "").strip()
    args = [spawn.claude_bin(), "-p", "--output-format", "json", *spawn.permission_args("plan")[0],
            "--resume", csid, "--fork-session", "--no-session-persistence", *spawn.settings_args(cfg)] + (["--model", model] if model else [])
    env = spawn.claude_env(m.get("env") or {}, "plan")
    t0 = time.time()
    try:
        p = subprocess.run(args, input=ASK_PREFACE + question, capture_output=True, text=True, cwd=cwd, env=env,
                           timeout=ASK_TIMEOUT_S, start_new_session=True)
    except subprocess.TimeoutExpired:
        raise SessionError(504, "timeout", f"No answer after {ASK_TIMEOUT_S} s.") from None
    except OSError as e:
        raise SessionError(500, "spawn_failed", f"Claude could not start: {e}") from None
    try:
        res = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
    except ValueError:
        res = {}
    answer = str(res.get("result") or "").strip()
    if p.returncode != 0 or res.get("is_error") or not answer:
        detail = answer or (p.stderr or "").strip()[-300:] or f"exit code {p.returncode}"
        raise SessionError(502, "ask_failed", f"The side question failed: {detail}")
    # the fork starts from the thread's running total: only the increase is this question's cost
    cost = store.turn_cost(float(res.get("total_cost_usd") or 0), store.thread_prev_cost(m, csid))
    return {"answer": answer, "cost_usd": round(cost, 4),
            "duration_ms": int(res.get("duration_ms") or (time.time() - t0) * 1000)}
