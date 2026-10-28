import * as React from 'react'
import { isCompact } from '@/stores/media'
// Swipe down to close a bottom sheet (Sheet, Dialog on phones). Touch only, no dependency.
// - The sheet follows the finger from its handle, its header or any content that is scrolled to the top;
//   a list that can still scroll up keeps the gesture (the finger scrolls it, the sheet stays).
// - Released past a quarter of its height, or flicked down, the sheet slides out (the closed-state animation
//   picks up from where the finger left it); otherwise it springs back.
// - Fields, sliders and horizontally scrolling rows never start a drag.

const NO_DRAG = 'input, textarea, select, [contenteditable=""], [contenteditable="true"], [data-no-drag], [role="slider"]'

function scrollerAbove(target: Element, root: HTMLElement): HTMLElement | null {
  for (let el: Element | null = target; el && el !== root.parentElement; el = el.parentElement) {
    if (!(el instanceof HTMLElement)) continue
    const oy = getComputedStyle(el).overflowY
    if ((oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 1) return el
  }
  return null
}

/** `active()` tells whether the content is a bottom sheet right now (phones, or side="bottom" everywhere). */
export function useSheetDrag(onDismiss: () => void, active: () => boolean, overlay?: React.RefObject<HTMLElement | null>) {
  const dismiss = React.useRef(onDismiss)
  dismiss.current = onDismiss
  // Callback ref (React 19 cleanup): the content mounts and unmounts with the open state.
  return React.useCallback(
    (node: HTMLElement | null) => {
      if (!node) return
      let y0 = 0
      let x0 = 0
      let dy = 0
      let trail: { y: number; t: number }[] = [] // last positions, for the release speed
      let state: 'idle' | 'maybe' | 'drag' | 'off' = 'idle'
      let scroller: HTMLElement | null = null
      const set = (y: number, animate: boolean) => {
        const ease = animate ? 'transform 260ms cubic-bezier(0.32, 0.72, 0, 1)' : 'none'
        node.style.transition = ease
        node.style.transform = y ? `translateY(${y}px)` : ''
        const o = overlay?.current
        if (o) {
          o.style.transition = animate ? 'opacity 260ms ease' : 'none'
          o.style.opacity = y ? String(Math.max(0, 1 - y / node.offsetHeight)) : ''
        }
      }
      const start = (e: TouchEvent) => {
        if (state === 'drag') set(0, true) // a second finger mid-drag: the sheet springs back, the gesture ends
        state = 'idle'
        if (e.touches.length !== 1 || !active()) return
        const target = e.target as Element
        if (target.closest(NO_DRAG)) return
        scroller = scrollerAbove(target, node)
        y0 = e.touches[0].clientY
        x0 = e.touches[0].clientX
        dy = 0
        state = 'maybe'
      }
      const move = (e: TouchEvent) => {
        if (state === 'idle' || state === 'off') return
        const y = e.touches[0].clientY - y0
        const x = e.touches[0].clientX - x0
        if (state === 'maybe') {
          if (Math.abs(x) < 4 && Math.abs(y) < 4) return
          // Down, mostly vertical, and nothing above to scroll back to: the sheet takes the gesture.
          if (y <= 0 || Math.abs(x) > Math.abs(y) || (scroller && scroller.scrollTop > 0)) {
            state = 'off'
            return
          }
          state = 'drag'
          y0 += y // no jump: the sheet starts following from here
          trail = []
        }
        e.preventDefault()
        const d = e.touches[0].clientY - y0
        // Pulled up past its rest position: strong resistance.
        dy = d < 0 ? -Math.sqrt(-d) * 2 : d
        set(dy, false)
        const now = performance.now()
        trail.push({ y: dy, t: now })
        while (trail.length > 2 && now - trail[0].t > 100) trail.shift()
      }
      const end = () => {
        if (state !== 'drag') {
          state = 'idle'
          return
        }
        state = 'idle'
        // Speed over the last ~100 ms (px/ms): a flick counts even after a slow start.
        const first = trail[0]
        const speed = first && performance.now() - first.t < 200 ? (dy - first.y) / Math.max(16, performance.now() - first.t) : 0
        if (dy > node.offsetHeight * 0.25 || (dy > 24 && speed > 0.4)) {
          node.style.transition = 'none'
          if (overlay?.current) overlay.current.style.transition = 'none'
          if (navigator.vibrate) navigator.vibrate(8)
          dismiss.current()
        } else set(0, true)
      }
      node.addEventListener('touchstart', start, { passive: true })
      node.addEventListener('touchmove', move, { passive: false })
      node.addEventListener('touchend', end)
      node.addEventListener('touchcancel', end)
      return () => {
        node.removeEventListener('touchstart', start)
        node.removeEventListener('touchmove', move)
        node.removeEventListener('touchend', end)
        node.removeEventListener('touchcancel', end)
      }
    },
    [active, overlay],
  )
}

const mobile = () => isCompact()
const always = () => true
/** Bottom-sheet test for the shared primitives: `bottom` forces it, otherwise phones only (< md). */
export const sheetIsBottom = (bottom: boolean) => (bottom ? always : mobile)

/** Menus, lists of choices and pickers on phones (`.mx-sheet`, globals.css): swipe down closes them like the
 *  Escape key would (Radix listens on the document). */
export function useMenuSheetDrag<T extends HTMLElement>(ref?: React.Ref<T>) {
  const node = React.useRef<HTMLElement | null>(null)
  const drag = useSheetDrag(() => node.current?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })), mobile)
  return React.useMemo(
    () => (el: T | null) => {
      node.current = el
      drag(el)
      if (typeof ref === 'function') ref(el)
      else if (ref) (ref as React.RefObject<T | null>).current = el
    },
    [drag, ref],
  )
}
