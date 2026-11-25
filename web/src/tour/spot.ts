// The spotlight shared by the showcases (Tour.tsx) and the getting-started guide (guide/Guide.tsx): find the
// `data-tour` targets on screen, cut a hole around them, place a card beside it.
import * as React from 'react'

export type Rect = { x: number; y: number; w: number; h: number }
export const PAD = 6

/** First visible element for each target id, unioned. */
export function measure(targets: string[]): Rect | null {
  let r: Rect | null = null
  for (const id of targets) {
    const els = document.querySelectorAll<HTMLElement>(`[data-tour="${id}"]`)
    for (const el of els) {
      const b = el.getBoundingClientRect()
      if (b.width < 1 || b.height < 1 || getComputedStyle(el).visibility === 'hidden') continue
      if (!r) r = { x: b.left, y: b.top, w: b.width, h: b.height }
      else {
        const x = Math.min(r.x, b.left)
        const y = Math.min(r.y, b.top)
        r = { x, y, w: Math.max(r.x + r.w, b.right) - x, h: Math.max(r.y + r.h, b.bottom) - y }
      }
      break
    }
  }
  return r
}
export function firstEl(targets: string[]): HTMLElement | null {
  for (const id of targets)
    for (const el of document.querySelectorAll<HTMLElement>(`[data-tour="${id}"]`)) {
      const b = el.getBoundingClientRect()
      if (b.width >= 1 && b.height >= 1) return el
    }
  return null
}
export const sameRect = (a: Rect | null, b: Rect | null) =>
  a === b || (!!a && !!b && Math.abs(a.x - b.x) < 0.5 && Math.abs(a.y - b.y) < 0.5 && Math.abs(a.w - b.w) < 0.5 && Math.abs(a.h - b.h) < 0.5)

/** Padded target rect, kept 3 px inside the viewport so the ring is never cut by the screen edge. */
export function clampHole(r: Rect): Rect {
  const m = 3
  const x = Math.max(m, r.x - PAD)
  const y = Math.max(m, r.y - PAD)
  const right = Math.min(window.innerWidth - m, r.x + r.w + PAD)
  const bottom = Math.min(window.innerHeight - m, r.y + r.h + PAD)
  return { x, y, w: Math.max(0, right - x), h: Math.max(0, bottom - y) }
}

/** Card placement: desktop = beside the hole (right, below, above, left — first that fits), clamped to the
 *  viewport; mobile = a full-width card at the top or the bottom, away from the target. */
export function useCardPosition(hole: Rect | null, mobile: boolean, card: React.RefObject<HTMLDivElement | null>, key: number): React.CSSProperties {
  const [size, setSize] = React.useState({ w: 340, h: 180 })
  React.useLayoutEffect(() => {
    const el = card.current
    if (!el) return
    const read = () => setSize((s) => (s.w === el.offsetWidth && s.h === el.offsetHeight ? s : { w: el.offsetWidth, h: el.offsetHeight }))
    const ro = new ResizeObserver(read)
    ro.observe(el)
    read()
    return () => ro.disconnect()
  }, [card, key])
  if (!hole) return { left: '50%', top: '50%', transform: 'translate(-50%, -50%)' }
  const vw = window.innerWidth
  const vh = window.innerHeight
  const gap = 12
  const m = 12
  if (mobile) {
    if (vh - (hole.y + hole.h) >= size.h + gap + m) return { top: hole.y + hole.h + gap }
    if (hole.y >= size.h + gap + m) return { bottom: vh - hole.y + gap }
    return { bottom: 'calc(var(--safe-bottom-ui) + 12px)' }
  }
  const clampX = (x: number) => Math.max(m, Math.min(vw - size.w - m, x))
  const clampY = (y: number) => Math.max(m, Math.min(vh - size.h - m, y))
  if (hole.x + hole.w + gap + size.w + m <= vw && hole.w < vw / 2) return { left: hole.x + hole.w + gap, top: clampY(hole.y) }
  if (hole.y + hole.h + gap + size.h + m <= vh) return { left: clampX(hole.x), top: hole.y + hole.h + gap }
  if (hole.y - gap - size.h >= m) return { left: clampX(hole.x), top: hole.y - gap - size.h }
  if (hole.x - gap - size.w >= m) return { left: hole.x - gap - size.w, top: clampY(hole.y) }
  return { left: clampX(hole.x), top: m }
}
