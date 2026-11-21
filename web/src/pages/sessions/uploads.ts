/* Files still uploading, kept outside the composer: switching session or tab unmounts it, the upload goes on and
 * its file lands in the draft it was added to (the composer shows it again when it comes back). */
import { uploadAttachment } from '@/lib/queries'
import { busyEnd, busyStart } from '@/lib/busy'
import { loadAtts, saveAtts } from './store'

export type Upload = { lid: string; key: string; name: string; size: number; progress: number }
type Event =
  | { kind: 'progress'; up: Upload }
  | { kind: 'done'; up: Upload; path: string; name: string }
  | { kind: 'error'; up: Upload; error: unknown }
/** A listener returns true when it took the event (an open composer of that draft). */
type Listener = (e: Event) => boolean

const ups = new Map<string, Upload & { ctrl: AbortController }>()
const listeners = new Set<Listener>()
const emit = (e: Event) => {
  let taken = false
  listeners.forEach((l) => {
    if (l(e)) taken = true
  })
  return taken
}

/** `key`: the draft the file goes to ('' = none: lost if its box is gone). `url`: the upload route (see uploadAttachment). */
export function startUpload(key: string, topicPath: string, f: File, lid: string, url?: string) {
  const ctrl = new AbortController()
  const up = { lid, key, name: f.name || 'file', size: f.size, progress: 0, ctrl }
  ups.set(lid, up)
  busyStart()
  uploadAttachment(topicPath, f, (l, tot) => {
    up.progress = tot ? l / tot : 0
    emit({ kind: 'progress', up })
  }, ctrl.signal, url)
    .then((saved) => {
      ups.delete(lid)
      // no composer open on that draft: the file goes straight into the stored draft
      if (!emit({ kind: 'done', up, path: saved.path, name: saved.name }) && up.key) saveAtts(up.key, [...loadAtts(up.key), { path: saved.path, name: saved.name, size: up.size }])
    })
    .catch((error) => {
      ups.delete(lid)
      if ((error as Error)?.name !== 'AbortError') emit({ kind: 'error', up, error })
    })
    .finally(busyEnd)
}

export const cancelUpload = (lid: string) => ups.get(lid)?.ctrl.abort()
export const uploadsOf = (key: string): Upload[] => [...ups.values()].filter((u) => u.key === key)
/** The draft got a new key (new column → real session): its uploads follow. */
export const moveUploads = (from: string, to: string) => ups.forEach((u) => u.key === from && (u.key = to))
export function onUploads(l: Listener) {
  listeners.add(l)
  return () => void listeners.delete(l)
}
