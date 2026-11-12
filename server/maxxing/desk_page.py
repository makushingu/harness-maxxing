"""The front desk's public chat page (GET /desk/<token>): one static document, no third-party code, no cookie.

An unauthenticated surface: the page holds no data (the token is read from the address by its own script), the
script and the style are inline and allowed by hash only, everything the visitor or the assistant wrote goes in with
`textContent`, and the page talks to the two routes under /api/public/desk/<token> of its own origin only."""
from __future__ import annotations

import base64
import hashlib
import html
import json

STYLE = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1c1c1e;--mut:#6b7280;--line:#d4d4d8;--me:#e8f0fe;--ai:#f4f4f5;--acc:#2563eb}
@media (prefers-color-scheme:dark){:root{--bg:#18181b;--fg:#f4f4f5;--mut:#a1a1aa;--line:#3f3f46;--me:#1e3a5f;--ai:#27272a;--acc:#60a5fa}}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,sans-serif;display:flex;flex-direction:column;max-width:42rem;margin:0 auto}
header{padding:12px 16px;border-bottom:1px solid var(--line)}
#label{font-weight:600}
#note{color:var(--mut);font-size:13px}
#log{flex:1;overflow-y:auto;padding:12px 16px;display:flex;flex-direction:column;gap:8px}
.m{max-width:85%;padding:8px 12px;border-radius:12px;white-space:pre-wrap;overflow-wrap:anywhere}
.visitor{align-self:flex-end;background:var(--me)}
.assistant{align-self:flex-start;background:var(--ai)}
.system{align-self:center;color:var(--mut);font-size:14px}
form{display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--line)}
textarea{flex:1;resize:none;font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px}
button{font:inherit;border:0;border-radius:8px;padding:0 16px;background:var(--acc);color:#fff;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
"""

TEXTS = {
    "en": {"note": "You are chatting with an AI assistant.", "aria": "Your message", "ph": "Write your message", "send": "Send",
           "title": "Chat", "unavail": "The assistant is not available right now.", "lost": "Connection lost. Reload the page to continue.",
           "name": "Assistant", "ai": "AI assistant"},
    "fr": {"note": "Vous discutez avec un assistant IA.", "aria": "Votre message", "ph": "Écrivez votre message", "send": "Envoyer",
           "title": "Discussion", "unavail": "L'assistant n'est pas disponible pour le moment.",
           "lost": "Connexion perdue. Rechargez la page pour continuer.", "name": "Assistant", "ai": "Assistant IA"},
}

BODY = """<header><div id="label"></div><div id="note">@note@</div></header>
<div id="log" role="log" aria-live="polite"></div>
<form id="f"><textarea id="t" rows="2" aria-label="@aria@" placeholder="@ph@" disabled></textarea>
<button id="b" type="submit" disabled>@send@</button></form>"""

SCRIPT_TPL = """
(function () {
  'use strict';
  var T = @texts@;
  var parts = location.pathname.split('/').filter(Boolean);
  var api = '/api/public/desk/' + encodeURIComponent(parts[parts.length - 1] || '');
  var key = 'desk-conv:' + parts[parts.length - 1];
  var log = document.getElementById('log'), t = document.getElementById('t'), b = document.getElementById('b');
  var conv = '', busy = false, timer = 0, tries = 0;
  try { conv = sessionStorage.getItem(key) || ''; } catch (e) { conv = ''; }
  function store(v) { conv = v; try { if (v) sessionStorage.setItem(key, v); else sessionStorage.removeItem(key); } catch (e) {} }
  function lock(v) { busy = v; t.disabled = v; b.disabled = v; }
  function show(list) {
    log.textContent = '';
    list.forEach(function (m) {
      var d = document.createElement('div');
      d.className = 'm ' + (m.role === 'visitor' || m.role === 'assistant' ? m.role : 'system');
      d.textContent = String(m.text == null ? '' : m.text);
      log.appendChild(d);
    });
    log.scrollTop = log.scrollHeight;
  }
  function say(text) { show([{ role: 'system', text: text }]); }
  function call(method, url, body) {
    return fetch(url, { method: method, credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer',
      headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, j: j }; }); });
  }
  function poll() {
    clearTimeout(timer);
    call('GET', api + '?conv=' + encodeURIComponent(conv)).then(function (r) {
      if (!r.ok) { if (r.status === 404) store(''); say(r.j.message || T.unavail); lock(false); return; }
      show(r.j.messages || []);
      if (r.j.pending && ++tries < 400) { timer = setTimeout(poll, 2500); return; }
      lock(false); t.focus();
    }).catch(function () { say(T.lost); lock(false); });
  }
  document.getElementById('f').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var text = t.value.trim();
    if (!text || busy) return;
    lock(true);
    call('POST', api, { message: text, conv: conv || null }).then(function (r) {
      if (!r.ok) {
        if (r.status === 404) store('');
        var d = document.createElement('div'); d.className = 'm system'; d.textContent = r.j.message || T.unavail;
        log.appendChild(d); log.scrollTop = log.scrollHeight; lock(false); return;
      }
      t.value = ''; store(r.j.conv); tries = 0; poll();
    }).catch(function () { say(T.lost); lock(false); });
  });
  call('GET', api + (conv ? '?conv=' + encodeURIComponent(conv) : '')).then(function (r) {
    if (!r.ok && conv) { store(''); return call('GET', api); }
    return r;
  }).then(function (r) {
    if (!r.ok) { document.getElementById('label').textContent = T.name; say(r.j.message || T.unavail); return; }
    document.getElementById('label').textContent = r.j.label || T.ai;
    t.maxLength = r.j.max_chars || 1000;
    if (r.j.messages) show(r.j.messages);
    lock(false);
    if (r.j.pending) { lock(true); tries = 0; poll(); }
  }).catch(function () { say(T.unavail); });
})();
"""


def _h(s: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode() + "'"


def _build(lang: str) -> tuple[str, dict, str, str]:
    """(html, headers, script, csp) of the page in one language; the CSP hashes are those of the exact strings sent."""
    t = TEXTS[lang]
    body = BODY
    for k in ("note", "aria", "ph", "send"):
        body = body.replace(f"@{k}@", html.escape(t[k]))
    script = SCRIPT_TPL.replace("@texts@", json.dumps(t, ensure_ascii=True))   # ASCII only: stable bytes, stable hash
    page = ('<!doctype html>\n<html lang="' + lang + '"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">'
            f"<title>{html.escape(t['title'])}</title><style>{STYLE}</style></head><body>\n{body}\n<script>{script}</script></body></html>\n")
    csp = ("default-src 'none'; script-src " + _h(script) + "; style-src " + _h(STYLE) + "; img-src data:; connect-src 'self'; "
           "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    headers = {"Content-Security-Policy": csp, "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
               "X-Robots-Tag": "noindex, nofollow", "X-Content-Type-Options": "nosniff"}
    return page, headers, script, csp


PAGES = {lang: _build(lang) for lang in TEXTS}


def page(lang: str) -> tuple[str, dict]:
    """(html, headers) for the server language (en or fr; anything else is English)."""
    return PAGES.get(lang, PAGES["en"])[:2]


HTML, HEADERS, SCRIPT, CSP = PAGES["en"]
