"""Markdown (Claude output) -> Telegram HTML, split into <= 4096-character messages.

Telegram's HTML mode supports a small subset: <b> <i> <u> <s> <code> <pre> <a href> <blockquote>.
Only `<`, `>` and `&` need escaping, which makes it far more robust than MarkdownV2 for arbitrary
model output.

Strategy: the markdown is cut into *blocks* (fenced code, tables, paragraphs/lists) first, each
block is rendered on its own (so a tag never spans two blocks), then blocks are packed greedily
into messages. A block larger than the limit is split on line boundaries (code blocks are
re-opened in every piece) and, as a last resort, on characters.
"""
from __future__ import annotations

import html
import re

LIMIT = 4096

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([\w+#.-]*)\s*$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_TASK = re.compile(r"^\[([ xX])\]\s+(.*)$")


def escape(text: str) -> str:
    """Escape the three characters Telegram HTML cares about."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_url(url: str) -> str | None:
    url = url.strip().strip("<>")
    if re.match(r"^(https?|tg|mailto):", url, re.I):
        return html.escape(url, quote=True)
    return None


INLINE_MAX = 2000  # the lazy `(.+?)` patterns are quadratic: a longer line is sent as plain text


def inline(text: str) -> str:
    """Render inline markdown (code, links, bold, italic, strike) of one line/paragraph."""
    if len(text) > INLINE_MAX:
        return escape(text.replace("\x00", ""))
    slots: list[str] = []

    def keep(fragment: str) -> str:
        slots.append(fragment)
        return f"\x00{len(slots) - 1}\x00"

    text = text.replace("\x00", "")
    # inline code (``a`b`` or `a`) - content is verbatim
    text = re.sub(r"(`+)(.+?)\1", lambda m: keep(f"<code>{escape(m.group(2).strip())}</code>"), text)

    # links [label](url) and autolinks <https://…>
    def _link(m: re.Match) -> str:
        url = _safe_url(m.group(2))
        label = inline(m.group(1)) if m.group(1) else escape(m.group(2))
        return keep(f'<a href="{url}">{label}</a>') if url else keep(escape(m.group(0)))

    text = re.sub(r"!?\[([^\]\n]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", _link, text)
    text = re.sub(r"<((?:https?|mailto):[^>\s]+)>",
                  lambda m: keep(f'<a href="{_safe_url(m.group(1))}">{escape(m.group(1))}</a>'), text)

    text = escape(text)
    text = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w])__(?=\S)(.+?)(?<=\S)__(?![\w])", r"<b>\1</b>", text)
    text = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<s>\1</s>", text)
    text = re.sub(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![\w])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w])", r"<i>\1</i>", text)
    text = _nest(text)
    # restore protected fragments (nested slots from link labels resolve recursively)
    for _ in range(3):
        if "\x00" not in text:
            break
        text = re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], text)
    return text


_EMPH_TAG = re.compile(r"</?[bis]>")


def _nest(text: str) -> str:
    """Crossed markers (`**a *b** c*`) give crossed tags, which Telegram refuses: close the inner tags before
    the outer one ends and reopen them after. Only our tags can match (the text itself is escaped)."""
    out: list[str] = []
    stack: list[str] = []
    pos = 0
    for m in _EMPH_TAG.finditer(text):
        out.append(text[pos:m.start()])
        pos = m.end()
        tag = m.group(0).strip("</>")
        if not m.group(0).startswith("</"):
            stack.append(tag)
            out.append(m.group(0))
            continue
        if tag not in stack:
            continue
        crossed: list[str] = []
        while stack[-1] != tag:
            crossed.append(stack.pop())
            out.append(f"</{crossed[-1]}>")
        stack.pop()
        out.append(m.group(0))
        for t in reversed(crossed):
            stack.append(t)
            out.append(f"<{t}>")
    out.append(text[pos:])
    out.extend(f"</{t}>" for t in reversed(stack))
    return re.sub(r"<([bis])></\1>", "", "".join(out))


def _code_block(code: str, lang: str) -> str:
    body = escape(code)
    if lang:
        return f'<pre><code class="language-{escape(lang)}">{body}</code></pre>'
    return f"<pre>{body}</pre>"


def _line(raw: str) -> str:
    """Render one non-code line (heading, list item, quote, rule or text)."""
    if _RULE.match(raw):
        return "──────────"
    m = _HEADING.match(raw)
    if m:
        return f"<b>{inline(m.group(1))}</b>"
    m = _BULLET.match(raw)
    if m:
        indent = "  " * (len(m.group(1).expandtabs(2)) // 2)
        item = m.group(2)
        t = _TASK.match(item)
        if t:
            return f"{indent}{'☑' if t.group(1).strip() else '☐'} {inline(t.group(2))}"
        return f"{indent}• {inline(item)}"
    m = _NUMBERED.match(raw)
    if m:
        indent = "  " * (len(m.group(1).expandtabs(2)) // 2)
        return f"{indent}{m.group(2)}. {inline(m.group(3))}"
    return inline(raw)


# ---- blocks -------------------------------------------------------------------------------
# A block is (kind, payload): ("code", (lang, code)), ("table", text), ("quote", [lines]),
# ("text", [lines]). Blank lines separate text blocks.
Block = tuple


def blocks(md: str) -> list[Block]:
    """Cut markdown into renderable blocks."""
    out: list[Block] = []
    lines = md.replace("\r\n", "\n").split("\n")
    i, n = 0, len(lines)
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(("text", list(para)))
            para.clear()

    while i < n:
        ln = lines[i]
        fm = _FENCE.match(ln)
        if fm:
            flush()
            fence, lang = fm.group(1), fm.group(2)
            j = i + 1
            body: list[str] = []
            while j < n and not (lines[j].strip().startswith(fence[0] * len(fence))
                                 and lines[j].strip().strip(fence[0]) == ""):
                body.append(lines[j])
                j += 1
            out.append(("code", (lang, "\n".join(body))))
            i = j + 1
            continue
        if ln.lstrip().startswith("|") and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            flush()
            j = i
            rows: list[str] = []
            while j < n and lines[j].strip().startswith("|"):
                rows.append(lines[j].strip())
                j += 1
            out.append(("table", "\n".join(rows)))
            i = j
            continue
        if _QUOTE.match(ln):
            flush()
            q: list[str] = []
            while i < n and _QUOTE.match(lines[i]):
                q.append(_QUOTE.match(lines[i]).group(1))
                i += 1
            out.append(("quote", q))
            continue
        if not ln.strip():
            flush()
        else:
            para.append(ln)
        i += 1
    flush()
    return out


def _render_block(b: Block) -> str:
    kind, payload = b
    if kind == "code":
        return _code_block(payload[1], payload[0])
    if kind == "table":
        return f"<pre>{escape(payload)}</pre>"
    if kind == "quote":
        return "<blockquote>" + "\n".join(_line(x) for x in payload) + "</blockquote>"
    return "\n".join(_line(x) for x in payload)


def to_html(md: str) -> str:
    """Convert a whole markdown text to one Telegram HTML string (no length limit)."""
    return "\n\n".join(_render_block(b) for b in blocks(md or "")).strip()


def _split_big(b: Block, limit: int) -> list[str]:
    """Render a block that does not fit into one message as several valid fragments."""
    kind, payload = b
    if kind in ("code", "table"):
        lang, code = payload if kind == "code" else ("", payload)
        overhead = len(_code_block("", lang))
        pieces: list[str] = []
        cur = ""
        for ln in code.split("\n"):
            add = (cur + "\n" + ln) if cur else ln
            if len(escape(add)) + overhead > limit and cur:
                pieces.append(cur)
                cur = ln
            else:
                cur = add
            while len(escape(cur)) + overhead > limit:        # one gigantic line
                cut = max(1, (limit - overhead) // 5)          # worst case: every char -> &amp;
                pieces.append(cur[:cut])
                cur = cur[cut:]
        if cur:
            pieces.append(cur)
        return [_code_block(p, lang) for p in pieces]
    lines = payload if isinstance(payload, list) else [str(payload)]
    wrap = (lambda s: f"<blockquote>{s}</blockquote>") if kind == "quote" else (lambda s: s)
    frags: list[str] = []
    cur_lines: list[str] = []
    for ln in lines:
        r = _line(ln)
        if len(r) > limit - 30:                                 # split a monster line on chars
            if cur_lines:
                frags.append(wrap("\n".join(cur_lines)))
                cur_lines = []
            step = max(1, (limit - 30) // 5)
            frags.extend(wrap(escape(ln[k:k + step])) for k in range(0, len(ln), step))
            continue
        trial = "\n".join(cur_lines + [r])
        if len(wrap(trial)) > limit and cur_lines:
            frags.append(wrap("\n".join(cur_lines)))
            cur_lines = [r]
        else:
            cur_lines.append(r)
    if cur_lines:
        frags.append(wrap("\n".join(cur_lines)))
    return frags


def render(md: str, limit: int = LIMIT) -> list[str]:
    """Markdown -> list of Telegram HTML messages, each at most `limit` characters.

    Messages are cut between blocks (paragraphs, lists, code blocks) whenever possible, so
    every message is valid HTML on its own.
    """
    frags: list[str] = []
    for b in blocks(md or ""):
        r = _render_block(b)
        frags.extend([r] if len(r) <= limit else _split_big(b, limit))
    msgs: list[str] = []
    cur = ""
    for f in frags:
        if not f.strip():
            continue
        if not cur:
            cur = f
        elif len(cur) + 2 + len(f) <= limit:
            cur += "\n\n" + f
        else:
            msgs.append(cur)
            cur = f
    if cur:
        msgs.append(cur)
    return msgs


def plain(text: str, limit: int = LIMIT) -> list[str]:
    """Escape plain text and split it on line boundaries (for notifications)."""
    out: list[str] = []
    cur = ""
    step = max(1, limit // 5)                    # worst case: every char becomes "&amp;"
    for ln in (text or "").split("\n"):
        parts = [ln] if len(escape(ln)) <= limit else [ln[k:k + step] for k in range(0, len(ln), step)]
        for part in parts:
            e = escape(part)
            if cur and len(cur) + 1 + len(e) > limit:
                out.append(cur)
                cur = e
            else:
                cur = f"{cur}\n{e}" if cur else e
    if cur:
        out.append(cur)
    return out or [""]


def strip_tags(html_text: str) -> str:
    """Fallback when Telegram rejects our HTML: plain text with entities decoded."""
    return html.unescape(re.sub(r"<[^>]+>", "", html_text))
