// The drag handle on the right edge of a sidebar (the main one when pinned, the second-level one when open).
import * as React from 'react'
import { useT } from '@/i18n'

/** Right edge: drag to resize `side` between `min` and `max`, saved by `onWidth` (double-click: null = the default).
 *  `edge="left"`: the handle sits on the left edge of a panel docked on the right (dragging left widens it). */
export function ResizeEdge({ side, min, max, onWidth, edge = 'right', className = '' }: { side: React.RefObject<HTMLElement | null>; min: number; max: number; onWidth: (w: number | null) => void; edge?: 'left' | 'right'; className?: string }) {
  const t = useT()
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={t('shell.resize')}
      title={t('shell.resize')}
      onDoubleClick={() => onWidth(null)}
      onPointerDown={(e) => {
        const el = side.current
        if (!el || e.button !== 0) return
        e.preventDefault()
        const target = e.currentTarget
        target.setPointerCapture(e.pointerId)
        const startX = e.clientX
        const startW = el.getBoundingClientRect().width
        let w = startW
        let moved = false // a tap on the handle saves nothing (the width on screen may be outside min / max)
        const onMove = (ev: PointerEvent) => {
          moved = true
          w = Math.max(min, Math.min(max, startW + (edge === 'left' ? startX - ev.clientX : ev.clientX - startX)))
          el.style.width = `${w}px`
        }
        const onUp = () => {
          target.removeEventListener('pointermove', onMove)
          target.removeEventListener('pointerup', onUp)
          target.removeEventListener('pointercancel', onUp)
          document.body.style.cursor = ''
          document.body.style.userSelect = ''
          if (moved) onWidth(w)
        }
        document.body.style.cursor = 'col-resize'
        document.body.style.userSelect = 'none'
        target.addEventListener('pointermove', onMove)
        target.addEventListener('pointerup', onUp)
        target.addEventListener('pointercancel', onUp)
      }}
      className={`absolute inset-y-0 ${edge === 'left' ? '-left-1' : '-right-1'} z-40 w-2 cursor-col-resize touch-none after:absolute after:inset-y-0 after:left-[3px] after:w-[3px] after:transition-colors hover:after:bg-primary/40 active:after:bg-primary/60 ${className}`}
    />
  )
}
