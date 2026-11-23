// The frame of the sidebar's preview cards (an agent's in features/agents/AgentPreview.tsx).
// Rendered in a portal (the bar is overflow-hidden) but as a React child of the rail: pointer enter / leave through
// the portal count as staying inside the bar, so hovering the card keeps the bar unfolded and leaving it folds it.
// No focus is ever moved into it, and nothing in it sets aria-expanded (the bar waits for those before folding).
import * as React from 'react'
import { createPortal } from 'react-dom'
import { reducedMotion } from '@/lib/presence'

/**
 * The frame every preview card of the rail shares (a session here, an agent in features/agents/AgentPreview.tsx): a
 * portal beside the rail, level with `anchor`, kept inside the window, fading in, crossfading its content when
 * `swapKey` changes. The transparent left padding bridges the rail and the card: the pointer never crosses a gap.
 */
export function PreviewShell({
  anchor,
  rail,
  width,
  maxHeight,
  swapKey,
  testId,
  onPointerEnter,
  onPointerLeave,
  children,
}: {
  anchor: HTMLElement
  rail: HTMLElement
  width: number
  maxHeight: number
  swapKey: string
  testId: string
  onPointerEnter: () => void
  onPointerLeave: () => void
  children: React.ReactNode
}) {
  const card = React.useRef<HTMLDivElement>(null)
  const body = React.useRef<HTMLDivElement>(null)
  const [pos, setPos] = React.useState<{ left: number; top: number } | null>(null)

  // Place it: beside the rail, level with the row, kept inside the window (measured again when the content grows).
  const place = React.useCallback(() => {
    const el = card.current
    if (!el) return
    const r = rail.getBoundingClientRect()
    const a = anchor.getBoundingClientRect()
    const h = el.offsetHeight
    const top = Math.max(8, Math.min(a.top - 10, window.innerHeight - h - 8))
    // a narrow window (two sidebars open at 768-1023 px): over the rail rather than cut at the right edge
    const left = Math.max(8, Math.min(r.right, window.innerWidth - el.offsetWidth - 8))
    setPos((p) => (p && p.left === left && p.top === top ? p : { left, top }))
  }, [anchor, rail])
  React.useLayoutEffect(place)
  React.useEffect(() => {
    const el = card.current
    if (!el) return
    const ro = new ResizeObserver(place)
    ro.observe(el)
    window.addEventListener('resize', place)
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', place)
    }
  }, [place])

  // Appears: fade + 4 px slide. Another row: a short crossfade of the content.
  const shown = pos !== null
  React.useEffect(() => {
    if (!shown || reducedMotion()) return
    card.current?.animate([{ opacity: 0, transform: 'translateX(-4px)' }, { opacity: 1, transform: 'none' }], { duration: 160, easing: 'ease-out' })
  }, [shown])
  const first = React.useRef(true)
  React.useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    if (!reducedMotion()) body.current?.animate([{ opacity: 0.25 }, { opacity: 1 }], { duration: 120, easing: 'ease-out' })
  }, [swapKey])

  return createPortal(
    <div
      ref={card}
      role="tooltip"
      data-testid={testId}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
      className="fixed z-50 pl-2"
      style={{
        width: width + 8,
        left: pos?.left ?? -9999,
        top: pos?.top ?? 0,
        visibility: pos ? 'visible' : 'hidden',
        transition: reducedMotion() ? undefined : 'top 120ms ease-out',
      }}
    >
      <div className="mx-glass flex flex-col overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-pop" style={{ maxHeight: `min(${maxHeight}px, calc(100vh - 16px))` }}>
        <div ref={body} className="flex min-h-0 flex-col">
          {children}
        </div>
      </div>
    </div>,
    document.body,
  )
}

