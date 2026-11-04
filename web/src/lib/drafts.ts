/** What the composer keeps in localStorage (pages/sessions/store.ts): the draft under `mx-draft:<key>`, its quotes,
 *  attachments and sends in flight under `mx-draft:<key>:quotes|:atts|:out`, the last prefill under `mx-prefilled:<key>`.
 *  Kept here, out of the sessions page, so signing out can clear it without loading that page. */
const PREFIXES = ['mx-draft:', 'mx-prefilled:']
const PARTS = ['', ':quotes', ':atts', ':out']

/** Signing out: no unsent text or attachment path of any session stays in this browser. */
export function forgetAllDrafts() {
  try {
    const keys: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && PREFIXES.some((p) => k.startsWith(p))) keys.push(k)
    }
    for (const k of keys) localStorage.removeItem(k)
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
