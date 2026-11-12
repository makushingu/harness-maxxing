"""The front desk's public chat page (GET /desk/<token>): one static document, no third-party code, no cookie.

An unauthenticated surface: the page holds no data (the token is read from the address by its own script), the
script and the style are inline and allowed by hash only, everything the visitor or the assistant wrote goes in with
`textContent`, and the page talks to the two routes under /api/public/desk/<token> of its own origin only."""
from __future__ import annotations

import base64
import hashlib

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

BODY = """<header><div id="label"></div><div id="note">You are chatting with an AI assistant.</div></header>
<div id="log" role="log" aria-live="polite"></div>
<form id="f"><textarea id="t" rows="2" aria-label="Your message" placeholder="Write your message" disabled></textarea>
<button id="b" type="submit" disabled>Send</button></form>"""

SCRIPT = """
(function () {
  'use strict';
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
      if (!r.ok) { if (r.status === 404) store(''); say(r.j.message || 'The assistant is not available right now.'); lock(false); return; }
      show(r.j.messages || []);
      if (r.j.pending && ++tries < 400) { timer = setTimeout(poll, 2500); return; }
      lock(false); t.focus();
    }).catch(function () { say('Connection lost. Reload the page to continue.'); lock(false); });
  }
  document.getElementById('f').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var text = t.value.trim();
    if (!text || busy) return;
    lock(true);
    call('POST', api, { message: text, conv: conv || null }).then(function (r) {
      if (!r.ok) {
        if (r.status === 404) store('');
        var d = document.createElement('div'); d.className = 'm system'; d.textContent = r.j.message || 'The assistant is not available right now.';
        log.appendChild(d); log.scrollTop = log.scrollHeight; lock(false); return;
      }
      t.value = ''; store(r.j.conv); tries = 0; poll();
    }).catch(function () { say('Connection lost. Reload the page to continue.'); lock(false); });
  });
  call('GET', api + (conv ? '?conv=' + encodeURIComponent(conv) : '')).then(function (r) {
    if (!r.ok && conv) { store(''); return call('GET', api); }
    return r;
  }).then(function (r) {
    if (!r.ok) { document.getElementById('label').textContent = 'Assistant'; say(r.j.message || 'The assistant is not available right now.'); return; }
    document.getElementById('label').textContent = r.j.label || 'AI assistant';
    t.maxLength = r.j.max_chars || 1000;
    if (r.j.messages) show(r.j.messages);
    lock(false);
    if (r.j.pending) { lock(true); tries = 0; poll(); }
  }).catch(function () { say('The assistant is not available right now.'); });
})();
"""


def _h(s: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode() + "'"


HTML = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">'
        f"<title>Chat</title><style>{STYLE}</style></head><body>\n{BODY}\n<script>{SCRIPT}</script></body></html>\n")

CSP = ("default-src 'none'; script-src " + _h(SCRIPT) + "; style-src " + _h(STYLE) + "; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

HEADERS = {"Content-Security-Policy": CSP, "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
           "X-Robots-Tag": "noindex, nofollow", "X-Content-Type-Options": "nosniff"}
