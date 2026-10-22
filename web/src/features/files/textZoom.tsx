// Text zoom control (− 100 % +, Ctrl/⌘ + wheel or a trackpad pinch over the text) and the markdown reader that keeps
// the reading position: same place after a zoom, a switch Preview / Edit / Split, or when the file is opened again.
import * as React from 'react'
import { Minus, Plus, Type } from 'lucide-react'
import { useT } from '@/i18n'
import { useMediaQuery } from '@/stores/media'
import { Button, Popover, PopoverContent, PopoverTrigger, Tooltip } from '@/components/ui'
import { cn } from '@/lib/utils'
import { MarkdownView } from './viewers'
import { fromHeading, getReadPos, headingAt, setReadPos, useTextZoom, type ReadPos } from './readPos'

/** Ctrl/⌘ + wheel (a trackpad pinch sends the same) over `ref` zooms the text instead of the whole page. */
export function useCtrlWheelZoom(ref: React.RefObject<HTMLElement | null>) {
  React.useEffect(() => {
    const el = ref.current
    if (!el) return
    let acc = 0
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      acc += e.deltaY
      if (Math.abs(acc) < 30) return
      useTextZoom.getState().step(acc < 0 ? 1 : -1)
      acc = 0
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [ref])
}

/** − 100% + in the toolbar; one "text size" button that opens it when the toolbar is narrow (`inlineFrom` = the
 *  smallest window width where it shows inline). */
export function TextZoomControl({ className, inlineFrom = 768 }: { className?: string; inlineFrom?: number }) {
  const t = useT()
  const inline = useMediaQuery(`(min-width: ${inlineFrom}px)`)
  const { zoom, step, setZoom } = useTextZoom()
  const pct = `${Math.round(zoom * 100)}%`
  const trio = (
    <div className={cn('flex items-center', className)} data-testid="text-zoom">
      <Tooltip content={t('files.textSmaller')}>
        <Button variant="ghost" size="icon-sm" onClick={() => step(-1)} aria-label={t('files.textSmaller')} disabled={zoom <= 0.75}>
          <Minus />
        </Button>
      </Tooltip>
      <Tooltip content={t('files.textZoomTip')}>
        <button
          type="button"
          onClick={() => setZoom(1)}
          className="h-8 min-w-12 rounded-md px-1.5 text-xs whitespace-nowrap font-medium text-muted-foreground tabular-nums outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring max-md:h-10 pointer-coarse:h-10"
          aria-label={t('files.textZoomReset')}
          data-testid="text-zoom-value"
        >
          {pct}
        </button>
      </Tooltip>
      <Tooltip content={t('files.textBigger')}>
        <Button variant="ghost" size="icon-sm" onClick={() => step(1)} aria-label={t('files.textBigger')} disabled={zoom >= 2.5}>
          <Plus />
        </Button>
      </Tooltip>
    </div>
  )
  if (inline) return trio
  return (
    <Popover>
      <Tooltip content={`${t('files.textZoom')} · ${pct}`}>
        <PopoverTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={t('files.textZoom')} data-testid="text-zoom-open" className={cn(zoom !== 1 && 'text-primary')}>
            <Type />
          </Button>
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent align="end" className="w-auto p-1" onOpenAutoFocus={(e) => e.preventDefault()}>
        {trio}
      </PopoverContent>
    </Popover>
  )
}

const HEADS = ':scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > h5, :scope > h6'

/** Rendered markdown in its own scroller, zoomed, that remembers where the reader was (key: `path`). */
export function MarkdownReader({ content, path, className, testId }: { content: string; path: string; className?: string; testId?: string }) {
  const zoom = useTextZoom((s) => s.zoom)
  const box = React.useRef<HTMLDivElement>(null)
  const inner = React.useRef<HTMLDivElement>(null)
  const restored = React.useRef(false)
  const anchor = React.useRef<ReadPos | null>(null)
  useCtrlWheelZoom(box)

  // The rendered page (not the skeleton shown while the markdown chunk loads).
  const root = () => {
    const el = inner.current?.firstElementChild as HTMLElement | null
    return el && !el.hasAttribute('aria-hidden') ? el : null
  }
  const y = (el: Element) => el.getBoundingClientRect().top - box.current!.getBoundingClientRect().top + box.current!.scrollTop
  const measure = React.useCallback((): ReadPos | null => {
    const b = box.current
    const r = root()
    if (!b || !r) return null
    const top = b.scrollTop
    const blocks = [...r.children]
    let block: ReadPos['block']
    for (let i = 0; i < blocks.length; i++) {
      const rect = blocks[i].getBoundingClientRect()
      const at = y(blocks[i])
      if (at + rect.height > top + 1) {
        block = { i, r: rect.height ? Math.max(0, (top - at) / rect.height) : 0 }
        break
      }
    }
    const hs = [...r.querySelectorAll(HEADS)].map(y)
    return { view: 'md', frac: b.scrollHeight > b.clientHeight ? top / (b.scrollHeight - b.clientHeight) : 0, block, h: headingAt(hs, top, b.scrollHeight) }
  }, [])
  const apply = React.useCallback((pos: ReadPos) => {
    const b = box.current
    const r = root()
    if (!b || !r) return
    const blocks = [...r.children]
    const el = pos.view === 'md' && pos.block ? blocks[pos.block.i] : undefined
    if (el instanceof Element) return void (b.scrollTop = y(el) + pos.block!.r * el.getBoundingClientRect().height)
    const viaHeading = pos.h ? fromHeading([...r.querySelectorAll(HEADS)].map(y), pos.h, b.scrollHeight) : null
    b.scrollTop = viaHeading ?? pos.frac * (b.scrollHeight - b.clientHeight)
  }, [])

  // The text is rendered by a lazy chunk: restore once it is in the page.
  React.useEffect(() => {
    if (restored.current) return
    let raf = 0
    let tries = 0
    const tick = () => {
      if (root()?.children.length || tries++ > 120) {
        restored.current = true
        const pos = getReadPos(path)
        if (pos) apply(pos)
        return
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [path, content, apply])

  // Remember the position while reading.
  React.useEffect(() => {
    const b = box.current
    if (!b) return
    let raf = 0
    const onScroll = () => {
      if (raf || !restored.current) return
      raf = requestAnimationFrame(() => {
        raf = 0
        const pos = measure()
        if (pos) setReadPos(path, pos)
      })
    }
    b.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      cancelAnimationFrame(raf)
      b.removeEventListener('scroll', onScroll)
    }
  }, [path, measure])

  // Zoom: measured just before the change (the store calls back before React renders), put back right after.
  React.useEffect(() => useTextZoom.subscribe((s, prev) => void (s.zoom !== prev.zoom && (anchor.current = measure()))), [measure])
  React.useLayoutEffect(() => {
    if (anchor.current) apply(anchor.current)
    anchor.current = null
  }, [zoom, apply])

  return (
    <div ref={box} className="min-h-0 flex-1 overflow-y-auto overscroll-contain" data-testid={testId}>
      <div ref={inner} style={zoom === 1 ? undefined : { zoom }}>
        <MarkdownView content={content} path={path} className={className} />
      </div>
    </div>
  )
}

/** A box around a text editor: Ctrl/⌘ + wheel over it zooms the text. */
export function ZoomBox({ className, children }: { className?: string; children: React.ReactNode }) {
  const ref = React.useRef<HTMLDivElement>(null)
  useCtrlWheelZoom(ref)
  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  )
}

/** Whether the text zoom applies to what is shown (not a table or a web page preview). */
export const zoomsText = (kind: string, preview: boolean) => kind === 'markdown' || kind === 'code' || kind === 'text' || ((kind === 'csv' || kind === 'html') && !preview)
