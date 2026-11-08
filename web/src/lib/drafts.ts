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
  } catch {
    /* private mode */
  }
}

/** A deleted session: its draft keys go with it. */
export function forgetDraft(key: string) {
  try {
    for (const part of PARTS) localStorage.removeItem(`mx-draft:${key}${part}`)
    localStorage.removeItem(`mx-prefilled:${key}`)
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
