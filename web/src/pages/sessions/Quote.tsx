// Quote: selecting text inside ONE reply of Claude (thread or side-question answer) shows a small "Quote"
// pill above the selection (below it on touch, clear of the native menu); clicking it puts the text in the
// composer's quotes card. Hidden on Escape, scroll, a click elsewhere or an empty selection.
import * as React from 'react'
import { createPortal } from 'react-dom'
import { Quote } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'

type Pill = { x: number; y: number; below: boolean; text: string }

/** Reply the selection lies entirely in (rendered as `.mx-assistant` inside `scope`), or null. */
function selectedReply(scope: HTMLElement | null): { text: string; rect: DOMRect } | null {
  const sel = window.getSelection()
  if (!scope || !sel || sel.isCollapsed || !sel.rangeCount) return null
  const range = sel.getRangeAt(0)
  const node = range.commonAncestorContainer
  const reply = (node instanceof Element ? node : node.parentElement)?.closest('.mx-assistant')
  if (!reply || !scope.contains(reply)) return null
  const text = sel.toString().trim()
  if (!text) return null
  const rects = range.getClientRects()
  return { text, rect: rects.length ? range.getBoundingClientRect() : (reply as HTMLElement).getBoundingClientRect() }
}

export function QuotePill({ scope, onQuote }: { scope: React.RefObject<HTMLElement | null>; onQuote: (text: string) => void }) {
  const t = useT()
  const [pill, setPill] = React.useState<Pill | null>(null)

  React.useEffect(() => {
    let timer = 0
    let dragging = false
    let touch = false
    const update = () => {
      const hit = selectedReply(scope.current)
      if (!hit) return setPill(null)
      const { rect } = hit
      // Above the selection (below on touch, or when there is no room above), clamped to the viewport.
      const below = touch || rect.top < 56
      const x = Math.min(Math.max(rect.left + rect.width / 2, 56), window.innerWidth - 56)
      const y = below ? Math.min(rect.bottom + 8, window.innerHeight - 48) : rect.top - 8
      setPill({ x, y, below, text: hit.text })
    }
    const later = (ms: number) => {
      window.clearTimeout(timer)
      timer = window.setTimeout(update, ms)
    }
    const onDown = (e: PointerEvent) => {
      touch = e.pointerType !== 'mouse'
      if ((e.target as Element | null)?.closest?.('[data-mx-quote-pill]')) return
      dragging = e.pointerType === 'mouse'
      window.clearTimeout(timer)
      setPill(null)
    }
    const onUp = () => {
      if (!dragging) return
      dragging = false
      later(10)
    }
    // Mouse: shown on release. Touch / keyboard: once the selection has stopped changing.
    const onChange = () => {
      if (dragging) return
      const sel = window.getSelection()
      if (!sel || sel.isCollapsed) {
        window.clearTimeout(timer)
        setPill(null)
        return
      }
      later(touch ? 400 : 200)
    }
    const hide = () => {
      window.clearTimeout(timer)
      setPill(null)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && hide()
    const el = scope.current
    document.addEventListener('pointerdown', onDown, true)
    document.addEventListener('pointerup', onUp, true)
    document.addEventListener('pointercancel', onUp, true)
    document.addEventListener('selectionchange', onChange)
    document.addEventListener('keydown', onKey)
    el?.addEventListener('scroll', hide, true)
    window.addEventListener('resize', hide)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('pointerdown', onDown, true)
      document.removeEventListener('pointerup', onUp, true)
      document.removeEventListener('pointercancel', onUp, true)
      document.removeEventListener('selectionchange', onChange)
      document.removeEventListener('keydown', onKey)
      el?.removeEventListener('scroll', hide, true)
      window.removeEventListener('resize', hide)
    }
  }, [scope])

  if (!pill) return null
  return createPortal(
    <div className="pointer-events-none fixed z-50" style={{ left: pill.x, top: pill.y }}>
      <button
        type="button"
        data-mx-quote-pill
        aria-label={t('sessions.quote.tip')}
        title={t('sessions.quote.tip')}
        // Keeps the selection (and the focus) where it is.
        onPointerDown={(e) => e.preventDefault()}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => {
          onQuote(pill.text)
          setPill(null)
        }}
        className={cn(
          'mx-queue-in pointer-events-auto flex h-8 -translate-x-1/2 items-center gap-1.5 rounded-lg border bg-card px-2.5 text-[13px] font-medium whitespace-nowrap shadow-xs hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
          !pill.below && '-translate-y-full',
        )}
      >
        <Quote className="size-3.5 text-primary" /> {t('sessions.quote.action')}
      </button>
    </div>,
    document.body,
  )
}
