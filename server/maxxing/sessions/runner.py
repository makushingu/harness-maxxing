"""Turn runner - a process DETACHED from the web server.  STDLIB ONLY.

    python -m maxxing.sessions.runner <sid>        (or: python path/to/runner.py <sid>)

Started by spawn.start() in a transient systemd unit (or a detached subprocess). It processes the
session's queue turn after turn, then exits:

  1. takes the run lock (`<id>.run`; another live runner -> exit at once), records its pid;
  2. pops the next queue item, writes an `mx_user` line into the raw log;
  3. runs `claude -p --output-format stream-json --verbose [--model M] <permission flags>`
     with `--session-id <csid>` on a fresh thread, `--resume <csid>` afterwards. The prompt goes
     through stdin (no argv size limit, no option parsing of a leading "-");
  4. copies every stream-json line into the log (with an `mx_at` timestamp added, tool outputs
     clipped by clip.py) and keeps
     cost / real model / context size / last assistant text in the meta;
  5. if `--resume` fails because Claude lost the thread (purged transcript), starts a new csid in
     the same session (`mx_note` warns the user) - the displayed history is kept;
  6. writes an `mx_done` line; compact / handoff items post-process the summary;
  7. when the queue is empty: state idle (or error if the last turn failed), exit.

SIGTERM aborts the CURRENT turn only (the server clears the queue before signalling), so a
message sent right after "stop" is still processed. SIGUSR1 (steer) also ends the current turn but
keeps the queue: its head - the steered message, `steer: true` - runs next in the same Claude thread
with a preface telling Claude to go on with it. `timeout_s` (meta) caps a turn.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

if __package__ in (None, ""):                       # path invocation
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from maxxing import claude_auth, config, mcp_auto   # noqa: E402  (stdlib-only modules)
from maxxing.sessions import clip, resume, spawn, store      # noqa: E402

RESUME_LOST = re.compile(r"no conversation found|session .{0,80}not found|no such session|"
                         r"invalid session|could not resume|failed to resume", re.I)
SUMMARY_PROMPT = (
    "Summarize this conversation in at most 15 lines so that a NEW session (same folder, same "
    "CLAUDE.md/memory.md context, but with no memory of this exchange) can resume exactly where we "
    "are: goal, decisions taken, progress, files touched (paths), what is left to do, known pitfalls. "
    "Only the summary, in the language of this conversation, no preamble.")
AUTO_COMPACT_MIN = 100_000                             # a lower setting is raised to this (summaries cost a turn)
SEED_COMPACT = ("Context of this session before compaction (automatic summary):\n\n{summary}\n\n"
                "Read it; we continue from there.")
IDLE_COMPACT_MIN = 20_000                              # a lower non-zero idle threshold is raised to this
SEED_HANDOFF = ("Context carried over from session '{title}' (automatic summary):\n\n{summary}\n\n"
                "Read it; we continue from there.")
STDERR_TAIL = 4000
CGROUP_FS = Path("/sys/fs/cgroup")
OOM_ERROR = ("Claude was killed by the kernel: the turn ran out of memory (a command used too much RAM; "
             "`journalctl -k | grep -i oom` shows which).")
LATENCY_KEPT = 20                                     # per session: seconds to the first event / answer


@dataclass
class Attempt:
    """Outcome of one `claude` process."""
    rc: int = 1
    stderr: str = ""
    saw_init: bool = False
    result: dict | None = None
    final_text: str = ""
    real_model: str | None = None
    context_tokens: int | None = None
    first_context: int | None = None          # context of the call's first answer (before any tool output)
    fresh: bool = False                       # the call started a new thread (its context is the fixed base)
    turn_cost: float | None = None                     # this turn only (Claude reports the thread's total)
    thread_total: float | None = None
    csid: str = ""
    prev_total: float = 0.0
    stopped: bool = False
    timed_out: bool = False
    held: list[str] = field(default_factory=list)   # lines held back while a resume may fail
    t0: float = 0.0                                    # claude process started
    start_s: float | None = None                       # -> its first event (Claude Code ready)
    first_s: float | None = None                       # -> its first answer (start + the API's first response)
    oom: bool = False                                  # SIGKILLed while the unit's oom_kill counter went up
    mcp_used: set[str] = field(default_factory=set)    # MCP servers (tool form) whose tools were called
    connectors: list[str] | None = None                # claude.ai connectors listed by the init event


class Runner:
    def __init__(self, sid: str) -> None:
        self.sid = sid
        self.child: subprocess.Popen | None = None
        self.stop_flag = threading.Event()
        self.lock = threading.RLock()                  # re-entrant: signal handlers run on the main thread
        self.turn_id = ""                              # id of the turn in progress (meta turn_id)
        self.current: dict | None = None               # queue item of the turn in progress
        self.voice_wait = False                        # waiting for the transcript of a voice message (_voice)
        self.interrupted = False                       # the current turn was cut short by a steer

    # ---- signals -------------------------------------------------------------------------
    def on_sigterm(self, *_: object) -> None:
        self.stop_flag.set()
        self._kill_child()

    def on_steer(self, *_: object) -> None:
        """SIGUSR1 (POST /steer): end the current turn so the steered message at the head of the queue
        runs next, in the same Claude thread. A steered turn itself is never interrupted (the signal can
        arrive just after the runner moved on to it)."""
        # Only the turn the user steered: the server wrote its id (steer_turn) before signalling, so a
        # signal that arrives once the runner moved on (to the steered message itself, or later) is ignored.
        m = store.read(self.sid) or {}
        cur = self.current or {}
        if not self.turn_id or m.get("steer_turn") != self.turn_id or cur.get("kind") in ("compact", "handoff"):
            return
        if self.voice_wait:                            # a voice message waiting for its transcript: never lost, the
            return                                     # steered message runs right after it
        self.interrupted = True
        self.stop_flag.set()
        self._kill_child()

    def _kill_child(self) -> None:
        with self.lock:
            p = self.child
        if p is None or p.poll() is not None:
            return
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except OSError:
            return

        def hard_kill() -> None:
            time.sleep(5)
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
        threading.Thread(target=hard_kill, daemon=True).start()

    # ---- log helpers ---------------------------------------------------------------------
    def note(self, text: str, level: str = "info") -> None:
        store.append_log(self.sid, {"type": "mx_note", "text": text, "level": level, "at": time.time()})

    # ---- main loop -------------------------------------------------------------------------
    def run(self) -> int:
        fd = store.hold_run_lock(self.sid, wait_s=20.0)   # a previous runner may still be exiting
        if fd is None:
            return 0                                   # another runner owns this session
        signal.signal(signal.SIGTERM, self.on_sigterm)
        signal.signal(signal.SIGINT, self.on_sigterm)
        signal.signal(signal.SIGUSR1, self.on_steer)
        failed: str | None = None
        try:
            while True:
                item = self._pop(failed)                # also sets self.current / self.turn_id
                if item is None:
                    break
                failed = self.turn(item)
                self.current = None
        except Exception as e:                         # never leave a session "running"
            self._crash(e)
        finally:
            os.close(fd)
        return 0

    def _pop(self, failed: str | None) -> dict | None:
        """Next queue item, or None after setting the final state - atomically, so a message
        queued by the server is either popped here or finds the session idle and respawns it. A user message
        that comes back to a big session after a pause may be preceded by a summary turn (smart resume / idle
        compaction): the message stays at the head of the queue and runs in the fresh thread.

        Smart resume asks a small classifier first. That call never runs under the session lock: the head is
        inspected under the lock (the state stays "running", so the server queues behind us and never respawns),
        the lock is released for the call, then re-taken to pop. A Stop, a steer or an edit meanwhile changes the
        head: the call is cut short and the new head is looked at again (verdicts are only used for the item they
        were asked about)."""
        asked: tuple[dict, str | None] | None = None   # (queue head as classified, verdict or None = failed)
        for attempt in range(3):
            ask = None
            with store.edit(self.sid) as m:
                m["spawned_at"] = None
                q = m.get("queue") or []
                m["updated"] = time.time()
                if not q:
                    m["pid"], m["state"] = None, ("error" if failed else "idle")
                    m.pop("runner_caps", None)
                    m.pop("turn_id", None)
                    m.pop("turn_refs", None)
                    return None
                cfg, now = config.load_config(), time.time()
                same = asked is not None and q[0] == asked[0]
                if not same and attempt < 2:
                    ask = resume.candidate(m, q[0], cfg, now)
                if not ask:
                    return self._take(m, q, cfg, now, asked[1] if same and asked else None)
                # Like a turn that is starting (no pid): the head shows as being sent, not as waiting, and is never
                # merged by a steer; a Stop just clears the queue (seen below, no signal needed).
                m["pid"] = None
                head, title = json.loads(json.dumps(q[0])), str(m.get("title") or "")
                self.stop_flag.clear()
            verdict = resume.classify(title, resume.conversation(resume.exchanges(self.sid)), head.get("text") or "",
                                      should_stop=lambda h=head: self._head_changed(h))
            asked = (head, verdict)
        return None                                    # not reached: the third pass never asks

    def _head_changed(self, head: dict) -> bool:
        if self.stop_flag.is_set():
            return True
        q = (store.read(self.sid) or {}).get("queue") or []
        return not q or q[0] != head

    def _take(self, m: dict, q: list, cfg: dict, now: float, verdict: str | None) -> dict:
        """Pop the queue head (under the session lock), with the summary turn first when the return is worth it."""
        item = q.pop(0)
        item.pop("held", None)
        if verdict == "CONTINUE":                      # builds on the recent details: resume as is
            idle = None
        elif verdict == "NEW":
            away = now - max(float(m.get("finished_at") or 0), float(m.get("cache_at") or 0))
            idle = (resume.away_text(away), int(m.get("context_tokens") or 0) // 1000)
        else:                                          # not asked, or the call failed: the idle rule as before
            idle = _idle_compact(m, item, cfg, now)
        if idle:                                       # the summary runs first, the message waits at the head
            q.insert(0, {**item, "held": True})        # a Stop cancels the summary, never the user's message
            item = {"text": SUMMARY_PROMPT, "attachments": [], "source": "system", "kind": "compact",
                    "auto": True, "idle": True, "at": time.time()}
        m["queue"], m["state"], m["pid"] = q, "running", os.getpid()
        m["runner_caps"] = ["steer"]                   # the server may send SIGUSR1 (steer) to this runner
        # Before releasing the lock: a steer can only target this turn once its id is known.
        self.turn_id = m["turn_id"] = uuid.uuid4().hex[:12]
        # Still under the lock: a Stop / steer for THIS turn can only be sent once the item is popped, so it is
        # never wiped here (one that targeted the previous turn arrived before and is dropped).
        self.stop_flag.clear()
        self.interrupted = False
        m["turn_kind"] = item.get("kind") or "user"
        m["turn_refs"] = list(item.get("refs") or [])  # the caller's ids of this message (Telegram)
        self.current = item
        if idle:
            hours, tokens = idle
            if verdict == "NEW":
                text = (f"New subject after {hours}: Harness summarized the session ({tokens}k tokens) before your "
                        "message - cheaper from now on (smart resume, Settings -> Claude). The history stays "
                        "displayed here.")
            else:
                text = (f"Back after {hours}: the cache had expired, Harness summarized the session ({tokens}k tokens) "
                        "before your message - cheaper from now on (idle compaction, Settings -> Claude). The history "
                        "stays displayed here.")
            self.note(text)                            # under the lock: written before the summary turn starts
        return item

    def _crash(self, e: Exception) -> None:
        try:
            self.note(f"Runner error: {e}"[:500], "error")
            with store.edit(self.sid) as m:
                m["pid"], m["spawned_at"], m["state"] = None, None, "error"
                m["error"], m["updated"] = f"runner: {e}"[:300], time.time()
        except Exception:
            pass

    # ---- one turn ------------------------------------------------------------------------
    def turn(self, item: dict) -> str | None:
        """Run one queue item; returns an error string when the turn failed (None when ok)."""
        meta = store.read(self.sid) or {}
        cfg = config.load_config()
        kind = item.get("kind") or "user"
        voices = [v for v in item.get("voice") or [] if isinstance(v, dict) and v.get("path")]
        store.append_log(self.sid, {"type": "mx_user", "text": item.get("text") or "",
                                    "attachments": item.get("attachments") or [],
                                    "source": item.get("source") or "web", "kind": kind,
                                    **({"voice": [str(v["path"]) for v in voices]} if voices else {}),
                                    "at": time.time()})
        if voices:
            heard, err = self._voice(item, voices)
            if heard is None:                          # stopped, or nothing to send: no Claude call
                return err
            item = heard
        cwd = self._cwd(cfg, meta)
        if cwd is None:
            err = f"Topic folder not found: {meta.get('path')!r}"
            self.note(err, "error")
            self._record(Attempt(rc=1, stderr=err), item)
            return err
        mode = effective_mode(meta, cfg)
        # Plan mode: a read-only turn that ends with a plan; the user validates it (approve_plan) before
        # anything is changed. Compact / hand-off summaries run as usual.
        plan = bool(meta.get("plan_mode")) and kind not in ("compact", "handoff")
        if plan:
            mode = "plan"
        if meta.get("plan_ready"):
            store.update(self.sid, plan_ready=False)
        model = (meta.get("model") or cfg.get("default_model") or "").strip()
        mcp_plan = mcp_auto.plan(self.sid, cfg, meta, cwd, item.get("text") or "")   # MCP servers this turn needs
        base = [spawn.claude_bin(), "-p", "--output-format", "stream-json", "--verbose"]
        base += spawn.permission_args(mode)[0] + spawn.settings_args(cfg) + spawn.agents_args(cfg, mcp_plan.hint)
        base += ["--model", model] if model else []
        from maxxing import pcbridge                    # not at import: the runner starts with stdlib-only modules
        base += pcbridge.mcp_config_args() + mcp_plan.args
        env = spawn.claude_env(meta.get("env") or {}, mode)
        env["MAXXING_SESSION"] = self.sid               # `maxxing mcp load` run by the turn finds its session
        text = (PLAN_PREFACE if plan else "") + build_prompt(item)
        prompt, json_in = stdin_payload(text, item, Path(cfg.get("workspace") or "/").resolve())
        if json_in:
            base += ["--input-format", "stream-json"]
        timeout_s = meta.get("timeout_s")

        csid, fresh = meta.get("csid") or self.sid, bool(meta.get("fresh", True))
        a = self.attempt(base + (["--session-id", csid] if fresh else ["--resume", csid]),
                         prompt, cwd, env, timeout_s, hold=not fresh, csid=csid,
                         prev_total=0.0 if fresh else store.thread_prev_cost(meta, csid))
        a.fresh = fresh
        if not fresh and a.rc != 0 and not a.saw_init and not a.stopped and _resume_lost(a):
            csid = str(uuid.uuid4())
            store.update(self.sid, csid=csid, fresh=True)
            self.note("The previous conversation thread was no longer available. A new thread was started in "
                      "this session: the history above is kept, but Harness no longer remembers it.", "warn")
            a = self.attempt(base + ["--session-id", csid], prompt, cwd, env, timeout_s, hold=False, csid=csid)
            a.fresh = True
        else:
            for line in a.held:                        # not a lost thread: keep what it printed
                self._write_line(line)
        if a.saw_init:
            store.update(self.sid, fresh=False)
        if a.stopped and self.interrupted and not a.timed_out:
            self.note("Interrupted to take your new message into account - Harness continues the task with it.")
        elif a.stopped:
            self.note("Stopped." if not a.timed_out else f"Turn stopped after {timeout_s} s (timeout).",
                      "warn")
        store.append_log(self.sid, {"type": "mx_done", "code": a.rc, "stderr": a.stderr[-STDERR_TAIL:],
                                    "stopped": a.stopped and not a.timed_out,
                                    "timed_out": a.timed_out, "at": time.time()})
        err = self._record(a, item)
        if plan and err is None and not a.stopped:
            store.update(self.sid, plan_ready=True)
        self._post(item, a, err)
        self._mcp_after(item, a, err, cfg, meta, mcp_plan, plan)
        if not plan:
            self._auto_compact(item, a, err, cfg)
        return err

    def _mcp_after(self, item: dict, a: Attempt, err: str | None, cfg: dict, meta: dict,
                   mcp_plan: mcp_auto.Plan, plan: bool) -> None:
        """Remembers the MCP servers the topic used and the claude.ai connectors seen; when the turn asked for a
        server it was not given (`maxxing mcp load`), queues a continuation first - at most CONTINUE_MAX in a row."""
        try:
            if a.mcp_used:
                mcp_auto.record_used(str(meta.get("path") or ""), a.mcp_used)
            if not mcp_plan.args and a.connectors is not None:     # a full list only when nothing was restricted
                mcp_auto.record_connectors(a.connectors)
            if not mcp_plan.args or err is not None or a.stopped or plan:
                return
            before = set(meta.get("mcp_loaded") or [])
            given = {mcp_auto.norm(n) for n in mcp_plan.loaded}
            now = (store.read(self.sid) or {}).get("mcp_loaded") or []
            new = [n for n in now if isinstance(n, str) and n not in before and mcp_auto.norm(n) not in given]
            if not new:
                return
            streak = int(item.get("mcp_continue") or 0) + 1
            if streak > mcp_auto.CONTINUE_MAX:
                self.note(f"MCP server {', '.join(new)} loaded for the next message (Harness did not continue by "
                          "itself again).")
                return
            with store.edit(self.sid) as m:
                m["queue"] = [mcp_auto.continue_item(new, streak)] + (m.get("queue") or [])
            self.note(f"MCP server {', '.join(new)} loaded: Harness continues the turn.")
        except Exception as e:                         # noqa: BLE001 - never fails a turn
            self.note(f"MCP auto-loading: {e}"[:300], "warn")

    def _voice(self, item: dict, voices: list[dict]) -> tuple[dict | None, str | None]:
        """A voice message sent directly: wait for its transcription (done by the server, voicejobs.py), show it
        (`mx_voice`) and return the item whose text Claude gets. -> (item, None), or (None, error | None when
        stopped) - nothing is sent then."""
        ids = [str(v.get("id") or "") for v in voices]
        deadline, jobs = time.time() + VOICE_WAIT_S, {}
        self.voice_wait = True
        try:
            while not self.stop_flag.is_set():
                jobs = (store.read(self.sid) or {}).get("voice_jobs") or {}
                if not isinstance(jobs, dict):
                    jobs = {}
                if all((jobs.get(j) or {}).get("state") in ("done", "error") or j not in jobs for j in ids):
                    break
                if time.time() > deadline:
                    break
                self.stop_flag.wait(VOICE_POLL_S)
        finally:
            self.voice_wait = False
        with store.edit(self.sid) as m:
            left = m.get("voice_jobs")
            if isinstance(left, dict):
                for j in ids:
                    left.pop(j, None)
                if not left:
                    m.pop("voice_jobs", None)
        if self.stop_flag.is_set():
            store.append_log(self.sid, {"type": "mx_voice", "text": "", "error": None, "stopped": True,
                                        "at": time.time()})
            self.note("Stopped.", "warn")
            return None, None
        texts, errors = [], []
        for j in ids:
            job = jobs.get(j) if isinstance(jobs.get(j), dict) else {}
            if job.get("state") == "done" and str(job.get("text") or "").strip():
                texts.append(str(job["text"]).strip())
            elif job.get("state") == "done":
                errors.append("nothing was heard in the recording")
            else:
                errors.append(str(job.get("error") or ("the transcription took too long" if job
                                                         else "the transcription was cancelled")))
        heard = "\n\n".join(texts)
        store.append_log(self.sid, {"type": "mx_voice", "text": heard, "error": "; ".join(errors)[:500] or None,
                                    "at": time.time()})
        if not texts and not (item.get("text") or "").strip() and not item.get("attachments"):
            err = f"Voice message not transcribed: {'; '.join(errors)}"[:300]
            self.note(err + ". The recording is kept above (play it, or send it again).", "error")
            return None, err
        paths = ", ".join(str(v["path"]) for v in voices)
        text = "\n\n".join(t for t in (item.get("text") or "", heard) if t.strip())
        return {**item, "text": text, "preface": "\n\n".join(
            p for p in (item.get("preface") or "", VOICE_PREFACE.format(paths=paths)) if p)}, None

    def _auto_compact(self, item: dict, a: Attempt, err: str | None, cfg: dict) -> None:
        """After a turn that ended with a big context: a summary turn runs next (before any waiting message) and
        the session continues in a fresh thread seeded with it - every later call stops re-sending the history."""
        limit = int(cfg.get("auto_compact_tokens") or 0)
        if limit <= 0 or err is not None or a.stopped or not a.context_tokens:
            return
        limit = max(limit, AUTO_COMPACT_MIN)
        if a.context_tokens < limit or (item.get("kind") or "user") not in ("user", "seed"):
            return
        with store.edit(self.sid) as m:
            q = m.get("queue") or []
            if m.get("cron") or m.get("plan_ready") or any(x.get("kind") in ("compact", "handoff") for x in q):
                return
            m["queue"] = [{"text": SUMMARY_PROMPT, "attachments": [], "source": "system", "kind": "compact",
                           "auto": True, "at": time.time()}] + q
        self.note(f"The context reached {a.context_tokens // 1000}k tokens: Harness summarizes this session and "
                  "continues in a fresh thread (automatic compaction, Settings -> Claude). The history stays "
                  "displayed here.")

    @staticmethod
    def _cwd(cfg: dict, meta: dict) -> str | None:
        root = Path(cfg.get("workspace") or "/").resolve()
        cwd = (root / (meta.get("path") or "")).resolve()
        if cwd != root and root not in cwd.parents:
            return None
        return str(cwd) if cwd.is_dir() else None

    def attempt(self, args: list[str], prompt: str, cwd: str, env: dict, timeout_s: object,
                hold: bool, csid: str = "", prev_total: float = 0.0) -> Attempt:
        """Run one claude process, streaming its stdout into the raw log. `prev_total`: the running cost Claude
        last reported for thread `csid` (to tell this turn's own cost). Holds the Claude Code update lock (shared)
        meanwhile: an automatic update never replaces the files of a running Claude, and waits for it."""
        fd = _claude_in_use(self.note)
        try:
            return self._attempt(args, prompt, cwd, env, timeout_s, hold, csid, prev_total)
        finally:
            if fd is not None:
                os.close(fd)

    def _attempt(self, args: list[str], prompt: str, cwd: str, env: dict, timeout_s: object,
                 hold: bool, csid: str = "", prev_total: float = 0.0) -> Attempt:
        a = Attempt(csid=csid, prev_total=prev_total, t0=time.time())
        oom_before = _oom_kills()
        try:
            p = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, bufsize=1, start_new_session=True)
        except (OSError, ValueError) as e:                # ValueError: a NUL in an argument (an old session's model)
            a.stderr = f"Cannot start Claude ({args[0]}): {e}"
            return a
        with self.lock:
            self.child = p
        if self.stop_flag.is_set():                    # stop arrived while starting
            self._kill_child()
        err_chunks: list[str] = []
        t_err = threading.Thread(target=_stderr_tail, args=(p.stderr, err_chunks), daemon=True)
        t_err.start()
        timer = None
        if timeout_s:
            def on_timeout() -> None:
                a.timed_out = True
                self.stop_flag.set()
                self._kill_child()
            timer = threading.Timer(float(timeout_s), on_timeout)
            timer.daemon = True
            timer.start()
        threading.Thread(target=_feed, args=(p, prompt), daemon=True).start()
        for raw in _lines_until_exit(p):
            line = raw.strip()
            if not line:
                continue
            ev = _parse(line)
            if ev is not None:
                self._observe(ev, a)
                if ev.get("type") == "result" and a.thread_total is not None:
                    ev["mx_turn_cost"] = a.turn_cost   # shown per turn in the thread (normalize.py)
                if not clip.keep_event(ev):            # progress-only lines (thinking_tokens)
                    continue
                clip.clip_event(ev)                    # huge tool outputs / the init lists never reach the log
                ev.setdefault("mx_at", time.time())
                line = json.dumps(ev, ensure_ascii=False)
            if hold and not a.saw_init:
                a.held.append(line)
                continue
            if a.held:
                for h in a.held:
                    self._write_line(h)
                a.held = []
            self._write_line(line)
        a.rc = p.wait()
        if a.rc in (-9, 137) and oom_before is not None:
            a.oom = (_oom_kills() or 0) > oom_before
        if timer:
            timer.cancel()
        t_err.join(timeout=5)
        a.stderr = "".join(err_chunks).strip()[-STDERR_TAIL:]
        a.stopped = self.stop_flag.is_set()
        with self.lock:
            self.child = None
        return a

    def _write_line(self, line: str) -> None:
        with open(store.log_path(self.sid), "a") as f:
            f.write(line + "\n")

    @staticmethod
    def _observe(ev: dict, a: Attempt) -> None:
        t = ev.get("type")
        if a.start_s is None and a.t0:
            a.start_s = round(time.time() - a.t0, 3)
        if t == "assistant":                           # subagents' calls count too
            for b in (ev.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    srv = mcp_auto.tool_server(b.get("name"))
                    if srv:
                        a.mcp_used.add(srv)
        if t == "system" and ev.get("subtype") == "init":
            a.saw_init = True
            a.connectors = mcp_auto.connectors_of_init(ev)
        elif t == "assistant" and not ev.get("parent_tool_use_id"):
            if a.first_s is None and a.t0:
                a.first_s = round(time.time() - a.t0, 3)
            msg = ev.get("message") or {}
            if msg.get("model") and not str(msg["model"]).startswith("<"):
                a.real_model = msg["model"]
            u = msg.get("usage") or {}
            if u:
                a.context_tokens = sum(int(u.get(k) or 0) for k in
                                       ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                if a.first_context is None:
                    a.first_context = a.context_tokens
            for b in msg.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip():
                    a.final_text = b["text"]
        elif t == "rate_limit_event":
            claude_auth.record_limits(ev.get("rate_limit_info"))
        elif t == "result":
            a.result = ev
            if ev.get("total_cost_usd") is not None:
                a.thread_total = float(ev.get("total_cost_usd") or 0)
                a.turn_cost = store.turn_cost(a.thread_total, a.prev_total)
            if isinstance(ev.get("result"), str) and ev["result"].strip():
                a.final_text = ev["result"]
            mu = ev.get("modelUsage")
            if isinstance(mu, dict) and mu and not a.real_model:
                a.real_model = next(iter(mu))

    def _record(self, a: Attempt, item: dict) -> str | None:
        """Update the meta after a turn; returns the error string (None when ok)."""
        res = a.result or {}
        ok = a.rc == 0 and not res.get("is_error") and not a.stopped
        err = None
        if not ok and not (a.stopped and not a.timed_out):
            errors = res.get("errors") if isinstance(res.get("errors"), list) else []
            err = ("; ".join(str(e) for e in errors) or a.stderr or
                   ("Turn stopped (timeout)" if a.timed_out else "")
                   or f"Claude exited with code {a.rc}")[-300:]
            if a.oom and not a.timed_out:
                err = OOM_ERROR
        if not (a.stopped and not a.timed_out):
            auth_err = _auth_error(a, ok)
            if auth_err:
                err = auth_err
                claude_auth.record(False, auth_err, "turn")
            elif ok and a.result is not None:
                claude_auth.record(True, None, "turn")
        cost = a.turn_cost if a.turn_cost is not None else res.get("total_cost_usd")
        with store.edit(self.sid) as m:
            if a.thread_total is not None and a.csid:
                m["thread_cost"] = {"csid": a.csid, "total": a.thread_total}
            m["turns"] = int(m.get("turns") or 0) + 1
            m["cost_usd"] = round(float(m.get("cost_usd") or 0) + float(cost or 0), 6)
            if a.result is not None:
                store.add_usage(m, res.get("usage"), float(cost or 0), time.time())
            if a.real_model:
                m["real_model"] = a.real_model
            if a.start_s is not None:                  # Stats: how fast turns start (last LATENCY_KEPT turns)
                lat = [x for x in (m.get("latency") or []) if isinstance(x, list)]
                m["latency"] = (lat + [[a.start_s, a.first_s]])[-LATENCY_KEPT:]
            if a.context_tokens is not None:
                m["context_tokens"] = a.context_tokens
                if a.fresh and a.first_context:        # first answer of a thread: system prompt, CLAUDE.md, memory
                    m["base_tokens"] = a.first_context
            if a.result is not None:
                store.record_windows(a.result)
                cw = store.context_window_of(a.result, a.real_model)
                if cw:
                    m["context_window"] = cw
            if a.final_text.strip():
                m["last_text"] = a.final_text.strip()[:200]
            m["error"] = err
            m["updated"] = m["finished_at"] = time.time()
            # which item this turn ran: on_turn_end callbacks answer only their own turns (never a summary)
            m["last_turn"] = {"id": self.turn_id, "kind": item.get("kind") or "user",
                              "source": item.get("source") or "web", "refs": list(item.get("refs") or [])}
            if not m.get("title"):
                m["title"] = " ".join((item.get("text") or "").split())[:60] or "Untitled"
            if m.get("cron") and err is None and not m.get("queue"):
                m["archived"] = True                   # successful cron sessions fold away
        return err

    # ---- compact / handoff ---------------------------------------------------------------
    def _post(self, item: dict, a: Attempt, err: str | None) -> None:
        kind = item.get("kind")
        summary = a.final_text.strip()
        if kind == "compact":
            if err is None and summary and not a.stopped:
                seed = SEED_COMPACT.format(summary=summary)
                with store.edit(self.sid) as m:
                    m["csid"], m["fresh"] = str(uuid.uuid4()), True
                    q = m.get("queue") or []
                    if item.get("idle") and q and (q[0].get("kind") or "user") == "user":
                        q[0]["preface"] = seed             # idle compaction: the message itself carries the seed
                        m["queue"] = q
                    else:
                        m["queue"] = [_seed(seed)] + q
                self.note("Context compacted: Harness continues in a fresh thread seeded with the summary "
                          "above; the history stays displayed here.")
            else:
                self.note("Compaction impossible (the summary turn failed) - session unchanged.", "warn")
        elif kind == "handoff":
            self._handoff(item.get("target") or "", summary if err is None and not a.stopped else "")

    def _handoff(self, target: str, summary: str) -> None:
        if not summary or not store.is_valid_id(target) or store.read(target) is None:
            self.note("Handoff impossible (the summary turn failed) - session kept.", "warn")
            if store.is_valid_id(target):
                self._start_target(target, None)       # messages sent to the continuation meanwhile run now
            return
        title = (store.read(self.sid) or {}).get("title") or self.sid[:8]
        self._start_target(target, _seed(SEED_HANDOFF.format(title=title, summary=summary)))
        store.update(self.sid, archived=True)
        self.note(f"Summary handed over to session '{(store.read(target) or {}).get('title', '')}' - "
                  "this session is archived.")


    @staticmethod
    def _start_target(target: str, seed: dict | None) -> None:
        """Ends the hand-off hold of the continuation: the seed goes FIRST (messages the user sent to it meanwhile
        were held behind it, service._enqueue) and its runner starts unless one is already running."""
        try:
            with store.edit(target) as t:
                t.pop("handoff_pending", None)
                t["queue"] = ([seed] if seed else []) + (t.get("queue") or [])
                go = bool(t["queue"]) and not (t.get("state") == "running" and store.runner_alive(target, t))
                if go:
                    t["state"], t["spawned_at"], t["error"] = "running", time.time(), None
                t["updated"] = time.time()
        except (KeyError, OSError):
            return
        if not go:
            return
        try:
            store.update(target, unit=spawn.start(target))
        except Exception as e:
            store.update(target, state="error", error=f"spawn failed: {e}"[:300], spawned_at=None)


# ---- helpers -----------------------------------------------------------------------------

def _oom_kills() -> int | None:
    """oom_kill counter of the runner's cgroup (its turn unit; Claude runs in it), None when unreadable."""
    try:
        rel = next(line[3:].strip() for line in Path("/proc/self/cgroup").read_text().splitlines()
                   if line.startswith("0::"))
        for line in (CGROUP_FS / rel.lstrip("/") / "memory.events").read_text().splitlines():
            k, _, v = line.partition(" ")
            if k == "oom_kill":
                return int(v)
    except (OSError, ValueError, StopIteration):
        pass
    return None


def _stderr_tail(stream, chunks: list[str]) -> None:
    """Drain stderr continuously but keep only its end: a very noisy Claude process must not grow
    the runner's memory without limit."""
    keep = 0
    for line in iter(stream.readline, ""):
        chunks.append(line)
        keep += len(line)
        while keep > STDERR_TAIL * 4 and len(chunks) > 1:
            keep -= len(chunks.pop(0))

def build_prompt(item: dict) -> str:
    """User text + absolute paths of the attachments (Claude reads them with its Read tool)."""
    text = item.get("text") or ""
    files = [str(p) for p in item.get("attachments") or [] if p]
    if files:
        text = (text + "\n\n" if text else "") + "Attached files:\n" + "\n".join(f"- {p}" for p in files)
    if item.get("hud"):
        text = HUD_PREFACE + text
    if item.get("plan_approved"):
        text = PLAN_APPROVED_PREFACE + text
    if item.get("steer"):
        text = STEER_PREFACE + text
    if item.get("preface"):                            # the seed of an idle compaction (not displayed)
        text = item["preface"] + "\n\n" + text
    return text


VOICE_WAIT_S = 1800.0                                  # a transcription never holds the session longer than this
VOICE_POLL_S = 0.5
VOICE_PREFACE = ("[Voice message from the user, transcribed automatically on the server (speech-to-text: it may "
                 "contain recognition errors - read it for its meaning). Original audio: {paths}]")


STEER_PREFACE = ("[The user interrupted your previous turn to add the message below while you were working. "
                 "Your work so far is kept: take this message into account and continue the task from where "
                 "you stopped - do not start over, and do not redo what is already done.]\n\n")


INLINE_IMAGE_MAX = 3_500_000   # bytes (the API takes 5 MB of base64)
INLINE_IMAGE_SIDE = 8000       # px (the API refuses larger images; Read would have resized them)
INLINE_IMAGES = 4


def image_info(head: bytes) -> tuple[str, int, int] | None:
    """(media type, width, height) read from the first bytes of a PNG / GIF / WebP / JPEG, else None.
    The type comes from the content, never from the extension (the API rejects a mismatch)."""
    if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
        return "image/png", int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", int.from_bytes(head[6:8], "little"), int.from_bytes(head[8:10], "little")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        kind = head[12:16]
        if kind == b"VP8 " and head[23:26] == b"\x9d\x01\x2a":
            return ("image/webp", int.from_bytes(head[26:28], "little") & 0x3FFF,
                    int.from_bytes(head[28:30], "little") & 0x3FFF)
        if kind == b"VP8L" and head[20:21] == b"\x2f":
            b = int.from_bytes(head[21:25], "little")
            return "image/webp", (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
        if kind == b"VP8X":
            return ("image/webp", int.from_bytes(head[24:27], "little") + 1,
                    int.from_bytes(head[27:30], "little") + 1)
        return None
    if head[:3] == b"\xff\xd8\xff":                        # JPEG: walk the segments to the frame header
        i = 2
        while i + 9 < len(head):
            if head[i] != 0xFF:
                return None
            marker = head[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            size = int.from_bytes(head[i + 2:i + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return "image/jpeg", int.from_bytes(head[i + 7:i + 9], "big"), int.from_bytes(head[i + 5:i + 7], "big")
            i += 2 + size
    return None


def inline_image(path: str, root: Path) -> dict | None:
    """An image content block for an attachment, or None (it stays a path Claude opens with Read): only
    real PNG/GIF/WebP/JPEG files inside the workspace (the permission mode applies to anything else), at
    most INLINE_IMAGE_MAX bytes and INLINE_IMAGE_SIDE px per side."""
    try:
        p = Path(path).resolve()
        if root not in p.parents or not p.is_file() or p.stat().st_size > INLINE_IMAGE_MAX:
            return None
        data = p.read_bytes()
    except OSError:
        return None
    info = image_info(data[:65536])
    if not info or not (0 < info[1] <= INLINE_IMAGE_SIDE and 0 < info[2] <= INLINE_IMAGE_SIDE):
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": info[0],
                                         "data": base64.b64encode(data).decode("ascii")}}


def effective_mode(meta: dict, cfg: dict) -> str:
    """Permission mode of a turn: the session's own (set by its cron), else its topic's, else the global setting."""
    from .. import workspace
    return (meta.get("permission_mode") or workspace.topic_permission_mode(meta.get("path") or "")
            or cfg.get("permission_mode") or "bypass")


def stdin_payload(prompt: str, item: dict, root: Path | None = None) -> tuple[str, bool]:
    """What the claude process reads on stdin -> (payload, json_in). HUD messages carry their images inline
    (stream-json input): Claude sees the screen in its first step instead of opening each file with Read
    (one model round trip saved, ~2-3 s). The paths stay listed in the text (Claude annotates copies)."""
    if not item.get("hud"):
        return prompt, False
    if root is None:
        root = Path(config.load_config().get("workspace") or "/").resolve()
    blocks: list[dict] = []
    for raw in item.get("attachments") or []:
        if len(blocks) >= INLINE_IMAGES:
            break
        block = inline_image(str(raw), root)
        if block:
            blocks.append(block)
    if not blocks:
        return prompt, False
    msg = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": prompt}, *blocks]}}
    return json.dumps(msg) + "\n", True


PLAN_PREFACE = ("[Plan mode is on: you must not create, edit or delete files nor run commands that change "
                "anything - the tools refuse it. Explore what you need (read files, search, read-only commands), "
                "then answer with the complete plan in Markdown, in the user's language: goal, steps, files "
                "concerned, risks and open questions. Your final answer must contain the whole plan: the user "
                "reads it there and either validates it or asks for changes (then send the updated plan in full). "
                "Implement nothing before it is validated.]\n\n")
PLAN_APPROVED_PREFACE = ("[The user validated your plan: plan mode is off, you can now edit files and run "
                         "commands. Implement the latest version of the plan you proposed, then report what you "
                         "did.]\n\n")


HUD_PREFACE = ("[Sent from the HUD: a small floating window over the user's screen that shows your final answer "
               "and the images whose absolute paths you write in it. Lead with the result and keep it short. "
               "The attached images included in this message are already in front of you: do not Read those. "
               "If a screen capture is attached and pointing at something on it helps (where to click, what is "
               "wrong), draw on a copy of it - arrows, boxes, numbers in a bright color, e.g. with ImageMagick - "
               "save it next to the capture with an '-annotated' suffix and write its absolute path in your answer. "
               "Never edit the original capture.]\n\n")


def _idle_compact(m: dict, item: dict, cfg: dict, now: float) -> tuple[str, int] | None:
    """Idle compaction: (time away, context in k tokens) when a user message comes back to a big session whose
    prompt cache has expired (last call more than `idle_compact_after_s` ago). The history would be re-sent
    uncached anyway: summarizing it now costs that once, and every later turn starts from a small seed."""
    limit = int(cfg.get("idle_compact_tokens") or 0)
    after = float(cfg.get("idle_compact_after_s") or 0)
    ctx = int(m.get("context_tokens") or 0)
    last = max(float(m.get("finished_at") or 0), float(m.get("cache_at") or 0))
    if limit <= 0 or after <= 0 or not last or ctx < max(limit, IDLE_COMPACT_MIN) or now - last < after:
        return None
    base = int(m.get("base_tokens") or 0)              # what a fresh thread costs anyway (CLAUDE.md, memory...)
    if base and ctx - base < max(limit, IDLE_COMPACT_MIN) // 2:
        return None                                    # mostly fixed context: a summary would save nothing
    if (item.get("kind") or "user") != "user" or item.get("source") in ("system", "cron") or item.get("steer") \
            or item.get("plan_approved"):
        return None
    if m.get("fresh", True) or m.get("cron") or m.get("plan_ready"):
        return None
    away = now - last
    hours = f"{away / 3600:.0f} h" if away >= 5400 else f"{away / 60:.0f} min"
    return hours, ctx // 1000


def _seed(text: str) -> dict:
    return {"text": text, "attachments": [], "source": "system", "kind": "seed", "at": time.time()}


STDOUT_GRACE_S = float(os.environ.get("MAXXING_STDOUT_GRACE_S") or 10)


UPDATE_LOCK = ".claude-update.lock"     # maxxing.claude_update holds it (exclusive) while it updates Claude Code
UPDATE_WAIT_S = 420


def _claude_in_use(note: Callable[..., None] | None = None) -> int | None:
    """A shared flock on <state>/.claude-update.lock (fd, closed by the caller), waiting for an update in progress
    (at most UPDATE_WAIT_S, said in the session through `note`). None when there is no state dir: the turn runs
    anyway."""
    import fcntl
    try:
        fd = os.open(config.STATE / UPDATE_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return None
    end = time.time() + UPDATE_WAIT_S
    told = False
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.time() >= end:
                if note:
                    note("The Claude Code update is still running: this turn starts anyway.", "warn")
                return fd                              # a stuck update must not stop the turns
            if not told and note:
                told = True
                note(f"Claude Code is being updated: this turn starts as soon as it is done "
                     f"(at most {UPDATE_WAIT_S // 60} min).")
            time.sleep(0.5)
        except OSError:
            return fd


def _lines_until_exit(p: subprocess.Popen) -> Iterator[str]:
    """Claude's stdout lines until EOF - or until STDOUT_GRACE_S after Claude exited: a program it started in the
    background (its own session, not in Claude's process group) can keep the pipe open forever, and the turn would
    then never end (session "running" for good)."""
    q: queue.Queue[str | None] = queue.Queue(maxsize=10000)

    def pump() -> None:
        try:
            for raw in p.stdout:                       # type: ignore[union-attr]
                q.put(raw)
        except (OSError, ValueError):
            pass
        finally:
            q.put(None)
    threading.Thread(target=pump, daemon=True).start()
    gone: float | None = None
    while True:
        try:
            raw = q.get(timeout=0.5)
        except queue.Empty:
            raw = ""
        if raw is None:
            return
        if raw:
            yield raw
        # checked on every pass: a background program that keeps writing must not hold the turn open either
        if p.poll() is not None:
            gone = gone or time.monotonic()
            if time.monotonic() - gone >= STDOUT_GRACE_S:
                print("claude exited but its output stayed open (a background program): turn ended", file=sys.stderr)
                return


def _feed(p: subprocess.Popen, prompt: str) -> None:
    try:
        p.stdin.write(prompt)
        p.stdin.close()
    except (OSError, ValueError):
        pass


def _parse(line: str) -> dict | None:
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    return ev if isinstance(ev, dict) else None


def _auth_error(a: Attempt, ok: bool) -> str | None:
    """Sign-in failure seen in this turn ("OAuth session expired…", "Invalid API key…"), else None.
    Only failed turns, or a short synthetic answer (no real model), are inspected - never what
    Claude writes about authentication in a normal answer."""
    res = a.result or {}
    if not ok or res.get("is_error"):
        errors = res.get("errors") if isinstance(res.get("errors"), list) else []
        parts = [a.stderr, *map(str, errors), str(res.get("result") or ""), a.final_text]
    elif a.real_model is None and len(a.final_text) < 300:
        parts = [a.final_text]
    else:
        return None
    return claude_auth.detect("\n".join(p for p in parts if p))


def _resume_lost(a: Attempt) -> bool:
    errs = (a.result or {}).get("errors") if a.result else None
    text = a.stderr + " " + " ".join(str(e) for e in errs or [])
    return bool(RESUME_LOST.search(text))


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not store.is_valid_id(argv[1]):
        print("usage: python -m maxxing.sessions.runner <session-id>", file=sys.stderr)
        return 2
    if store.read(argv[1]) is None:
        return 1
    return Runner(argv[1]).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
