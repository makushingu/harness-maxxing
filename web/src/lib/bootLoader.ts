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
  }
}

export const bootStep = (n: 1 | 2 | 3) => window.mxStep?.(n)

/** A screen with nothing to wait for (sign-in, setup, onboarding, an error): the loader can end once it is painted. */
export function useBootReady() {
  React.useEffect(() => {
    const id = requestAnimationFrame(() => bootStep(3))
    return () => cancelAnimationFrame(id)
  }, [])
}

/** The app shell: the loader ends once the first queries (auth, shell, page data) have answered - checked after
 *  each query change, a frame apart so a query started by the first render is seen - or after 4 s at most (slow
 *  data: the page shows its own placeholders). */
export function useBootReadyWhenIdle() {
  const qc = useQueryClient()
  React.useEffect(() => {
    if (!window.mxStep) return
    let frame = 0
    const done = () => {
      unsubscribe()
      clearTimeout(cap)
      cancelAnimationFrame(frame)
      bootStep(3)
    }
    const check = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        if (qc.isFetching() === 0) done()
      })
    }
    const unsubscribe = qc.getQueryCache().subscribe(check)
    const cap = setTimeout(done, 4000)
    check()
    return () => {
      unsubscribe()
      clearTimeout(cap)
      cancelAnimationFrame(frame)
    }
  }, [qc])
}

/** `useBootReady` as an element, for a branch of a component (an error screen). */
export function BootReady() {
  useBootReady()
  return null
}
