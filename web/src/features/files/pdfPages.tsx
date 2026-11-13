// A PDF read page by page, as pictures rendered by the server (/api/files/pdf/page): for the browsers that show
// no PDF inside a page - most phones, where the frame stays empty or stops at the first page. Pages load as they
// come near, two fingers (or − / +, a double tap, Ctrl + wheel) zoom, one finger scrolls.
import * as React from 'react'
import { Minus, Plus } from 'lucide-react'
import { Button, Tooltip } from '@/components/ui'
import { PDF_PAGE_WIDTHS, pdfPageUrl } from '@/lib/queries/files'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { useTouchZoom, type Pt } from '@/lib/touch-zoom'

const ZOOMS = [1, 1.5, 2, 3, 4]
const MAX_ZOOM = 4
/** Widest a page is at 100 % (px): the width of a sheet of paper on a desk screen, the screen on a phone. */
const PAGE_MAX = 896
const clamp = (z: number) => Math.min(MAX_ZOOM, Math.max(1, z))
/** The step above or below `z` (− / +, the wheel). */
const stepFrom = (z: number, dir: 1 | -1) => (dir > 0 ? (ZOOMS.find((s) => s > z + 0.01) ?? MAX_ZOOM) : ([...ZOOMS].reverse().find((s) => s < z - 0.01) ?? 1))

