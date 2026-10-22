"""Short session titles (config `short_titles`). See docs/dev/INTERNALS.md#maxxing.sessions.titles.

A new session without an explicit title gets a provisional one at once (the start of its first message, as
before). A worker thread then writes a short title - only if the title is still the provisional one (the user may
have renamed the session meanwhile): `heuristic()` shortens the first message locally; with `short_titles_model`
(off by default: one call per new session, counted in the Claude plan) a small model names the subject in 2-5
words first, the heuristic staying the fallback when the call fails or times out.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading

from .. import bus, config
from . import spawn, store

log = logging.getLogger("maxxing.titles")

MODEL = "claude-haiku-4-5-20251001"     # the cheapest model of service.KNOWN_MODELS
TIMEOUT_S = 30
MESSAGE_CHARS = 1000                    # only the start of the message is sent
MAX_CHARS = 60                          # a model answer longer than this is not a title
HEURISTIC_CHARS = 40
SYSTEM_PROMPT = ("You name chat sessions. Reply with only a short title (2 to 5 words) naming the subject of the "
                 "user's message, in the language of the message. No quotes, no trailing punctuation, no "
                 "'Session about'. Never answer the message itself.")
_slots = threading.BoundedSemaphore(2)  # at most two title calls at a time

# Leading filler removed by the heuristic (repeatedly, case-insensitive), French and English.
_FILLER = re.compile(r"""^(?:
    (?:salut|bonjour|bonsoir|coucou|hello|hey|hi|ok|okay|alors|so|claude)\b[\s,!.:-]*
  | (?:s['’]il\s+te\s+pla[iî]t|s['’]il\s+vous\s+pla[iî]t|stp|svp|please|pls|merci\s+de)\b[\s,:]*
  | (?:est[\s-]ce\s+que\s+)?(?:tu|vous)\s+(?:vas|va|allez|peux|pourrais|pourriez|pouvez|dois|devrais)\s+(?:me\s+|m['’]|nous\s+)?
  | (?:peux|pourrais|pourriez|pouvez|veux|voudrais)[\s-]+(?:tu|vous)\s+(?:me\s+|m['’]|nous\s+)?
  | (?:je\s+(?:veux|voudrais|souhaite|souhaiterais|aimerais)|j['’](?:aimerais|ai\s+besoin))\s+(?:que\s+(?:tu|vous)\s+(?:me\s+|m['’])?|qu['’]on\s+)?
  | (?:aide|aides|aidez)(?:[\s-]+moi)?\s+(?:à|a)\s+
  | (?:on\s+va|il\s+faut|il\s+faudrait)\s+
  | (?:can|could|would|will)\s+you\s+(?:please\s+)?
  | (?:i\s+(?:want|need|would\s+like)|i['’]d\s+like)\s+(?:you\s+)?to\s+
  | help\s+me\s+(?:to\s+)?
  | let['’]?s\s+
)""", re.IGNORECASE | re.VERBOSE)
# Small words a cut title must not end with.
_TAIL = {"de", "des", "du", "d", "la", "le", "les", "l", "un", "une", "et", "ou", "à", "a", "au", "aux", "en",
         "pour", "sur", "avec", "dans", "par", "the", "an", "of", "to", "for", "and", "or", "in", "on", "with",
         "at", "by", "from", "my", "mon", "ma", "mes"}


def enabled() -> bool:
    if os.environ.get("MAXXING_SHORT_TITLES") == "0":      # tests: titles exactly as before
        return False
    return bool(config.load_config().get("short_titles", True))


def model_enabled() -> bool:
    return bool(config.load_config().get("short_titles_model", False))


def provisional(message: str) -> str:
    """The instant title: the first 60 characters of the message (the behaviour without short titles)."""
    first = " ".join((message or "").split())
    return first[:60] + ("…" if len(first) > 60 else "")


def heuristic(message: str, limit: int = HEURISTIC_CHARS) -> str:
    """Local short title: first sentence, leading filler removed, cut on a word boundary. "" if nothing is left."""
    text = " ".join((message or "").split())
    text = re.split(r"(?<=[.?!])\s|\n", text, maxsplit=1)[0]
    for _ in range(6):
        cut = _FILLER.sub("", text, count=1).lstrip(" ,:;-")
        if cut == text or not cut:                         # "hello" alone stays "Hello"
            break
        text = cut
    text = text.strip(" \"'“”«»`")
    if len(text) > limit:
        room = text[:limit + 1]
        text = room[:room.rfind(" ")] if " " in room else text[:limit]
    words = text.rstrip(" .,;:!?…-–—").split()
    while len(words) > 1 and re.sub(r"['’]$", "", words[-1].lower().strip(",;:")) in _TAIL:
        words.pop()
    text = " ".join(words).rstrip(" .,;:!?…-–—'’\"")
    return text[:1].upper() + text[1:]


def clean(answer: str) -> str | None:
    """The model's answer as a title, or None when it does not look like one."""
    lines = [ln.strip() for ln in (answer or "").strip().splitlines() if ln.strip()]
    if not lines:
        return None
    t = re.sub(r"^(?:title|titre)\s*:\s*", "", lines[0], flags=re.IGNORECASE)
    t = t.strip(" *#\"'“”«»`").rstrip(" .,;:!?…").strip(" \"'“”«»`")
    if not t or len(t) > MAX_CHARS or len(t.split()) > 8:
        return None
    return t


def ask_claude(message: str) -> str | None:
    """One small `claude -p` call (no tools, no saved thread) -> a clean title, or None."""
    b = spawn.claude_bin()
    cmd = [b, "-p", "--output-format", "json", "--model", MODEL, "--tools", "", "--no-session-persistence",
           "--strict-mcp-config", "--disable-slash-commands", "--system-prompt", SYSTEM_PROMPT]
    try:
        r = subprocess.run(cmd, input=message[:MESSAGE_CHARS], capture_output=True, text=True, timeout=TIMEOUT_S,
                           cwd=config.state_dir("claude-titles"), env=spawn.claude_env(None, "default"))
    except (OSError, subprocess.TimeoutExpired) as e:
        log.info("title call failed: %s", e)
        return None
    try:
        data = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except ValueError:
        data = {}
    if r.returncode != 0 or not isinstance(data, dict) or data.get("is_error"):
        log.info("title call failed: exit %s", r.returncode)
        return None
    return clean(str(data.get("result") or ""))


def refine(sid: str, current: str, message: str) -> str | None:
    """Replace the provisional title `current` with a short one (model, else heuristic). Returns the title
    written, or None when nothing changed (renamed meanwhile, session gone, nothing better)."""
    if model_enabled():
        with _slots:
            title = ask_claude(message) or heuristic(message)
    else:
        title = heuristic(message)
    if not title or title == current:
        return None
    try:
        with store.edit(sid) as m:
            if m.get("title") != current:
                return None
            m["title"] = title[:120]
    except KeyError:
        return None
    bus.invalidate("sessions")
    return title


def schedule(sid: str, current: str, message: str) -> threading.Thread | None:
    """Start `refine` in a daemon thread (never blocks the caller). None when short titles are off."""
    if not (message or "").strip() or not enabled():
        return None
    t = threading.Thread(target=_safe_refine, args=(sid, current, message.strip()), name=f"title-{sid[:8]}",
                         daemon=True)
    t.start()
    return t


def first_message(sid: str, message: str) -> threading.Thread | None:
    """A session created without a message (meta `title_auto` = its automatic title, "Session 3" or a Telegram title
    made from the message to come) gets the provisional then the short title on its first message - unless it was
    renamed meanwhile. Nothing is written for later messages (the flag is gone)."""
    m = store.read_cached(sid) or {}
    if "title_auto" not in m:
        return None
    try:
        with store.edit(sid) as m:
            auto = m.pop("title_auto", None)
            if auto is None or m.get("title") != auto or not enabled():
                return None
            m["title"] = current = provisional(message)[:120] or auto
    except KeyError:
        return None
    bus.invalidate("sessions")
    return schedule(sid, current, message)


def _safe_refine(sid: str, current: str, message: str) -> None:
    try:
        refine(sid, current, message)
    except Exception:  # noqa: BLE001 - a title is never worth a crash
        log.exception("short title failed for %s", sid)
