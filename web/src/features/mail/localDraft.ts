// What this browser keeps of the E-mail page between two loads:
// - the message being written (`mx-mail-compose` in localStorage, its new files in IndexedDB `mx-mail`): a reload, a
//   tab closed or a Back gesture no longer loses it; it opens again on the next visit of the page;
// - for a reply saved as a draft, the message it answers (`mx-mail-replies`): the draft holds no trace of it, and
//   sending it later must still flag that message "answered".
// Signing out clears both (lib/drafts.ts forgetAllDrafts).
import type { MailAttachment } from '@/lib/types'
import type { ComposeInit } from './Compose'

const KEY = 'mx-mail-compose'
const REPLIES = 'mx-mail-replies'
const DB = 'mx-mail'
const MAX_AGE = 30 * 86400_000
const MAX_REPLIES = 200

/** The message being written: a ComposeInit with what the user changed, plus what only the open dialog had. */
export type LocalCompose = ComposeInit & { at: number; showCc: boolean; kept: MailAttachment[]; files: number }

export function loadCompose(): LocalCompose | null {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || 'null') as LocalCompose | null
    if (!v || typeof v !== 'object' || typeof v.acc !== 'string' || Date.now() - (v.at || 0) > MAX_AGE) return null
    return v
  } catch {
    return null
  }
}
export function saveCompose(c: Omit<LocalCompose, 'at'>) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...c, at: Date.now() }))
  } catch {
    /* private mode, full storage: the dialog still works, only the copy is missing */
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
