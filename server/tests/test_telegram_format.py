"""Every kind of outgoing Telegram message: markdown rendered, valid HTML, the start of long texts kept."""
from __future__ import annotations

import re
import sys
import types

import pytest

from maxxing import crons
from maxxing.telegram import format as fmt
from maxxing.telegram import gateway
from _conn_helpers import mx_state  # noqa: F401  (fixture)

RADAR = """**Ce qui a été fait :**

| Constat | Correctif | Résultat |
|---|---|---|
| r4dee1c7e, champs de saisie | les champs faisaient déjà 44 px | bouton œil 40×44 → 44×44 |
| refa4845a, menu des Réglages | pastilles à 40 px | surlignage aligné \\| actif |

**Vérifications :**
- La suite serveur passe : 890 ok, 2 ignorés.
- La vérification de types (`tsc`) passe.
""" + "\n".join(f"- ligne de détail numéro {i} avec un peu de texte" for i in range(400))

RAW = re.compile(r"\*\*|(?<!ˋ)`|^\s*\|", re.M)


def _balanced(h: str) -> bool:
    for tag in ("b", "i", "pre", "code", "blockquote", "a", "s"):
        if len(re.findall(rf"<{tag}[ >]", h)) != h.count(f"</{tag}>"):
            return False
    return True


@pytest.fixture
def posted(mx_state, monkeypatch):
    out: list[tuple[str, list[str], bool]] = []
    monkeypatch.setattr(gateway, "_post", lambda key, parts, silent, markup=None: out.append((key, parts, silent)))
    return out


def test_table_becomes_a_readable_list():
    html = fmt.to_html(RADAR[:400])
    assert "• <b>r4dee1c7e, champs de saisie</b>\n   <i>Correctif</i>: les champs faisaient déjà 44 px" in html
    assert "surlignage aligné | actif" in html and not RAW.search(html)


def test_huge_table_is_split_into_valid_messages():
    md = "| a | b |\n|---|---|\n" + "\n".join(f"| row {i} | {'x & y ' * 30} |" for i in range(200))
    msgs = fmt.render(md)
    assert len(msgs) > 1 and all(len(m) <= fmt.LIMIT and _balanced(m) for m in msgs)
    assert "row 0" in msgs[0] and "row 199" in msgs[-1]


def test_head_and_tail_cut_on_boundaries():
    text = "\n".join(f"line {i} with words" for i in range(100))
    h = fmt.head(text, 200)
    assert h.startswith("line 0 ") and h.endswith("\n…") and len(h) <= 202
    assert all(ln.startswith("line ") or ln == "…" for ln in h.split("\n"))
    t = fmt.tail(text, 200)
    assert t.startswith("…\nline ") and t.endswith("line 99 with words")
    assert fmt.head("one word", 50) == "one word" and fmt.head("abc " * 100, 21).endswith("abc…")


def test_preview_is_one_clean_line():
    p = fmt.preview(RADAR, 120)
    assert "\n" not in p and "**" not in p and "|" not in p and "`" not in p
    assert p.startswith("Ce qui a été fait : · Constat") and len(p) <= 120 and p.endswith("…")


def test_claude_cron_report_keeps_its_start_and_renders_markdown(posted):
    gateway.notify_cron_report("OK - Radar – PR (16 min 55 s)", RADAR, markdown=True, loud=False)
    key, parts, silent = posted[-1]
    assert key == gateway.CRONS and silent is True                 # a success does not ring
    assert parts[0].startswith("<b>OK - Radar – PR (16 min 55 s)</b>\n\n<b>Ce qui a été fait :</b>")
    assert all(len(p) <= fmt.LIMIT and _balanced(p) and not RAW.search(p) for p in parts)
    assert "<code>tsc</code>" in "".join(parts) and "ligne de détail numéro 0 " in "".join(parts)
    assert sum(len(fmt.strip_tags(p)) for p in parts) <= gateway.REPORT_MAX + 200


def test_shell_cron_report_is_code_and_disabled_reports_are_not_sent(posted, monkeypatch):
    gateway.notify_cron_report("FAILED (code 3) - backup", "rsync: <error> & co", markdown=False)
    _, parts, silent = posted[-1]
    assert parts == ["<b>FAILED (code 3) - backup</b>\n<pre>rsync: &lt;error&gt; &amp; co</pre>"] and silent is False
    gateway.notify_cron_report("OK - quiet", "")
    assert posted[-1][1] == ["<b>OK - quiet</b>"]
    monkeypatch.setattr(gateway, "tg_config", lambda: {"notify_crons": False})
    n = len(posted)
    gateway.notify_cron_report("OK - x", "y")
    assert len(posted) == n


def test_feed_body_and_finished_preview_are_rendered(mx_state):
    text, _ = gateway.feed_message({"id": 1, "title": "Cron failed: Radar", "body": "**Erreur** dans `build`",
                                    "level": "error", "source": "crons"})
    assert "<b>Erreur</b> dans <code>build</code>" in text
    html = gateway.finished_message({"id": "s1", "title": "Audit", "state": "idle", "last_text": RADAR})
    assert "**" not in html and "|" not in html and len(fmt.strip_tags(html)) < 400 and _balanced(html)


def test_status_never_loses_its_closing_tag():
    steps = [{"text": "x" * 41, "state": "ok"}] * 400
    for final in (None, "ok"):
        h = gateway.render_status(steps, [], 10, final)
        assert len(h) <= 4000 and h.endswith("</blockquote>")


@pytest.fixture
def report_job(mx_state, monkeypatch):
    sent: list[tuple] = []
    gw = types.ModuleType("maxxing.telegram.gateway")
    gw.notify_cron_report = lambda header, body="", markdown=True, loud=True: sent.append((header, body, markdown, loud))
    monkeypatch.setitem(sys.modules, "maxxing.telegram.gateway", gw)
    import maxxing.telegram as tpkg
    monkeypatch.setattr(tpkg, "gateway", gw, raising=False)
    monkeypatch.setattr(crons, "_feed", lambda job, run: None)
    return sent


def test_cron_notify_sends_the_whole_answer_from_its_start(report_job):
    job = {"name": "Radar – PR", "kind": "claude", "notify": "always"}
    run = {"ok": True, "code": 0, "duration_s": 1015, "output_tail": crons._clip_head(RADAR, crons.OUTPUT_TAIL)}
    crons._notify(job, run, RADAR)
    header, body, markdown, loud = report_job[-1]
    assert header == "OK - Radar – PR (16 min 55 s)" and body == RADAR.strip() and markdown and not loud
    assert run["output_tail"].startswith("**Ce qui a été fait") and len(run["output_tail"]) <= crons.OUTPUT_TAIL + 2


def test_cron_notify_shell_failure_keeps_the_end_on_a_line(report_job):
    out = "\n".join(f"step {i}" for i in range(300)) + "\nERROR: disk full"
    crons._notify({"name": "backup", "kind": "shell", "notify": "failure"},
                  {"ok": False, "code": 1, "duration_s": 3, "output_tail": out})
    header, body, markdown, loud = report_job[-1]
    assert header.startswith("FAILED (code 1) - backup") and not markdown and loud
    assert body.startswith("…\nstep ") and body.endswith("ERROR: disk full") and len(body) <= 603
