// Tabs view (Tabs.tsx): the session that comes on screen slides in a little from the side of its tab (to the right
// of the previous one: from the right) and fades in, 200 ms, transform + opacity only. The columns stay mounted
// (hidden ones are `display: none`), so nothing reloads or loses its place: only the shown one moves.
import * as React from 'react'
import { EASE_OUT, reducedMotion } from '@/lib/presence'

export const TAB_MS = 200

export function useTabSwitchMotion(on: boolean, shown: string | undefined, order: string[], el: (key: string) => HTMLElement | null) {
  const prev = React.useRef<string | undefined>(undefined)
  const orderNow = React.useRef(order)
  orderNow.current = order
  React.useLayoutEffect(() => {
    const from = prev.current
    prev.current = on ? shown : undefined
    if (!on || !shown || !from || from === shown || reducedMotion()) return
    const node = el(shown)
    if (!node) return
    const a = orderNow.current.indexOf(from)
    const b = orderNow.current.indexOf(shown)
    // the previous tab was closed (no index): a plain fade
    const dx = a < 0 || b < 0 ? 0 : b > a ? 18 : -18
    node.animate([{ opacity: 0, transform: `translateX(${dx}px)` }, { opacity: 1, transform: 'none' }], { duration: TAB_MS, easing: EASE_OUT })
  }, [on, shown, el])
}

/** The tabs bar's underline: one element that glides (translate + scaleX, composited) under the selected chip. */
export function useTabIndicator(bar: React.RefObject<HTMLElement | null>, mark: React.RefObject<HTMLElement | null>, deps: React.DependencyList) {
  const placed = React.useRef(false)
  React.useLayoutEffect(() => {
    const list = bar.current
    const line = mark.current
    if (!list || !line) return
    const place = () => {
      const chip = list.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')
      if (!chip) {
        line.style.opacity = '0'
        return
      }
      const first = !placed.current || reducedMotion()
      line.style.transition = first ? 'none' : ''
      line.style.opacity = '1'
      // 100 px wide at scale 1: scaleX gives the chip's width without a layout per frame
      line.style.transform = `translateX(${chip.offsetLeft + 10}px) scaleX(${Math.max(0, chip.offsetWidth - 20) / 100})`
      placed.current = true
    }
    place()
    const ro = new ResizeObserver(place)
    ro.observe(list)
    for (const c of list.querySelectorAll('[role="tab"]')) ro.observe(c)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}
