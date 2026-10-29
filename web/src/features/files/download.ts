// Download a file to the user's device. The browser's own download of `?download=1` is the rule: it streams to
// disk and shows its progress, whatever the size (a 200 MB PDF read into a Blob froze or crashed the tab).
// One shortcut: an image of at most 20 MB whose versioned URL is the one the viewer displayed is read back
// from the browser cache and saved at once (the `?download=1` URL is another cache entry: a second transfer).
// iPhone / iPad home-screen app: an `<a download>` on a Blob often does nothing there, and a link that leaves
// the app opens Safari, which has no session (401). So the file goes to the share sheet ("Save to Files",
// AirDrop...) up to 50 MB, else it opens inside the app, where the system offers to save or share it.
import type * as React from 'react'
import { toast } from '@/components/ui'
import { api, errorMessage, isApiError, withQuery } from '@/lib/api'
import { useT } from '@/i18n'
import { fileRawUrl, fileZipUrl, knownFileStamp } from '@/lib/queries/files'
import type { FileEntry } from '@/lib/types'
import { isIOS, isStandalone } from '@/pwa'
import { basename, kindOf } from './kinds'

const BLOB_MAX = 20 * 1024 * 1024
const SHARE_MAX = 50 * 1024 * 1024

export type DownloadOpts = { version?: number | null; size?: number | null }

/** The installed app on iOS: a link that leaves the app (`target=_blank`, Safari) has no session cookie. */
export const inIosApp = () => isIOS() && isStandalone()

function save(href: string, name: string) {
  const a = document.createElement('a')
  a.href = href
  a.download = name
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

/** The body of `url` as a Blob, or null when it is larger than `max` (seen from Content-Length or while reading). */
async function fetchUpTo(url: string, max: number): Promise<Blob | null> {
  const ctrl = new AbortController()
  const res = await fetch(url, { credentials: 'same-origin', signal: ctrl.signal })
  const len = Number(res.headers.get('content-length') || 0)
  if (!res.ok || len > max) {
    ctrl.abort()
    return null
  }
  const reader = res.body?.getReader()
  if (!reader) return res.blob()
  const parts: Uint8Array[] = []
  let n = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    n += value.byteLength
    if (n > max) {
      ctrl.abort()
      return null
    }
    parts.push(value)
  }
  return new Blob(parts as BlobPart[], { type: res.headers.get('content-type') ?? '' })
}

/** iOS app: the share sheet when the file is small enough and sharing files is possible, else open it in the app. */
async function shareOrOpen(path: string, version: number | null | undefined, size: number | null | undefined) {
  const url = fileRawUrl(path, false, version)
  const share = navigator as Navigator & { canShare?: (d: ShareData) => boolean }
  if (share.share && share.canShare && (size == null || size <= SHARE_MAX)) {
    try {
      const blob = await fetchUpTo(url, SHARE_MAX)
      if (blob) {
        const file = new File([blob], basename(path), { type: blob.type || 'application/octet-stream' })
        if (share.canShare({ files: [file] })) {
          await share.share({ files: [file] })
          return
        }
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return // the user closed the share sheet
      /* not allowed (the tap is too old after a long fetch), network: open it instead */
    }
  }
  window.location.assign(url)
}

/** The image shortcut applies: a versioned URL (the one the viewer shows) of an image small enough for a Blob. */
const fromCache = (path: string, version: number | null | undefined, size: number | null | undefined) =>
  kindOf(basename(path)) === 'image' && !!version && (size == null || size <= BLOB_MAX)

export async function downloadFile(path: string, opts: DownloadOpts = {}): Promise<void> {
  const name = basename(path)
  const version = opts.version ?? knownFileStamp(path)
  if (inIosApp()) return shareOrOpen(path, version, opts.size)
  if (fromCache(path, version, opts.size)) {
    try {
      const blob = await fetchUpTo(fileRawUrl(path, false, version), BLOB_MAX)
      if (blob) {
        const url = URL.createObjectURL(blob)
        save(url, name)
        setTimeout(() => URL.revokeObjectURL(url), 60_000)
        return
      }
    } catch {
      /* the browser's own download below */
    }
  }
  save(fileRawUrl(path, true, version), name)
}

/** Props of a download `<a>`: a real link (middle click, "save link as"); a plain click lets the browser download
 * it, unless downloadFile has something better to do (image shortcut, iOS app). */
export function downloadProps(path: string, opts: DownloadOpts = {}) {
  return {
    href: fileRawUrl(path, true, opts.version),
    download: basename(path),
    onClick: (e: React.MouseEvent) => {
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
      if (!inIosApp() && !fromCache(path, opts.version ?? knownFileStamp(path), opts.size)) return
      // The native event only: a menu item (Radix) skips its own close when the React event is marked prevented.
      e.nativeEvent.preventDefault()
      void downloadFile(path, opts)
    },
  }
}

/** A folder as a zip, made by the server while it downloads. Asked first (`check`): a link download the server
 * refuses (413, too large) fails without a reason, this throws the ApiError instead. */
export async function downloadZip(path: string): Promise<void> {
  await api.get(fileZipUrl(path, true))
  save(fileZipUrl(path), `${basename(path) || 'files'}.zip`)
}

/** Props of an "Open raw" `<a>`: a new tab, except in the iOS app where a new tab is Safari without the session. */
export function openRawProps(path: string, version?: number | null) {
  return inIosApp() ? { href: fileRawUrl(path, false, version) } : { href: fileRawUrl(path, false, version), target: '_blank', rel: 'noopener noreferrer' }
}

/** downloadZip with its error shown (a toast). */
export function useDownloadZip() {
  const t = useT()
  return (path: string) =>
    void downloadZip(path).catch((e) => toast.error(isApiError(e, 'too_large') ? t('files.zipTooLarge') : errorMessage(e)))
}

/** Several files and folders in one zip. The server checks them first (POST: paths, caps, a 413 with its reason)
 * and answers a short-lived link of this session, which the browser downloads like any file. */
export async function downloadZipMany(paths: string[]): Promise<void> {
  const r = await api.post<{ token: string; name: string }>('/api/files/zip', { paths })
  save(withQuery('/api/files/zip', { token: r.token }), r.name)
}

/** Download entries of a listing: one file as it is, one folder as its zip, several entries as one zip. */
export function useDownloadEntries() {
  const t = useT()
  return (entries: FileEntry[]) => {
    const [one] = entries
    if (!one) return
    const job = entries.length > 1 ? downloadZipMany(entries.map((e) => e.path)) : one.type === 'dir' ? downloadZip(one.path) : downloadFile(one.path, { version: one.mtime, size: one.size })
    void job.catch((e) => toast.error(isApiError(e, 'too_large') ? t('files.sel.zipTooLarge') : errorMessage(e)))
  }
}
