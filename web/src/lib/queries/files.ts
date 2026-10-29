import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api, ApiError, isApiError, withQuery } from '../api'
import type { FileContent, FileList, FileSearchHit, FileWriteBody, FileWriteResult, Ok, UploadResult } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export const fileListQuery = (path: string) => ({
  queryKey: qk.files.list(path),
  queryFn: async () => {
    const list = await api.get<FileList>('/api/files/list', { path })
    seedFileStamps(list.entries)
    return list
  },
})
export function useFileList(path: string) {
  return useQuery(fileListQuery(path))
}
export function useFileContent(path: string | null, enabled = true) {
  return useQuery({
    queryKey: qk.files.read(path || ''),
    queryFn: ({ signal }) => api.get<FileContent>('/api/files/read', { path: path! }, { signal }),
    enabled: !!path && enabled,
  })
}

/** Remember the kind of a path seen in a listing (avoids a probe request when opening it). */
export function seedFileKind(qc: ReturnType<typeof useQueryClient>, path: string, kind: 'file' | 'dir') {
  qc.setQueryData(['files', 'kind', path], kind)
}

/**
 * `/files?path=` may point at a folder or a file. Probe the PARENT listing (no 404 noise for files, and the
 * viewer needs that listing anyway). The root listing is fetched once to know `root`.
 * A path missing from its parent is reported as "missing" (the viewer shows "not found" without a read).
 */
export function useFileKind(path: string) {
  return useQuery(fileKindQuery(useQueryClient(), path))
}
export const fileKindQuery = (qc: QueryClient, path: string) => ({
  queryKey: ['files', 'kind', path] as const,
  queryFn: async (): Promise<'file' | 'dir' | 'missing'> => {
    const listDir = async (p: string) => {
      const list = await api.get<FileList>('/api/files/list', { path: p })
      qc.setQueryData(qk.files.list(p), list)
      if (!p) qc.setQueryData(qk.files.list(list.path), list)
      return list
    }
    // Learn the files root once (cached): the root itself has no listable parent. The parent listing is
    // fetched at the same time (not after the root's); its error only matters when `path` is not the root.
    const parent = path.replace(/\/[^/]*$/, '') || '/'
    const parentList = path ? listDir(parent) : null
    parentList?.catch(() => undefined)
    const rootList = qc.getQueryData<FileList>(qk.files.list('')) ?? (await listDir(''))
    if (!path || path === rootList.root) return 'dir'
    let list: FileList
    try {
      list = await parentList!
    } catch (e) {
      if (isApiError(e) && (e.status === 403 || e.status === 404)) return (await listDir(path)) && 'dir'
      throw e
    }
    const name = path.slice(path.lastIndexOf('/') + 1)
    return list.entries.find((x) => x.name === name)?.type ?? 'missing'
  },
  staleTime: Infinity,
  retry: false,
})
export function useFileSearch(q: string) {
  return useQuery({
    queryKey: qk.files.search(q),
    queryFn: ({ signal }) => api.get<FileSearchHit[]>('/api/files/search', { q }, { signal }),
    enabled: q.trim().length >= 2,
    staleTime: 15_000,
  })
}
/** `version` = the file's mtime when known (listing): a versioned URL is cached by the browser for good. */
const ver = (v?: number | null) => (v ? String(Math.round(v * 1000)) : undefined)
export const fileRawUrl = (path: string, download = false, version?: number | null) => withQuery('/api/files/raw', { path, download, v: ver(version) })
/** `anim`: a GIF (up to 8 MB) comes as it is, so it moves (chat); else a still WebP (file grids). */
export const fileThumbUrl = (path: string, w = 320, version?: number | null, anim = false) =>
  withQuery('/api/files/thumb', { path, w, v: ver(version), anim: anim ? 1 : undefined })
/** Current mtime of the files shown as previews (chat thumbnails, viewer), asked in one batch per tick: it goes in
 *  their URLs, so a file rewritten under the same name shows its new version. Refreshed when a turn writes files
 *  (`refreshFileStamps`), on focus, and by any file mutation (key under `files`). */
