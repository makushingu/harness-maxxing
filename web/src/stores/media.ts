import { useSyncExternalStore } from 'react'
import { useUI, type Layout } from './ui'

/** Live media query (no flicker: read synchronously on first render). */
export function useMediaQuery(q: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(q)
      m.addEventListener('change', cb)
      return () => m.removeEventListener('change', cb)
    },
    () => window.matchMedia(q).matches,
    () => false,
  )
}

const NARROW = '(max-width: 767px)'
const TOUCH = '(pointer: coarse) and (hover: none)'

/** Touch layout (phones, tablets, narrow windows): no sidebar, the sessions and the app behind two buttons at the
 *  top. Copied in index.html (applied before the first paint) - keep both in sync. */
export function isCompact(layout: Layout = useUI.getState().layout): boolean {
  if (typeof window === 'undefined') return false
  if (window.matchMedia(NARROW).matches || layout === 'touch') return true
  return layout !== 'desktop' && window.matchMedia(TOUCH).matches
}

function subscribe(cb: () => void) {
  const qs = [NARROW, TOUCH].map((q) => window.matchMedia(q))
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