const Page = React.memo(function Page({
  path,
  n,
  w,
  version,
  ratio,
  root,
}: {
  path: string
  n: number
  w: number
  version: number
  ratio: number
  root: React.RefObject<HTMLElement | null>
}) {
  const t = useT()
  const ref = React.useRef<HTMLDivElement>(null)
  const [near, setNear] = React.useState(n <= 2)
  /** This page's own height / width, known once its picture is there (the first page gives the others' until then). */
  const [shape, setShape] = React.useState<number | null>(null)
  const [src, setSrc] = React.useState<string | null>(null)
  const [failed, setFailed] = React.useState(false)
  const want = pdfPageUrl(path, n, w, version)

  React.useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(([e]) => setNear(e.isIntersecting), { root: root.current, rootMargin: '150% 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [root])

  React.useEffect(() => {
    if (!near || src === want) return
    if (!src) return setSrc(want)
    // A sharper picture (after a zoom) takes the place of the one shown once it is loaded: never a blank page.
    let live = true
    const img = new Image()
    img.onload = () => live && setSrc(want)
    img.src = want
    return () => {
      live = false
    }
  }, [near, want, src])

  return (
    <div
      ref={ref}
      className="relative w-full overflow-hidden rounded-[2px] bg-white shadow-sm ring-1 ring-black/10"
      style={{ aspectRatio: `1 / ${shape ?? ratio}` }}
      data-page={n}
    >
      {failed ? (
        <p className="absolute inset-0 flex items-center justify-center p-4 text-center text-xs text-neutral-500">{t('doc.pdfPageError', { n })}</p>
      ) : (
        // far pages keep their place, not their picture (a 300-page file is not 300 decoded pictures on a phone)
        near &&
        src && (
          <img
            src={src}
            alt={t('doc.pdfPage', { n })}
            className="absolute inset-0 size-full select-none"
            draggable={false}
            decoding="async"
            onLoad={(e) => {
              const i = e.currentTarget
              if (i.naturalWidth) setShape(i.naturalHeight / i.naturalWidth)
            }}
            onError={() => setFailed(true)}
          />
        )
      )}
    </div>
  )
})

export function PdfPages({
  path,
  pages,
  ratio,
  version,
  className,
  children,
}: {
  path: string
  pages: number
  /** Height / width of the first page. */
  ratio: number
  version: number
  className?: string
  /** Buttons at the end of the bar (open, download). */
  children?: React.ReactNode
}) {
  const t = useT()
  const box = React.useRef<HTMLDivElement>(null)
  const [zoom, setZoom] = React.useState(1)
  /** The zoom the pictures are asked for: follows `zoom` once the fingers are up (no reload at every frame of a pinch). */
  const [sharp, setSharp] = React.useState(1)
  const [page, setPage] = React.useState(1)
  const [width, setWidth] = React.useState(PDF_PAGE_WIDTHS[1])
  const anchor = React.useRef<{ px: number; py: number; fx: number; fy: number } | null>(null)
  const from = React.useRef(1)

  /** Called before any zoom change: the point under the fingers (default: the centre) stays where it is. */
  const capture = React.useCallback((p?: Pt) => {
    const b = box.current
    if (!b) return
    const r = b.getBoundingClientRect()
    const px = p ? p.x - r.left : b.clientWidth / 2
    const py = p ? p.y - r.top : b.clientHeight / 2
    anchor.current = { px, py, fx: (b.scrollLeft + px) / b.scrollWidth, fy: (b.scrollTop + py) / b.scrollHeight }
  }, [])
  React.useLayoutEffect(() => {
    const a = anchor.current
    const b = box.current
    anchor.current = null
    if (!a || !b) return
    b.scrollLeft = a.fx * b.scrollWidth - a.px
    b.scrollTop = a.fy * b.scrollHeight - a.py
  }, [zoom])

  const set = React.useCallback(
    (z: number, p?: Pt) => {
      capture(p)
      setZoom(clamp(z))
      setSharp(clamp(z))
    },
    [capture],
  )
  const now = React.useRef(zoom)
  now.current = zoom

  useTouchZoom(box, {
    pinchStart: () => void (from.current = zoom),
    pinch: (scale, mid) => {
      capture(mid)
      setZoom(clamp(from.current * scale))
    },
    // back to the full page when at or just above it, else the nearest step when close (98 % -> 100 %)
    pinchEnd: (mid) => set(zoom < 1.05 ? 1 : (ZOOMS.find((s) => Math.abs(s - zoom) / s < 0.04) ?? Math.round(zoom * 100) / 100), mid),
    doubleTap: (p) => set(zoom > 1.01 ? 1 : 2, p),
  })

  React.useEffect(() => {
    const b = box.current
    if (!b) return
    let raf = 0
    const onScroll = () => {
      if (raf) return
      raf = requestAnimationFrame(() => {
        raf = 0
        setPage(Math.min(pages, Math.max(1, Math.floor(((b.scrollTop + b.clientHeight / 2) / b.scrollHeight) * pages) + 1)))
      })
    }
    // Ctrl / ⌘ + wheel (a trackpad pinch sends the same) zooms the pages, not the whole interface.
    let acc = 0
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      acc += e.deltaY
      if (Math.abs(acc) < 30) return
      set(stepFrom(now.current, acc < 0 ? 1 : -1), { x: e.clientX, y: e.clientY })
      acc = 0
    }
    // The pictures are asked at the size they are shown (screen pixels), in three widths the server keeps.
    const measure = () => setWidth(Math.min(b.clientWidth, PAGE_MAX))
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(b)
    b.addEventListener('scroll', onScroll, { passive: true })
    b.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      b.removeEventListener('scroll', onScroll)
      b.removeEventListener('wheel', onWheel)
    }
  }, [pages, set])

  const need = width * sharp * Math.min(window.devicePixelRatio || 1, 3)
  const w = PDF_PAGE_WIDTHS.find((x) => x >= need * 0.9) ?? PDF_PAGE_WIDTHS[PDF_PAGE_WIDTHS.length - 1]
  const list = React.useMemo(() => Array.from({ length: pages }, (_, i) => i + 1), [pages])

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', className)} data-testid="pdf-pages">
      <div ref={box} className="min-h-0 flex-1 overflow-auto overscroll-contain bg-muted/40" data-zoomed={zoom > 1.01 ? '' : undefined} data-testid="pdf-scroll">
        <div className="mx-auto grid gap-2 p-2 md:gap-3 md:p-4" style={{ width: `${zoom * 100}%`, maxWidth: PAGE_MAX * zoom }}>
          {list.map((n) => (
            <Page key={n} path={path} n={n} w={w} version={version} ratio={ratio} root={box} />
          ))}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1 border-t px-2 py-1 md:px-3">
        <Tooltip content={t('files.zoomOut')}>
          <Button variant="ghost" size="icon-sm" onClick={() => set(stepFrom(zoom, -1))} disabled={zoom <= 1.01} aria-label={t('files.zoomOut')}>
            <Minus />
          </Button>
        </Tooltip>
        <button
          type="button"
          onClick={() => set(1)}
          className="h-8 min-w-12 rounded-md px-1.5 text-xs font-medium whitespace-nowrap text-muted-foreground tabular-nums outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:h-10"
          aria-label={t('files.fit')}
          data-testid="pdf-zoom"
        >
          {Math.round(zoom * 100)}%
        </button>
        <Tooltip content={t('files.zoomIn')}>
          <Button variant="ghost" size="icon-sm" onClick={() => set(stepFrom(zoom, 1))} disabled={zoom >= MAX_ZOOM - 0.01} aria-label={t('files.zoomIn')}>
            <Plus />
          </Button>
        </Tooltip>
        <span className="mx-2 text-xs whitespace-nowrap text-muted-foreground tabular-nums" aria-label={t('doc.pdfPageOf', { n: page, count: pages })} data-testid="pdf-page">
          {page} / {pages}
        </span>
        <div className="ml-auto flex items-center gap-1">{children}</div>
      </div>
    </div>
  )
}
