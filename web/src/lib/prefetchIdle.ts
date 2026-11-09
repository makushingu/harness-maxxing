// Background warm-up once the first screen is on: when the boot loader is gone (index.html drops `html[data-boot]`)
// and the browser is idle, load - one small step at a time, low priority - the code of the pages in the sidebar and
// what the Sessions page shows first (the tree, then the open sessions with their thread), so the first click on
// any of them opens a finished page instead of a skeleton. Nothing on Save-Data or a slow connection, nothing that
// could hold the boot loader (it waits for the queries in flight: lib/bootLoader.ts).
import type { QueryClient } from '@tanstack/react-query'
import { extensionsQuery, prefetchTail, sessionQuery, sessionsQuery, settingsQuery } from '@/lib/queries'
import type { Extension, Settings } from '@/lib/types'
import { prefetchPages } from '@/pages/prefetch'

type IdleWindow = Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (h: number) => void }

/** False on Save-Data, 2G / 3G or offline: the warm-up would compete with what the user asked for. */
export function canPrefetch(): boolean {
  const conn = (navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } }).connection
  return navigator.onLine !== false && !conn?.saveData && !/(^|-)[23]g$/.test(conn?.effectiveType || '')
}

/** `cb` once the boot loader has fully played (at once when there is none). Returns a cancel function. */
export function whenBootDone(cb: () => void): () => void {
  const root = document.documentElement
  const w = window as Window & { mxBooted?: number }
  if (!root.hasAttribute('data-boot') || w.mxBooted) {
    cb()
    return () => {}
  }
  let fired = false
  const fire = () => {
    if (fired) return
    fired = true
    stop()
    cb()
  }
  // The loader's end (`mxbooted`, right after the logo lands); the attribute's removal stays as a fallback.
  const mo = new MutationObserver(() => {
    if (!root.hasAttribute('data-boot')) fire()
  })
  const stop = () => {
    mo.disconnect()
    window.removeEventListener('mxbooted', fire)
  }
  window.addEventListener('mxbooted', fire)
  mo.observe(root, { attributes: true, attributeFilter: ['data-boot'] })
  return stop
}

/** `cb` when the browser is idle (at most `timeout` ms later). Returns a cancel function. */
export function whenIdle(cb: () => void, timeout = 2000): () => void {
  const w = window as IdleWindow
  if (w.requestIdleCallback) {
    const h = w.requestIdleCallback(cb, { timeout })
    return () => w.cancelIdleCallback?.(h)
  }
  const h = window.setTimeout(cb, 300)
  return () => window.clearTimeout(h)
}

/** The sessions open on the Sessions page of this browser (its saved columns, pages/sessions/store.ts), the focused
 *  one first. Read from storage: the page's store lives in the page's chunk. */
export function openSessionIds(max = 3): string[] {
  try {
    const st = JSON.parse(localStorage.getItem('mx-sessions') || '{}')?.state as { cols?: { key: string; kind: string; id?: string }[]; focused?: string } | undefined
    const cols = (st?.cols || []).filter((c) => c.kind === 'session' && typeof c.id === 'string')
    const f = cols.findIndex((c) => c.key === st?.focused)
    if (f > 0) cols.unshift(...cols.splice(f, 1))
    return cols.slice(0, max).map((c) => c.id as string)
  } catch {
    return []
  }
}

/** The tops of the pages in the sidebar (optional ones only when switched on), Sessions first. */
function pageTops(qc: QueryClient): string[] {
  const s = qc.getQueryData<Settings>(settingsQuery().queryKey)
  const tops = ['sessions', '', 'files', 'settings']
  if (!s || s.tasks_page !== false) tops.push('tasks')
  for (const k of ['agents', 'team', 'mail', 'infra', 'git'] as const) if (s?.[`${k}_page`]) tops.push(k)
  const ext = qc.getQueryData<Extension[]>(extensionsQuery().queryKey)
  if (ext?.some((e) => e.type === 'page' && e.enabled && e.pinned)) tops.push('x/')
  return tops.concat('feed', 'docs', 'x')
}

/** Starts the warm-up (once per page load). Returns a cancel function. */
export function startIdlePrefetch(qc: QueryClient): () => void {
  if (!canPrefetch()) return () => {}
  let cancel = () => {}
  let stopped = false
  const steps: (() => unknown)[] = [
    () => qc.prefetchQuery(sessionsQuery(undefined, false)),
    // the open sessions: their header data, then their thread into the page's own log cache (it stays there, and
    // the live stream resumes from where it ends when the page opens: nothing is missed)
    () => {
      const ids = openSessionIds()
      for (const id of ids) void qc.prefetchQuery(sessionQuery(id))
      if (!ids.length) return
      return import('@/pages/sessions/log').then(
        (m) => ids.reduce<Promise<unknown>>((p, id) => p.then(() => m.loadLog(id)), Promise.resolve()),
        () => ids.forEach(prefetchTail),
      )
    },
    () => prefetchPages(pageTops(qc)),
  ]
  const next = () => {
    const step = steps.shift()
    if (!step || stopped) return
    cancel = whenIdle(() => {
      if (stopped || !canPrefetch()) return
      void Promise.resolve(step()).catch(() => undefined).then(() => !stopped && next())
    })
  }
  const stopBoot = whenBootDone(next)
  return () => {
    stopped = true
    stopBoot()
    cancel()
  }
}
