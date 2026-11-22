import * as React from 'react'
import type { createBrowserRouter } from 'react-router'
import { createBackStack } from '@/lib/back-stack'

type Router = ReturnType<typeof createBrowserRouter>
let stack: ReturnType<typeof createBackStack> | null = null
let router: Router | null = null
let urlOpened = { key: '', at: 0 }

/** Called once with the app's router: knows when a navigation is in flight, and which overlays the URL opened. */
export function watchBack(r: Router) {
  router = r
  let prev = r.state.location
  r.subscribe((s) => {
    if (s.location.key === prev.key) return
    // Same page, other query (`?task=…`, `?chat=…`): an overlay that opens now has its own history entry already.
    if (s.historyAction === 'PUSH' && s.location.pathname === prev.pathname) urlOpened = { key: s.location.key, at: Date.now() }
    prev = s.location
  })
  return r
}

/** Rendered inside an overlay's content: on a touch screen, Back closes the overlay instead of leaving the page. */
export function BackCloses({ close }: { close: () => void }) {
  const fn = React.useRef(close)
  fn.current = close
  React.useEffect(() => {
    if (!window.matchMedia?.('(pointer: coarse)').matches) return
    if (router && urlOpened.key === router.state.location.key && Date.now() - urlOpened.at < 1000) return
    stack ??= createBackStack(window)
    const release = stack.push(() => fn.current())
    return () => release(!!router && router.state.navigation.state !== 'idle')
  }, [])
  return null
}
