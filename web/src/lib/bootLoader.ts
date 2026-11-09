// The boot loader of index.html: the logo builds itself one batch per boot step, then flies to its place and the
// interface opens around it. Step 1 = HTML parsed (index.html), 2 = app code running (main.tsx), 3 = the first
// screen is ready (this file). Step 3 is safe to call many times and from any screen; index.html also forces it
// after a while, so a screen that never calls it cannot leave the loader up.
import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'

declare global {
  interface Window {
    /** index.html boot loader (a no-op once it has played) */
    mxStep?: (n: number) => void
    /** set once the loader has played (index.html), with the event `mxbooted` */
    mxBooted?: number
  }
}

export const bootStep = (n: 1 | 2 | 3) => window.mxStep?.(n)

/** Runs `cb` once the loader has played (at once when there is none), so non-critical work never competes with it.
 *  Returns a cancel function. */
export function afterBoot(cb: () => void): () => void {
  if (!window.mxStep || window.mxBooted) {
    cb()
    return () => {}
  }
  window.addEventListener('mxbooted', cb, { once: true })
  return () => window.removeEventListener('mxbooted', cb)
}

/** A screen with nothing to wait for (sign-in, setup, onboarding, an error): the loader can end once it is painted. */
export function useBootReady() {
  React.useEffect(() => {
    const id = requestAnimationFrame(() => bootStep(3))
    return () => cancelAnimationFrame(id)
  }, [])
}

/** The app shell: the loader ends once the first queries (auth, shell, page data) have answered - checked after
 *  each query change, a frame apart so a query started by the first render is seen, then on the next idle moment so
 *  the renders those answers cause are done before the logo's end is scheduled - or after 1.5 s at most (slow data: the
 *  page shows its own placeholders). */
/** Queries the first screen does not wait for (side panels, meters, background lists). */
const BOOT_SKIP = new Set(['health', 'feed', 'team', 'agents', 'agent-groups', 'stats', 'mail', 'infra', 'mcp', 'approvals', 'docs', 'trash'])

export function useBootReadyWhenIdle() {
  const qc = useQueryClient()
  React.useEffect(() => {
    if (!window.mxStep) return
    let frame = 0
    let idle = 0
    const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (id: number) => void }
    const stopIdle = () => {
      if (idle) (w.cancelIdleCallback ?? clearTimeout)(idle)
    }
    const done = () => {
      unsubscribe()
      clearTimeout(cap)
      cancelAnimationFrame(frame)
      stopIdle()
      bootStep(3)
    }
    const check = () => {
      cancelAnimationFrame(frame)
      stopIdle()
      idle = 0
      frame = requestAnimationFrame(() => {
        if (qc.isFetching({ predicate: (q) => !BOOT_SKIP.has(String(q.queryKey[0])) && !(q.queryKey[0] === 'system' && q.queryKey[1] === 'usage') }) !== 0) return
        idle = w.requestIdleCallback ? w.requestIdleCallback(done, { timeout: 250 }) : window.setTimeout(done, 0)
      })
    }
    const unsubscribe = qc.getQueryCache().subscribe(check)
    const cap = setTimeout(done, 1500)
    check()
    return () => {
      unsubscribe()
      clearTimeout(cap)
      cancelAnimationFrame(frame)
      stopIdle()
    }
  }, [qc])
}

/** `useBootReady` as an element, for a branch of a component (an error screen). */
export function BootReady() {
  useBootReady()
  return null
}
