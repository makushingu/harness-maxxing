// Tabs view (Tabs.tsx): the session that comes on screen slides in a little from the side of its tab (to the right
// of the previous one: from the right) and fades in, 200 ms, transform + opacity only. The columns stay mounted
// (hidden ones are `display: none`), so nothing reloads or loses its place: only the shown one moves.
import * as React from 'react'
import { EASE_OUT, reducedMotion } from '@/lib/presence'

export const TAB_MS = 200
/** Going from Tabs to Zones or back (useModeMotion). */
export const MODE_MS = 340
const MODE_STEP = 35

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

/** Tabs <-> Zones (computer): the change of mode moves instead of jumping, the way the icon of its button does.
 *  To Zones, every session comes down from its tab: it slides from the tab's place to its column while it unrolls
 *  from the top, one after the other. To Tabs, every tab rises from the column its session was in, and the session
 *  that stays on screen glides from its column to the middle. Transform, opacity and clip-path only (no layout per
 *  frame); the places "before" are read while the change renders, the commit has not moved anything yet. */
export function useModeMotion(tabs: boolean, keys: string[], shown: string | undefined, col: (key: string) => HTMLElement | null, bar: React.RefObject<HTMLElement | null>) {
  const chip = (k: string) => bar.current?.querySelector<HTMLElement>(`[data-tab="${CSS.escape(k)}"]`) ?? null
  const was = React.useRef(tabs)
  const before = React.useRef<Map<string, DOMRect> | null>(null)
  if (was.current !== tabs) {
    was.current = tabs
    const from = new Map<string, DOMRect>()
    if (!reducedMotion())
      for (const k of keys) {
        const r = (tabs ? col(k) : chip(k))?.getBoundingClientRect()
        if (r?.width) from.set(k, r)
      }
    before.current = from
  }
  const keysNow = React.useRef(keys)
  keysNow.current = keys
  React.useLayoutEffect(() => {
    const from = before.current
    before.current = null
    if (!from?.size) return
    const order = keysNow.current
    if (tabs) {
      order.forEach((k, i) => {
        const el = chip(k)
        const b = from.get(k)
        if (!el || !b) return
        const dx = b.left - el.getBoundingClientRect().left
        el.animate([{ opacity: 0, transform: `translate(${dx}px, 18px)` }, { opacity: 1, transform: 'none' }], { duration: MODE_MS, delay: i * MODE_STEP, easing: EASE_OUT, fill: 'backwards' })
      })
      const el = shown ? col(shown) : null
      const b = shown ? from.get(shown) : undefined
      if (el && b) {
        const r = el.getBoundingClientRect()
        const dx = b.left + b.width / 2 - (r.left + r.width / 2)
        el.animate([{ opacity: 0.25, transform: `translateX(${dx}px)` }, { opacity: 1, transform: 'none' }], { duration: MODE_MS, easing: EASE_OUT })
      }
      return
    }
    let i = 0
    for (const k of order) {
      const el = col(k)
      const b = from.get(k)
      if (!el || !b) continue
      const dx = b.left - el.getBoundingClientRect().left
      el.animate(
        [
          { opacity: 0, transform: `translateX(${dx}px)`, clipPath: 'inset(0 0 100% 0)' },
          { opacity: 1, transform: 'none', clipPath: 'inset(0 0 0 0)' },
        ],
        { duration: MODE_MS, delay: i++ * MODE_STEP, easing: EASE_OUT, fill: 'backwards' },
      )
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabs])
}
