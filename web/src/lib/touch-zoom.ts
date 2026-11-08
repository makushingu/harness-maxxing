// Fingers on a zoomable surface (image, diagram, text): two fingers pinch (and move while pinching), one finger
// may pan, a double tap toggles. The page itself never zooms (see mobile-viewport.ts): an element using this hook is
// marked `data-pinch` and cancels its own two-finger moves; the document guard leaves those alone.
import * as React from 'react'

export const PINCH_ATTR = 'data-pinch'

export type Pt = { x: number; y: number }
export type TouchZoomHandlers = {
  /** Two fingers are down. Return false to ignore this pinch. */
  pinchStart?: (mid: Pt) => boolean | void
  /** `scale` = distance between the fingers / distance at the start; `mid` = their midpoint now (client px). */
  pinch?: (scale: number, mid: Pt) => void
  pinchEnd?: (mid: Pt) => void
  /** One finger moved by (dx, dy). Return true when it was used (the browser then does not scroll). */
  pan?: (dx: number, dy: number) => boolean
  /** The panning finger left, at (vx, vy) px/ms. */
  panEnd?: (vx: number, vy: number) => void
  doubleTap?: (p: Pt) => void
}

const TAP_MS = 300
const TAP_SLOP = 10
const DOUBLE_SLOP = 30

const dist = (a: Touch, b: Touch) => Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) || 1
const midOf = (a: Touch, b: Touch): Pt => ({ x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 })

/** Touch Events (as the rest of the app's touch code), native and non-passive so the moves can be cancelled.
 *  `mountKey`: the element behind `ref` was re-created. */
export function useTouchZoom(ref: React.RefObject<HTMLElement | null>, handlers: TouchZoomHandlers, mountKey: unknown = null) {
  const h = React.useRef(handlers)
  h.current = handlers
  React.useEffect(() => {
    const el = ref.current
    if (!el) return
    el.setAttribute(PINCH_ATTR, '')
    let pinch: { d0: number; mid: Pt; scale: number } | null = null
    let one: { id: number; x0: number; y0: number; x: number; y: number; t0: number; moved: boolean; samples: { x: number; y: number; t: number }[] } | null = null
    /** More than one finger touched since the last time all were up: no tap. */
    let multi = false
    let lastTap: { x: number; y: number; t: number } | null = null
    let frame = 0
    let queued: { scale: number; mid: Pt } | null = null

    const flush = () => {
      frame = 0
      const q = queued
      queued = null
      if (q) h.current.pinch?.(q.scale, q.mid)
    }
    const startOne = (t: Touch, moved: boolean) => {
      one = { id: t.identifier, x0: t.clientX, y0: t.clientY, x: t.clientX, y: t.clientY, t0: Date.now(), moved, samples: [{ x: t.clientX, y: t.clientY, t: performance.now() }] }
    }
    const endPinch = () => {
      if (!pinch) return
      if (frame) {
        cancelAnimationFrame(frame)
        flush()
      }
      const mid = pinch.mid
      pinch = null
      h.current.pinchEnd?.(mid)
    }

    const onStart = (e: TouchEvent) => {
      if (e.touches.length >= 2) {
        multi = true
        lastTap = null
        if (one?.moved) h.current.panEnd?.(0, 0)
        one = null
        if (pinch || !h.current.pinch) return
        const [a, b] = [e.touches[0], e.touches[1]]
        const mid = midOf(a, b)
        if (h.current.pinchStart?.(mid) === false) return
        pinch = { d0: dist(a, b), mid, scale: 1 }
        if (e.cancelable) e.preventDefault()
      } else if (e.touches.length === 1) {
        multi = false
        startOne(e.touches[0], false)
      }
    }
    const onMove = (e: TouchEvent) => {
      // Two fingers never zoom the page here, even when this surface ignores the pinch.
      if (e.touches.length >= 2 && e.cancelable) e.preventDefault()
      if (pinch && e.touches.length >= 2) {
        const [a, b] = [e.touches[0], e.touches[1]]
        pinch.mid = midOf(a, b)
        pinch.scale = dist(a, b) / pinch.d0
        queued = { scale: pinch.scale, mid: pinch.mid }
        if (!frame) frame = requestAnimationFrame(flush)
        return
      }
      if (e.touches.length !== 1 || !one) return
      const t = e.touches[0]
      if (t.identifier !== one.id) return startOne(t, true)
      const dx = t.clientX - one.x
      const dy = t.clientY - one.y
      one.x = t.clientX
      one.y = t.clientY
      if (!one.moved && Math.hypot(t.clientX - one.x0, t.clientY - one.y0) > TAP_SLOP) one.moved = true
      const now = performance.now()
      one.samples.push({ x: t.clientX, y: t.clientY, t: now })
      while (one.samples.length > 2 && now - one.samples[0].t > 100) one.samples.shift()
      if (h.current.pan?.(dx, dy) && e.cancelable) e.preventDefault()
    }
    const onEnd = (e: TouchEvent) => {
      if (pinch && e.touches.length < 2) endPinch()
      else if (pinch) {
        // A third finger was down and one of the pair left: the new pair goes on from the scale reached.
        const [a, b] = [e.touches[0], e.touches[1]]
        pinch.d0 = dist(a, b) / pinch.scale
        pinch.mid = midOf(a, b)
      }
      if (e.touches.length === 1) {
        // One finger stays after a pinch: it pans from where it is (never a tap).
        startOne(e.touches[0], true)
        return
      }
      if (e.touches.length > 0) return
      const o = one
      one = null
      const wasMulti = multi
      multi = false
      if (!o || wasMulti) return
      if (o.moved) {
        const s = o.samples
        const first = s[0]
        const last = s[s.length - 1]
        const dt = last.t - first.t
        // A finger held still before it lifts throws nothing: the last moves are old.
        const live = dt > 0 && performance.now() - last.t <= 100
        h.current.panEnd?.(live ? (last.x - first.x) / dt : 0, live ? (last.y - first.y) / dt : 0)
        return
      }
      if (e.type === 'touchcancel' || Date.now() - o.t0 > TAP_MS) return (lastTap = null)
      const now = Date.now()
      if (h.current.doubleTap && lastTap && now - lastTap.t < TAP_MS && Math.hypot(o.x - lastTap.x, o.y - lastTap.y) < DOUBLE_SLOP) {
        lastTap = null
        // No synthetic click / dblclick after this: the double tap is handled here once.
        if (e.cancelable) e.preventDefault()
        h.current.doubleTap({ x: o.x, y: o.y })
        return
      }
      lastTap = { x: o.x, y: o.y, t: now }
    }

    const opts = { passive: false } as const
    el.addEventListener('touchstart', onStart, opts)
    el.addEventListener('touchmove', onMove, opts)
    el.addEventListener('touchend', onEnd, opts)
    el.addEventListener('touchcancel', onEnd, opts)
    return () => {
      cancelAnimationFrame(frame)
      el.removeAttribute(PINCH_ATTR)
      el.removeEventListener('touchstart', onStart)
      el.removeEventListener('touchmove', onMove)
      el.removeEventListener('touchend', onEnd)
      el.removeEventListener('touchcancel', onEnd)
    }
  }, [ref, mountKey])
}
