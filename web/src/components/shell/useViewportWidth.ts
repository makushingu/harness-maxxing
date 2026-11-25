import * as React from 'react'

const read = () => (typeof window === 'undefined' ? 1280 : window.innerWidth)
const subscribe = (cb: () => void) => {
  window.addEventListener('resize', cb)
  return () => window.removeEventListener('resize', cb)
}

/** The window's width in CSS pixels, updated on resize. */
export function useViewportWidth(): number {
  return React.useSyncExternalStore(subscribe, read, read)
}
