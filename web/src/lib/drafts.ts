/** What the composer keeps in localStorage (pages/sessions/store.ts): the draft under `mx-draft:<key>`, its quotes,
 *  attachments and sends in flight under `mx-draft:<key>:quotes|:atts|:out`, the last prefill under `mx-prefilled:<key>`.
 *  Kept here, out of the sessions page, so signing out can clear it without loading that page. */
const PREFIXES = ['mx-draft:', 'mx-prefilled:', 'mx-mail-']
const PARTS = ['', ':quotes', ':atts', ':out']

/** Signing out: no unsent text or attachment path of any session, nor mail being written, stays in this browser. */
export function forgetAllDrafts() {
  try {
    const keys: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && PREFIXES.some((p) => k.startsWith(p))) keys.push(k)
    }
    for (const k of keys) localStorage.removeItem(k)
    // the files of a mail being written (features/mail/localDraft.ts)
    indexedDB.deleteDatabase('mx-mail')
    forgetAside()
  } catch {
    /* private mode */
  }
}

/** The side questions and answers (sessionStorage `mx-asides`, pages/sessions/Aside.tsx): of one session, or all of them.
 *  The page listens for this event to empty its store too. */
export const ASIDE_FORGET_EVENT = 'mx-forget-aside'
function forgetAside(sid?: string) {
  try {
    if (sid === undefined) sessionStorage.removeItem('mx-asides')
    else {
      const raw = sessionStorage.getItem('mx-asides')
      const state = raw ? JSON.parse(raw) : null
      if (state?.state?.bySid && Object.hasOwn(state.state.bySid, sid)) {
        delete state.state.bySid[sid]
        sessionStorage.setItem('mx-asides', JSON.stringify(state))
      }
    }
  } catch {
    /* private mode, or not JSON */
  }
  window.dispatchEvent(new CustomEvent(ASIDE_FORGET_EVENT, { detail: sid }))
}

/** A deleted session: its draft keys go with it. */
export function forgetDraft(key: string) {
  try {
    for (const part of PARTS) localStorage.removeItem(`mx-draft:${key}${part}`)
    localStorage.removeItem(`mx-prefilled:${key}`)
    forgetAside(key)
  } catch {
    /* private mode */
  }
}

/** Draft key of an agent's box (`agent:<path>`) or a group's (`group:<path>`): never a session's (its id or `new:<path>`). */
export const agentDraftKey = (kind: 'agent' | 'group', path: string) => `${kind}:${path}`

/** The drafts of the agents (`kind` 'agent') or groups ('group') not in `paths` (the full list the server just gave):
 *  gone from another browser, or with their topic or project. An empty list prunes nothing (a folder that could not
 *  be read must not wipe every draft). */
export function pruneAgentDrafts(kind: 'agent' | 'group', paths: string[]) {
  if (!paths.length) return
  try {
    const keep = new Set(paths)
    const head = `mx-draft:${kind}:`
    const gone = new Set<string>()
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (!k?.startsWith(head)) continue
      const rest = k.slice(head.length)
      const part = PARTS.find((p) => p && rest.endsWith(p)) || ''
      const path = rest.slice(0, rest.length - part.length)
      if (!keep.has(path)) gone.add(path)
    }
    for (const path of gone) forgetDraft(agentDraftKey(kind, path))
  } catch {
    /* private mode */
  }
}

/** Fired with the draft key when a draft is written from outside its composer: a mounted composer reloads it. */
export const DRAFT_EVENT = 'mx-draft'

/** Adds `text` after the draft of `key` (a dictation that came back once its box was gone: another page) and tells
 *  a box of that key opened again meanwhile. */
export function appendDraft(key: string, text: string) {
  try {
    const cur = localStorage.getItem(`mx-draft:${key}`) || ''
    localStorage.setItem(`mx-draft:${key}`, [cur.trimEnd(), text].filter(Boolean).join(cur.trim() ? '\n\n' : ''))
  } catch {
    /* quota / private mode */
  }
  window.dispatchEvent(new CustomEvent(DRAFT_EVENT, { detail: key }))
}
