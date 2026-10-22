// Enter / leave animations for keyed lists, without a library.
// - usePresence(items, key): the list to render, where an item that just left stays (flag `leaving`) at its
//   place for `ms` so it can animate out; `appear` = the item arrived after the list was first shown
//   (items of the first non-empty render, e.g. the initial load, do not animate).
// - animateIn / animateOut / useFlip: Web Animations, transform and opacity only (no per-frame layout): the
//   leaving element is taken out of the flow and fades, the others slide to their new place (FLIP).
//   Nothing runs under prefers-reduced-motion.
import * as React from 'react'

export const PRESENCE_MS = 220
export const EASE_OUT = 'cubic-bezier(0.22, 1, 0.36, 1)'
const EASE_IN_OUT = 'cubic-bezier(0.4, 0, 0.2, 1)'

export type Presence<T> = { item: T; key: string; leaving: boolean; appear: boolean }
type Gone<T> = { item: T; after: string | null; at: number }

export const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** `ms = 0`: no animation (e.g. while a filter is typed: rows must follow at once). */
export function usePresence<T>(items: readonly T[], keyOf: (t: T) => string, ms = PRESENCE_MS): Presence<T>[] {
  const keys = items.map(keyOf)
  const sig = keys.join('\n')
  const [st, setSt] = React.useState<{ sig: string; items: readonly T[]; keys: string[]; gone: ReadonlyMap<string, Gone<T>> }>(() => ({
    sig,
    items,
    keys,
    gone: new Map(),
  }))
  const appeared = React.useRef(new Map<string, boolean>())
  const ready = React.useRef(false)

  // Derived during render (no commit without the leaving item: it is never unmounted and remounted).
  let cur = st
  if (st.sig !== sig) {
    const now = new Set(keys)
    const gone = new Map([...st.gone].filter(([k]) => !now.has(k)))
    if (ms > 0 && !reducedMotion()) {
      const at = Date.now()
      st.keys.forEach((k, i) => {
        if (!now.has(k)) gone.set(k, { item: st.items[i], after: i > 0 ? st.keys[i - 1] : null, at })
      })
    }
    cur = { sig, items, keys, gone }
    setSt(cur)
  }

  React.useEffect(() => {
    if (items.length) ready.current = true
  })

  // Leaving items are dropped once their animation is over.
  React.useEffect(() => {
    if (!cur.gone.size) return
    const oldest = Math.min(...[...cur.gone.values()].map((g) => g.at))
    const id = setTimeout(
      () =>
        setSt((s) => {
          const gone = new Map([...s.gone].filter(([, g]) => Date.now() - g.at < ms))
          for (const k of s.gone.keys()) if (!gone.has(k)) appeared.current.delete(k)
          return gone.size === s.gone.size ? s : { ...s, gone }
        }),
      Math.max(0, oldest + ms - Date.now()) + 20,
    )
    return () => clearTimeout(id)
  }, [cur.gone, ms])

  const out: Presence<T>[] = items.map((item, i) => {
    const key = keys[i]
    if (!appeared.current.has(key)) appeared.current.set(key, ready.current && ms > 0)
    return { item, key, leaving: false, appear: appeared.current.get(key)! }
  })
  for (const [key, g] of cur.gone) {
    const at = g.after === null ? 0 : out.findIndex((o) => o.key === g.after) + 1
    out.splice(at > 0 || g.after === null ? at : out.length, 0, { item: g.item, key, leaving: true, appear: false })
  }
  return out
}

/** Entrance: a fade and a short slide (transform + opacity only: nothing is laid out again per frame). */
export function animateIn(el: HTMLElement, axis: 'x' | 'y', ms = PRESENCE_MS) {
  if (reducedMotion()) return
  el.animate([{ opacity: 0, transform: axis === 'x' ? 'translateX(24px)' : 'translateY(-6px)' }, { opacity: 1, transform: 'none' }], {
    duration: ms,
    easing: EASE_OUT,
  })
}

/** Exit: the element leaves the layout at once (absolute, where it was - its parent must be `relative`) so
 * the others slide over it (useFlip), and fades out; it stays inert until it unmounts. */
export function animateOut(el: HTMLElement, axis: 'x' | 'y', ms = PRESENCE_MS) {
  el.inert = true
  el.style.pointerEvents = 'none'
  if (reducedMotion()) return
  const { offsetLeft: left, offsetTop: top, offsetWidth: w, offsetHeight: h } = el
  Object.assign(el.style, { position: 'absolute', left: `${left}px`, top: `${top}px`, width: `${w}px`, height: `${h}px`, margin: '0', zIndex: '0' })
  el.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: axis === 'x' ? 'scale(0.97)' : 'translateX(-8px)' }], {
    duration: ms * 0.8,
    easing: EASE_IN_OUT,
    fill: 'forwards',
  })
}

/** Elements that moved since the last layout (reorder, or the others arriving / leaving) slide from where
 * they were (FLIP, transform only). `els` = key → element; new elements animate themselves. */
export function useFlip(els: () => Map<string, HTMLElement>, deps: React.DependencyList, axis: 'x' | 'y' = 'x', ms = PRESENCE_MS) {
  // (ms = 0: positions are still recorded, nothing moves)
  const last = React.useRef(new Map<string, number>())
  React.useLayoutEffect(() => {
    const now = new Map<string, number>()
    const map = els()
    for (const [k, el] of map) {
      const r = el.getBoundingClientRect()
      now.set(k, axis === 'x' ? r.left : r.top)
    }
    if (ms > 0 && !reducedMotion())
      for (const [k, x] of now) {
        const before = last.current.get(k)
        const el = map.get(k)
        if (before === undefined || !el || Math.abs(before - x) < 1) continue
        el.animate([{ transform: `translate${axis === 'x' ? 'X' : 'Y'}(${before - x}px)` }, { transform: 'none' }], { duration: ms, easing: EASE_OUT })
      }
    last.current = now
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
}