const stampKey = (path: string) => ['files', 'stamp', path] as const
const known = new Map<string, number | null>()
const stampWait = new Map<string, ((v: number | null) => void)[]>()
let stampTimer = 0
function fetchStamp(path: string) {
  return new Promise<number | null>((resolve) => {
    const waiting = stampWait.get(path)
    if (waiting) waiting.push(resolve)
    else stampWait.set(path, [resolve])
    if (!stampTimer) stampTimer = window.setTimeout(flushStamps, 0)
  })
}
async function flushStamps() {
  stampTimer = 0
  const batch = [...stampWait]
  stampWait.clear()
  for (let i = 0; i < batch.length; i += 200) {
    const part = batch.slice(i, i + 200)
    let mtimes: Record<string, number | null> = {}
    try {
      mtimes = (await api.post<{ mtimes: Record<string, number | null> }>('/api/files/stat', { paths: part.map(([p]) => p) })).mtimes
    } catch {
      // unversioned URLs (revalidated by the browser) until the next refresh
    }
    for (const [p, fns] of part) {
      known.set(p, mtimes[p] ?? null)
      for (const fn of fns) fn(mtimes[p] ?? null)
    }
  }
}
const seededAt = new Map<string, number>()
/** mtimes a folder listing already gives: a preview opened from it starts at once, with no round trip. */
export function seedFileStamps(entries: { path: string; type: string; mtime: number }[]) {
  const now = Date.now()
  for (const e of entries)
    if (e.type === 'file') {
      known.set(e.path, e.mtime)
      seededAt.set(e.path, now)
    }
}
export function useFileStamp(path: string | null | undefined) {
  const p = path ?? ''
  const q = useQuery({
    queryKey: stampKey(p),
    queryFn: () => fetchStamp(path!),
    enabled: !!path,
    staleTime: 30_000,
    // a stamp already known (a listing, a thumbnail shown before): used at once, re-asked once it is stale
    initialData: known.has(p) ? () => known.get(p) ?? null : undefined,
    initialDataUpdatedAt: () => seededAt.get(p) ?? 0,
  })
  return { ready: !path || q.isFetched || q.data !== undefined, version: q.data ?? null }
}
/** The stamp already known for a path (no request), for prefetching. */
export const knownFileStamp = (path: string) => known.get(path) ?? null
/** The stamp of a path, asked (batched) when not known yet: a prefetch then loads the URL the viewer will use. */
export const fileStamp = (path: string): Promise<number | null> => (known.has(path) ? Promise.resolve(known.get(path) ?? null) : fetchStamp(path))
/** Files may have changed (a tool ran, a turn ended): re-ask the stamps of the previews on screen. */
export const refreshFileStamps = (qc: QueryClient) => qc.invalidateQueries({ queryKey: ['files', 'stamp'] })

/** Image for the viewer: a WebP of at most `w` px when the original is heavy (> 300 KB), else the original. */
export const filePreviewUrl = (path: string, w = PREVIEW_W, version?: number | null) => withQuery('/api/files/preview', { path, w, v: ver(version) })
export const PREVIEW_W = 2048

/** Start downloading an image before it is shown (hover on a media link): the click then opens it instantly. */
const prefetched = new Set<string>()
export function prefetchImage(url: string) {
  if (prefetched.has(url) || prefetched.size > 200) return
  prefetched.add(url)
  const img = new Image()
  img.decoding = 'async'
  img.src = url
}

const inv = [qk.files.all] as const
export function useWriteFile() {
  return useMut((b: FileWriteBody) => api.put<FileWriteResult>('/api/files/write', b), { invalidate: inv, errorToast: false })
}
export function useMkdir() {
  return useMut((path: string) => api.post<Ok>('/api/files/mkdir', { path }), { invalidate: inv })
}
export function useMoveFile() {
  return useMut((b: { from: string; to: string }) => api.post<Ok>('/api/files/move', b), { invalidate: inv })
}
export function useDeleteFile() {
  return useMut((path: string) => api.post<Ok>('/api/files/delete', { path }), { invalidate: inv })
}
export function useUploadFiles() {
  return useMut(({ dir, files }: { dir: string; files: File[] }) => api.upload<UploadResult>('/api/files/upload', files, { dir }), {
    invalidate: inv,
  })
}

/**
 * Upload ONE file with progress (XHR: fetch has no upload progress). Same conventions as api.ts:
 * cookie, CSRF header, ApiError on failure.
 */
export function uploadFileWithProgress(dir: string, file: File, onProgress: (loaded: number, total: number) => void, signal?: AbortSignal) {
  return new Promise<UploadResult>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', withQuery('/api/files/upload', { dir }))
    xhr.setRequestHeader('X-Maxxing', '1')
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.withCredentials = true
    xhr.upload.onprogress = (e) => onProgress(e.loaded, e.lengthComputable ? e.total : file.size)
    xhr.onload = () => {
      let data: { error?: string; message?: string } | UploadResult | undefined
      try {
        data = JSON.parse(xhr.responseText)
      } catch {
        data = undefined
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as UploadResult)
      else {
        const d = (data || {}) as { error?: string; message?: string }
        reject(new ApiError(xhr.status, d.error || `http_${xhr.status}`, d.message || xhr.statusText))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'network', 'Network error — the server could not be reached.'))
    xhr.onabort = () => reject(new DOMException('Aborted', 'AbortError'))
    signal?.addEventListener('abort', () => xhr.abort())
    const fd = new FormData()
    fd.append('file', file, file.name)
    xhr.send(fd)
  })
}
