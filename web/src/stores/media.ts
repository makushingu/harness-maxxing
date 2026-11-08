import { useSyncExternalStore } from 'react'
import { useUI, type Layout } from './ui'

// One MediaQueryList per query (its `matches` is live): `matchMedia()` parses the query and builds a new object on
// every call, and the snapshots below are read on every render of every user (twice per commit).
const lists = new Map<string, MediaQueryList>()
const mql = (q: string) => {
  let m = lists.get(q)
  if (!m) lists.set(q, (m = window.matchMedia(q)))
  return m
}

/** Live media query (no flicker: read synchronously on first render). */
export function useMediaQuery(q: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = mql(q)
      m.addEventListener('change', cb)
      return () => m.removeEventListener('change', cb)
    },
    () => mql(q).matches,
    () => false,
  )
}

const NARROW = '(max-width: 767px)'
const TOUCH = '(pointer: coarse) and (hover: none)'

/** Touch layout (phones, tablets, narrow windows): no sidebar, the sessions and the app behind two buttons at the
 *  top. Copied in index.html (applied before the first paint) - keep both in sync. */
export function isCompact(layout: Layout = useUI.getState().layout): boolean {
  if (typeof window === 'undefined') return false
  if (mql(NARROW).matches || layout === 'touch') return true
  return layout !== 'desktop' && mql(TOUCH).matches
}

function subscribe(cb: () => void) {
  const qs = [NARROW, TOUCH].map(mql)
  qs.forEach((m) => m.addEventListener('change', cb))
  const unsub = useUI.subscribe((s, prev) => s.layout !== prev.layout && cb())
  return () => {
    qs.forEach((m) => m.removeEventListener('change', cb))
    unsub()
  }
}

/** Live `isCompact()`. Same decision as the `md:` / `max-md:` Tailwind variants (html[data-compact]). */
export const useCompact = () => useSyncExternalStore(subscribe, () => isCompact(), () => false)

/** Keeps html[data-compact] in sync (called once from main.tsx). */
export function bindCompact() {
  const apply = () => document.documentElement.toggleAttribute('data-compact', isCompact())
  apply()
  subscribe(apply)
}

/** Kept for the callers that mean "touch layout". */
export const useIsMobile = useCompact
/** A desktop-layout window between 768 and 1023 px: the sidebar folds to icons. */
export function useIsTablet() {
  const mid = useMediaQuery('(min-width: 768px) and (max-width: 1023px)')
  const compact = useCompact()
  return mid && !compact
}
