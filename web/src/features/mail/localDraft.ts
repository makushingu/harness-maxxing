// What this browser keeps of the E-mail page between two loads:
// - the message being written (`mx-mail-compose` in localStorage, its new files in IndexedDB `mx-mail`): a reload, a
//   tab closed or a Back gesture no longer loses it; it opens again on the next visit of the page;
// - for a reply saved as a draft, the message it answers (`mx-mail-replies`): the draft holds no trace of it, and
//   sending it later must still flag that message "answered".
// Signing out clears both (lib/drafts.ts forgetAllDrafts).
// The tab whose dialog holds the message says so every few seconds (`mx-mail-compose-live`): another tab opened
// meanwhile does not open the same message again (it could be sent twice). A crashed tab stops saying it: its message
// opens again a few seconds later.
import type { MailAttachment } from '@/lib/types'
import type { ComposeInit } from './Compose'

const KEY = 'mx-mail-compose'
const LIVE = 'mx-mail-compose-live'
const LIVE_MS = 5_000
// one id per page load: a reload of the same tab gives the hold up on pagehide, so the message opens again at once
const TAB = Math.random().toString(36).slice(2) + Date.now().toString(36)
const REPLIES = 'mx-mail-replies'
const DB = 'mx-mail'
const MAX_AGE = 30 * 86400_000
const MAX_REPLIES = 200

/** The message being written: a ComposeInit with what the user changed, plus what only the open dialog had. */
export type LocalCompose = ComposeInit & { at: number; showCc: boolean; kept: MailAttachment[]; files: number }

/** Another tab holds the message being written right now (its dialog is open). */
export function composeHeldElsewhere(): boolean {
  try {
    const v = JSON.parse(localStorage.getItem(LIVE) || 'null') as { tab?: string; at?: number } | null
    return !!v && v.tab !== TAB && Date.now() - (v.at || 0) < LIVE_MS * 3
  } catch {
    return false
  }
}
/** This tab's dialog holds the message: refreshed while it is open; returns the function that gives it up. */
export function holdCompose(): () => void {
  const beat = () => {
    try {
      localStorage.setItem(LIVE, JSON.stringify({ tab: TAB, at: Date.now() }))
    } catch {
      /* private mode */
    }
  }
  const release = () => {
    try {
      const v = JSON.parse(localStorage.getItem(LIVE) || 'null') as { tab?: string } | null
      if (v?.tab === TAB) localStorage.removeItem(LIVE)
    } catch {
      /* private mode */
    }
  }
  beat()
  const id = window.setInterval(beat, LIVE_MS)
  window.addEventListener('pagehide', release)
  window.addEventListener('pageshow', beat)
  return () => {
    window.clearInterval(id)
    window.removeEventListener('pagehide', release)
    window.removeEventListener('pageshow', beat)
    release()
  }
}

const strings = (v: unknown) => Array.isArray(v) && v.every((x) => typeof x === 'string')
const attachments = (v: unknown) =>
  Array.isArray(v) &&
  v.every((a) => !!a && typeof a === 'object' && typeof a.size === 'number' && typeof a.filename === 'string')
const place = (v: unknown) => v === undefined || (!!v && typeof v === 'object' && typeof (v as { uid?: unknown }).uid === 'number')

/** The kept message, or null; a copy of another shape (written by hand, an older build, cut by a full storage) is
 *  dropped: opened as is it would break the page on every visit. */
export function loadCompose(): LocalCompose | null {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || 'null') as LocalCompose | null
    if (!v) return null
    const ok =
      typeof v === 'object' &&
      typeof v.acc === 'string' &&
      typeof v.mode === 'string' &&
      strings(v.to) &&
      strings(v.cc) &&
      strings(v.bcc) &&
      typeof v.subject === 'string' &&
      typeof v.text === 'string' &&
      attachments(v.kept) &&
      place(v.reply) &&
      place(v.draft) &&
      place(v.source) &&
      (v.source === undefined || attachments(v.source.attachments))
    if (!ok) localStorage.removeItem(KEY)
    if (!ok || Date.now() - (v.at || 0) > MAX_AGE) return null
    return v
  } catch {
    try {
      localStorage.removeItem(KEY) /* not JSON */
    } catch {
      /* private mode */
    }
    return null
  }
}
export function saveCompose(c: Omit<LocalCompose, 'at'>) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...c, at: Date.now() }))
  } catch {
    // private mode, full storage: the dialog still works, only the copy is missing. An older copy must not stay:
    // opened after a reload it would pass for the message as it was last written
    try {
      localStorage.removeItem(KEY)
    } catch {
      /* private mode */
    }
  }
}
export function forgetCompose() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* private mode */
  }
  void saveFiles([])
}

// ------------------------------------------------------------------ the attached files (Blobs: IndexedDB only)

function db(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    try {
      const r = indexedDB.open(DB, 1)
      r.onupgradeneeded = () => r.result.createObjectStore('files')
      r.onsuccess = () => resolve(r.result)
      r.onerror = () => resolve(null)
    } catch {
      resolve(null)
    }
  })
}
export async function saveFiles(files: File[]): Promise<void> {
  const d = await db()
  if (!d) return
  await new Promise<void>((resolve) => {
    try {
      const tx = d.transaction('files', 'readwrite')
      if (files.length) tx.objectStore('files').put(files, 'compose')
      else tx.objectStore('files').delete('compose')
      tx.oncomplete = tx.onerror = tx.onabort = () => resolve()
    } catch {
      resolve()
    }
  })
  d.close()
}
export async function loadFiles(): Promise<File[]> {
  const d = await db()
  if (!d) return []
  const out = await new Promise<File[]>((resolve) => {
    try {
      const r = d.transaction('files').objectStore('files').get('compose')
      r.onsuccess = () => resolve(Array.isArray(r.result) ? r.result.filter((f): f is File => f instanceof File) : [])
      r.onerror = () => resolve([])
    } catch {
      resolve([])
    }
  })
  d.close()
  return out
}

// ------------------------------------------------------------------ reply drafts -> the message they answer

type Ref = { folder: string; uid: number }
const replyKey = (acc: string, d: Ref) => `${acc}|${d.folder}|${d.uid}`

function replies(): Record<string, Ref & { at: number }> {
  try {
    const v = JSON.parse(localStorage.getItem(REPLIES) || '{}')
    return v && typeof v === 'object' ? v : {}
  } catch {
    return {}
  }
}
/** A reply was saved as `draft`: remember the message it answers (the previous version of the draft is dropped). */
export function rememberReply(acc: string, draft: Ref, reply: Ref, previous?: Ref) {
  const all = replies()
  if (previous) delete all[replyKey(acc, previous)]
  all[replyKey(acc, draft)] = { folder: reply.folder, uid: reply.uid, at: Date.now() }
  const keys = Object.keys(all).sort((a, b) => all[b].at - all[a].at)
  for (const k of keys.slice(MAX_REPLIES)) delete all[k]
  try {
    localStorage.setItem(REPLIES, JSON.stringify(all))
  } catch {
    /* private mode */
  }
}
export function replyOf(acc: string, draft: Ref): Ref | undefined {
  const r = replies()[replyKey(acc, draft)]
  return r ? { folder: r.folder, uid: r.uid } : undefined
}
export function forgetReply(acc: string, draft: Ref) {
  const all = replies()
  if (!all[replyKey(acc, draft)]) return
  delete all[replyKey(acc, draft)]
  try {
    localStorage.setItem(REPLIES, JSON.stringify(all))
  } catch {
    /* private mode */
  }
}
