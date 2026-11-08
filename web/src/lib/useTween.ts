import { useEffect, useRef, useState, type RefObject } from 'react'

/** True when the user asked the system for less motion (read at call time: the setting can change live). */
export function reducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

const easeOut = (x: number) => 1 - (1 - x) ** 3

/** A number that glides to `target` (ease-out, `ms` long) instead of jumping: the figures of the status panel.
 *  The first value shows as is; under prefers-reduced-motion every change is instant. */
export function useTween(target: number, ms = 500): number {
  const [shown, setShown] = useState(target)
  const shownRef = useRef(target)
  useEffect(() => {
    const from = shownRef.current
    if (!Number.isFinite(target) || !Number.isFinite(from) || from === target || reducedMotion()) {
      shownRef.current = target
      setShown(target)
      return
    }
    const start = performance.now()
    let raf = 0
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / ms)
      const v = from + (target - from) * easeOut(k)
      shownRef.current = v
      setShown(v)
      if (k < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return shown
}

/** A one-shot gentle "breath" (scale 1 -> 1.08 -> 1, 700 ms, ease-in-out) of the element each time `key` changes
 *  after the first render: an icon whose colour just crossed a threshold. Nothing under prefers-reduced-motion. */
export function usePulseOnChange<T extends Element>(key: unknown, ref: RefObject<T | null>) {
  const prev = useRef(key)
  useEffect(() => {
    if (prev.current === key) return
    prev.current = key
    const el = ref.current
    if (!el || reducedMotion() || typeof el.animate !== 'function') return
    el.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.08)', offset: 0.45 }, { transform: 'scale(1)' }], { duration: 700, easing: 'cubic-bezier(0.37, 0, 0.63, 1)' })
  }, [key, ref])
}
