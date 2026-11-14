// The bar beside the current page in the sidebar and the row's highlight (the pill: `bg-accent`, liquid glass in the
// Glass material). When the page changes, both glide from where the previous ones were (FLIP: one transform animation, composited), so the eye follows the click. Not when the bar
// changed shape since (folded / unfolded / pinned: the effect runs again and only records), from far away, or with
// reduced motion.
import * as React from 'react'
import { EASE_OUT, reducedMotion } from '@/lib/presence'

/** Where the last mark stood (viewport), and in which state of the bar. */
let last: { top: number; height: number; collapsed: boolean } | null = null

export function ActiveMark({ className, collapsed }: { className: string; collapsed: boolean }) {
  const ref = React.useRef<HTMLSpanElement>(null)
  const pill = React.useRef<HTMLSpanElement>(null)
  React.useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const from = last
    last = { top: r.top, height: r.height, collapsed }
    if (!from || from.collapsed !== collapsed || reducedMotion() || !r.height) return
    const dy = from.top - r.top
    if (Math.abs(dy) < 2 || Math.abs(dy) > 800) return
    el.animate([{ transform: `translateY(${dy}px) scaleY(${from.height / r.height})` }, { transform: 'none' }], { duration: 260, easing: EASE_OUT })
    pill.current?.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }], { duration: 260, easing: EASE_OUT })
  }, [collapsed])
  return (
    <>
      {/* behind the row's icon and label: the row is `isolate` (navRow), so -z-10 stays inside it */}
      <span ref={pill} aria-hidden className="mx-lg-pill pointer-events-none absolute inset-0 -z-10 rounded-md bg-accent" />
      <span ref={ref} aria-hidden className={className} />
    </>
  )
}
