// Files page state helpers: persisted listing prefs, topic lookup ("Ask Claude"), upload queue.
import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { useWorkspace } from '@/lib/queries/workspace'
import { qk } from '@/lib/queries/keys'
import { uploadFileWithProgress } from '@/lib/queries/files'
import { errorMessage } from '@/lib/api'
import type { FileEntry } from '@/lib/types'

export type SortKey = 'name' | 'mtime' | 'size'
type Prefs = {
  sort: SortKey
  desc: boolean
  view: 'list' | 'grid'
  hidden: boolean
  set: (p: Partial<Omit<Prefs, 'set'>>) => void
}
export const useFilePrefs = create<Prefs>()(
  persist((set) => ({ sort: 'name', desc: false, view: 'list', hidden: false, set: (p) => set(p) }), { name: 'mx-files', version: 1 }),
)

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

/** Dirs first, then the chosen key; hidden files and the filter applied. */
export function sortEntries(entries: FileEntry[], o: { sort: SortKey; desc: boolean; hidden: boolean; filter: string }) {
  const f = o.filter.trim().toLowerCase()
  const list = entries.filter((e) => (o.hidden || !e.name.startsWith('.')) && (!f || e.name.toLowerCase().includes(f)))
  const dir = o.desc ? -1 : 1
  return list.sort((a, b) => {
    if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
    let c = o.sort === 'mtime' ? a.mtime - b.mtime : o.sort === 'size' ? a.size - b.size : 0
    if (c === 0) c = collator.compare(a.name, b.name)
    return c * dir
  })
}

/** Topic (workspace-relative path) containing `abs`, '' when none — for "Ask Claude about this file". */
export function useTopicFor(abs: string | null): string {
  const { data } = useWorkspace()
  return React.useMemo(() => {
    if (!abs || !data) return ''
    const root = data.root.replace(/\/+$/, '')
    let best = ''
    for (const p of data.projects)
      for (const tp of p.topics) {
        const full = `${root}/${tp.path}`
        if ((abs === full || abs.startsWith(full + '/')) && tp.path.length > best.length) best = tp.path
      }
    return best
  }, [abs, data])
}

/* ------------------------------------------------------------------ uploads */
export type UploadItem = {
  id: string
  name: string
  size: number
  loaded: number
  status: 'queued' | 'uploading' | 'done' | 'error'
  error?: string
  savedAs?: string
}

/** Sequential upload queue with per-file progress. Survives folder changes (each item keeps its target). */
export function useUploads() {
  const qc = useQueryClient()
  const [items, setItems] = React.useState<UploadItem[]>([])
  const queue = React.useRef<{ id: string; dir: string; file: File }[]>([])
  const running = React.useRef(false)
  const ctrl = React.useRef<AbortController | null>(null)

  const patch = React.useCallback((id: string, p: Partial<UploadItem>) => setItems((xs) => xs.map((x) => (x.id === id ? { ...x, ...p } : x))), [])

  const pump = React.useCallback(async () => {
    if (running.current) return
    running.current = true
    while (queue.current.length) {
      const job = queue.current.shift()!
      patch(job.id, { status: 'uploading' })
      ctrl.current = new AbortController()
      try {
        const res = await uploadFileWithProgress(job.dir, job.file, (loaded) => patch(job.id, { loaded }), ctrl.current.signal)
        patch(job.id, { status: 'done', loaded: job.file.size, savedAs: res.files?.[0]?.name })
      } catch (e) {
        patch(job.id, { status: 'error', error: (e as Error)?.name === 'AbortError' ? 'cancelled' : errorMessage(e) })
      }
      await qc.invalidateQueries({ queryKey: qk.files.list(job.dir) })
    }
    running.current = false
  }, [patch, qc])

  const add = React.useCallback(
    (dir: string, files: File[]) => {
      const jobs = files.map((file) => ({ id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, dir, file }))
      setItems((xs) => [...xs.filter((x) => x.status !== 'done'), ...jobs.map((j) => ({ id: j.id, name: j.file.name, size: j.file.size, loaded: 0, status: 'queued' as const }))])
      queue.current.push(...jobs)
      void pump()
    },
    [pump],
  )
  const cancelAll = React.useCallback(() => {
    const ids = new Set(queue.current.map((j) => j.id))
    queue.current = []
    setItems((xs) => xs.map((x) => (ids.has(x.id) ? { ...x, status: 'error', error: 'cancelled' } : x)))
    ctrl.current?.abort()
  }, [])
  const clear = React.useCallback(() => setItems((xs) => xs.filter((x) => x.status === 'queued' || x.status === 'uploading')), [])
  return { items, add, cancelAll, clear }
}
