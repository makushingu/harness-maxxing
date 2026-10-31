"""Smart resume (config `smart_resume_tokens`).  STDLIB ONLY (imported by the runner).

When a user message comes back to a big session after a pause, the next calls re-read the whole history - uncached
once the prompt cache expired. A summary first makes this turn and the next ones start small. A plain summary loses
details the returning message may need, so this one is written FOR that message: the summary turn sees it and keeps,
exact, everything it relies on (paths, commands, values, the plan just discussed, the question asked).

Measured on 30 real returns, each summary judged blind against the turn done with the full history: nothing missing
9 times (plain summary: 2), something important missing once (plain: 2). Tokens of the resumed turn: -11 % at
60-100k (not worth the risk), -38 to -45 % at 100-200k, -67 % from 200k.

  cache expired (pause >= idle_compact_after_s) and context >= smart_resume_tokens     -> targeted summary first
  cache warm (pause >= MIN_PAUSE_S) and context >= WARM_FACTOR x smart_resume_tokens   -> targeted summary first
  otherwise the idle compaction rule (runner._idle_compact, plain summary) - with smart resume on it adds nothing
  unless idle_compact_tokens is set lower.
"""
from __future__ import annotations

MIN_PAUSE_S = 300                       # below this, a message is just the next one of the conversation
WARM_FACTOR = 2                         # cache still warm: re-reading is cheap, only summarize a much bigger thread
MIN_TOKENS = 20_000                     # a lower non-zero setting is raised to this (like idle compaction)
MESSAGE_CHARS = 6000                    # the returning message as shown to the summary turn
SUMMARY_PROMPT = (
    "The user is back after a pause. Summarize this conversation so that a NEW session (same folder, same "
    "CLAUDE.md/memory.md context, but with no memory of this exchange) can answer the user's next message, given "
    "below, as well as if it had the whole history. First, in at most 15 lines: goal, decisions taken, progress, "
    "files touched (paths), what is left to do, known pitfalls. Then, under \"For the next message\": every detail "
    "that message relies on, kept exact (paths, commands, values, error texts, names, the options or plan just "
    "discussed, the question you asked) - as long as needed, nothing unrelated. Do not answer the message. Only the "
    "summary, in the language of this conversation, no preamble.\n\n"
    "The user's next message:\n{message}")


def threshold(cfg: dict) -> int:
    """The context (tokens) from which a return after the cache expired is summarized; 0 = smart resume off."""
    try:
        n = int(cfg.get("smart_resume_tokens") or 0)
    except (TypeError, ValueError, OverflowError):   # hand-edited config: off, never a crashed turn
        return 0
    return max(n, MIN_TOKENS) if n > 0 else 0


def away_text(seconds: float) -> str:
    return f"{seconds / 3600:.0f} h" if seconds >= 5400 else f"{seconds / 60:.0f} min"


def candidate(m: dict, item: dict, cfg: dict, now: float) -> tuple[float, int] | None:
    """(seconds away, context tokens) when the user message `item` coming back to session `m` gets a targeted
    summary first; None otherwise (then the idle rule applies)."""
    limit = threshold(cfg)
    if not limit:
        return None
    if (item.get("kind") or "user") != "user" or item.get("source") in ("system", "cron") or item.get("steer") \
            or item.get("plan_approved") or item.get("held"):
        return None
    if m.get("fresh", True) or m.get("cron") or m.get("plan_ready"):
        return None
    try:
        ctx = int(m.get("context_tokens") or 0)
        last = max(float(m.get("finished_at") or 0), float(m.get("cache_at") or 0))
        base = int(m.get("base_tokens") or 0)          # what a fresh thread costs anyway (CLAUDE.md, memory...)
        after = float(cfg.get("idle_compact_after_s") or 3600)
    except (TypeError, ValueError, OverflowError):     # a hand-edited value: no summary, never a crashed turn
        return None
    if not last or ctx < limit or now - last < MIN_PAUSE_S:
        return None
    if base and ctx - base < limit // 2:
        return None                                    # mostly fixed context: a summary would save nothing
    if now - last < after and ctx < limit * WARM_FACTOR:
        return None                                    # cache still warm and a medium context: just go on
    return now - last, ctx


def summary_prompt(message: str) -> str:
    text = (message or "").strip() or "(no text, only attachments)"
    if len(text) > MESSAGE_CHARS:
        half = (MESSAGE_CHARS - 3) // 2
        text = text[:half] + " … " + text[-half:]
    return SUMMARY_PROMPT.format(message=text)
