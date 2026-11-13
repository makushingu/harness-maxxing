// Building blocks of the file viewer: lazy editor, markdown, image (zoom/fit), media, pdf, info card.
// Used by FilePreview (read-only, reusable anywhere) and by the Files page (viewer + editor).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { ChevronLeft, ChevronRight, Download, ExternalLink, FileWarning, Maximize, Minus, Plus, type LucideIcon } from 'lucide-react'
import type { Components } from 'react-markdown'
import { Button, Sensitive, Spinner, Tooltip } from '@/components/ui'
import { fileRawUrl, filePreviewUrl, fileThumbUrl, PREVIEW_W, usePdfInfo } from '@/lib/queries/files'
import { fmtBytes } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { useMediaQuery } from '@/stores/media'
import { useHotkey } from '@/commands/shortcuts'
import { useTouchZoom, type Pt } from '@/lib/touch-zoom'
import { useDiagramSvg } from '@/components/ui/diagram'
import { basename, CONVERTED_IMAGE, dirname, extOf, resolvePath } from './kinds'
import type { CodeEditorProps } from './CodeEditor'
import { MediaPlayer } from './MediaPlayer'
import { downloadProps, inIosApp, openRawProps } from './download'
import { CodeSkeleton, PageSkeleton, ProseSkeleton } from './skeletons'
import { PdfPages } from './pdfPages'

const CodeEditorChunk = React.lazy(() => import('./CodeEditor'))
const MarkdownChunk = React.lazy(() => import('@/components/ui/markdown').then((m) => ({ default: m.Markdown })))

/** CodeMirror, loaded on demand. Fills its parent (give the parent a height). */
export function LazyCodeEditor(props: CodeEditorProps) {
  return (
    <React.Suspense fallback={<CodeSkeleton className="h-full" />}>
      <CodeEditorChunk {...props} />
    </React.Suspense>
  )
}

/* ------------------------------------------------------------------ markdown */
const APP_ROUTES = /^\/(sessions|files|tasks|crons|settings|docs|x|api|login|setup|welcome)(\/|\?|$)/

/** True when an URL in a markdown file should be read as a path on the server (not a web URL). */
function isFileRef(href: string) {
  if (!href || href.startsWith('#') || /^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith('//')) return false
  if (href.startsWith('/')) return !APP_ROUTES.test(href)
  return true
}

// A literal '%' is legal in a file name; malformed escapes must not crash its preview.
function decodeFileRef(ref: string) {
  try {
    return decodeURIComponent(ref)
  } catch {
    return ref
  }
}

/**
 * Rendered markdown of a file: relative images are served from the file's folder, relative links open
 * in the Files page. The raw text is never modified. `image`: where the pictures of this text are instead (a
 * document's own pictures); null = not shown.
 */
export function MarkdownView({ content, path, className, image }: { content: string; path: string; className?: string; image?: (ref: string) => string | null }) {
  const navigate = useNavigate()
  const dir = dirname(path)
  const onLink = React.useCallback(
    (href: string) => {
      if (!isFileRef(href)) return null
      const target = resolvePath(dir, decodeFileRef(href.replace(/[?#].*$/, '')))
      return () => navigate(`/files?path=${encodeURIComponent(target)}`)
    },
    [dir, navigate],
  )
  const components = React.useMemo<Components>(
    () => ({
      img({ src, alt }) {
        const s = typeof src === 'string' ? src : ''
        if (!s) return null
        if (image) {
          const url = isFileRef(s) ? image(decodeFileRef(s)) : null
          return url ? <img src={url} alt={alt || ''} loading="lazy" /> : null
        }
        if (isFileRef(s)) return <img src={fileRawUrl(resolvePath(dir, decodeFileRef(s.replace(/[?#].*$/, ''))))} alt={alt || ''} loading="lazy" />
        return /^https?:/i.test(s) ? <img src={s} alt={alt || ''} loading="lazy" referrerPolicy="no-referrer" /> : null
      },
    }),
    [dir, image],
  )
  return (
    <React.Suspense fallback={<ProseSkeleton />}>
      <MarkdownChunk className={className} onLink={onLink} components={components}>
        {content}
      </MarkdownChunk>
    </React.Suspense>
  )
}

/* ------------------------------------------------------------------ image */
const ZOOMS = [0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8]
const MIN_ZOOM = 0.05
const MAX_ZOOM = 8
/** One wheel notch: the next multiple of 5 % up or down (from a fitted 63 %: 65 %, then 70 %...). */
const wheelZoom = (from: number, dir: 1 | -1) =>
  Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, dir > 0 ? Math.floor(from * 20 + 1e-6) / 20 + 0.05 : Math.ceil(from * 20 - 1e-6) / 20 - 0.05))

/** What the fingers need: the zoom shown now (a number, also when fitted), the fitted zoom, how to set it, what a
 *  double tap does (same as a double-click) and whether a pinch may start now (`ready`). */
type TouchZoom = { current: number; fit: number; set: (z: 'fit' | number) => void; toggle: (p: Pt) => void; ready?: () => boolean }
type Anchor = { px: number; py: number; fx: number; fy: number }

/** End of a pinch: back to fitted when at or below it, else the nearest step when close (98 % -> 100 %), else a
 *  whole percent. */
const pinchSettle = (z: number, fit: number): 'fit' | number => {
  if (z <= fit * 1.03) return 'fit'
  return ZOOMS.find((s) => Math.abs(s - z) / s < 0.04) ?? Math.round(z * 100) / 100
}

/**
 * Zoom and pan shared by images and diagrams. The wheel zooms around the pointer (`onWheel(dir)` sets the zoom;
 * Shift + wheel still scrolls), a mouse drag moves a zoomed view (the hand), and `capture(point?)` - called before
 * any zoom change - keeps that point (default: the centre) under the same spot. The zoomed element is the one
 * marked `data-zoomable` inside `box`.
 * Touch (`touch`): two fingers zoom continuously around their midpoint and move the view while pinching, one finger
 * moves a zoomed view (with a glide), a double tap toggles. A fitted view leaves one finger alone (swipe to the next
 * file, scrolling around).
 */
function usePanZoom(
  box: React.RefObject<HTMLDivElement | null>,
  zoom: 'fit' | number,
  onWheel: (dir: 1 | -1) => void,
  mountKey: unknown = null,
  touch?: TouchZoom,
) {
  const anchor = React.useRef<Anchor | null>(null)
  const capture = React.useCallback(
    (point?: { x: number; y: number }) => {
      const b = box.current
      const el = b?.querySelector<HTMLElement>('[data-zoomable]')
      if (!b || !el) return
      const br = b.getBoundingClientRect()
      const r = el.getBoundingClientRect()
      const x = point?.x ?? br.left + b.clientWidth / 2
      const y = point?.y ?? br.top + b.clientHeight / 2
      anchor.current = { px: x - br.left, py: y - br.top, fx: (x - r.left) / (r.width || 1), fy: (y - r.top) / (r.height || 1) }
    },
    [box],
  )
  /** Scroll so that the point `fx, fy` of the zoomed element sits at `px, py` of the box. */
  const place = React.useCallback(
    (a: Anchor) => {
      const b = box.current
      const el = b?.querySelector<HTMLElement>('[data-zoomable]')
      if (!b || !el) return
      const br = b.getBoundingClientRect()
      const r = el.getBoundingClientRect()
      b.scrollLeft += r.left - br.left + a.fx * r.width - a.px
      b.scrollTop += r.top - br.top + a.fy * r.height - a.py
    },
    [box],
  )
  React.useLayoutEffect(() => {
    const a = anchor.current
    anchor.current = null
    if (a && zoom !== 'fit') place(a)
  }, [zoom, place])

  // Fingers. The handlers read the latest values through refs: the listeners stay bound for the whole gesture.
  const zoomNow = React.useRef(zoom)
  zoomNow.current = zoom
  const tz = React.useRef(touch)
  tz.current = touch
  const pinching = React.useRef<{ z0: number; fx: number; fy: number; last: number } | null>(null)
  const glide = React.useRef(0)
  const stopGlide = () => {
    cancelAnimationFrame(glide.current)
    glide.current = 0
  }
  React.useEffect(() => () => cancelAnimationFrame(glide.current), [])
  useTouchZoom(
    box,
    {
      pinchStart: (mid) => {
        const o = tz.current
        const el = box.current?.querySelector<HTMLElement>('[data-zoomable]')
        if (!o || !el || (o.ready && !o.ready())) return false
        stopGlide()
        const r = el.getBoundingClientRect()
        pinching.current = { z0: o.current, fx: (mid.x - r.left) / (r.width || 1), fy: (mid.y - r.top) / (r.height || 1), last: o.current }
      },
      pinch: (scale, mid) => {
        const p = pinching.current
        const o = tz.current
        const b = box.current
        if (!p || !o || !b) return
        const z = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, p.z0 * scale))
        const br = b.getBoundingClientRect()
        const a = { px: mid.x - br.left, py: mid.y - br.top, fx: p.fx, fy: p.fy }
        p.last = z
        // Same zoom (at a limit): the fingers only move the view.
        if (zoomNow.current !== 'fit' && Math.abs(zoomNow.current - z) < 1e-4) return place(a)
        anchor.current = a
        o.set(z)
      },
      pinchEnd: (mid) => {
        const p = pinching.current
        pinching.current = null
        const o = tz.current
        if (!p || !o) return
        const to = pinchSettle(p.last, o.fit)
        if (to === 'fit') {
          anchor.current = null
          return o.set('fit')
        }
        if (Math.abs(to - p.last) < 1e-4) return
        capture(mid)
        o.set(to)
      },
      pan: (dx, dy) => {
        const b = box.current
        if (zoomNow.current === 'fit' || !b || !tz.current) return false
        stopGlide()
        b.scrollLeft -= dx
        b.scrollTop -= dy
        return true
      },
      panEnd: (vx, vy) => {
        const b = box.current
        if (zoomNow.current === 'fit' || !b || Math.hypot(vx, vy) < 0.1) return
        let last = performance.now()
        const run = (now: number) => {
          const dt = Math.min(48, now - last)
          last = now
          b.scrollLeft -= vx * dt
          b.scrollTop -= vy * dt
          const k = Math.pow(0.95, dt / 16)
          vx *= k
          vy *= k
          glide.current = Math.hypot(vx, vy) < 0.02 ? 0 : requestAnimationFrame(run)
        }
        stopGlide()
        glide.current = requestAnimationFrame(run)
      },
      doubleTap: (pt) => {
        stopGlide()
        tz.current?.toggle(pt)
      },
    },
    mountKey,
  )

  // Native listener: React's wheel listeners are passive, they cannot stop the page from scrolling.
  const wheel = React.useRef(onWheel)
  wheel.current = onWheel
  React.useEffect(() => {
    const b = box.current
    if (!b) return
    let acc = 0
    const on = (e: WheelEvent) => {
      // Shift + wheel and sideways trackpad swipes scroll (a zoomed view pans); the vertical wheel zooms.
      if (e.shiftKey || (!e.ctrlKey && Math.abs(e.deltaX) > Math.abs(e.deltaY))) return
      e.preventDefault()
      // A mouse notch is ~100 px; a trackpad sends small deltas: one step per ~50 px.
      acc += e.deltaY * (e.deltaMode === 1 ? 40 : 1)
      if (Math.abs(acc) < 50 && e.deltaMode === 0 && Math.abs(e.deltaY) < 50) return
      const dir = acc < 0 ? 1 : -1
      acc = 0
      capture({ x: e.clientX, y: e.clientY })
      wheel.current(dir)
    }
    b.addEventListener('wheel', on, { passive: false })
    return () => b.removeEventListener('wheel', on)
    // mountKey: the box element is re-created (an image that failed, then another path in the same viewer)
  }, [box, capture, mountKey])

  // The hand: drag with the mouse to move a zoomed view (fingers scroll natively).
  const drag = React.useRef<{ x: number; y: number; l: number; t: number } | null>(null)
  const [dragging, setDragging] = React.useState(false)
  const pan = {
    onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => {
      if (zoom === 'fit' || e.pointerType !== 'mouse' || e.button !== 0) return
      drag.current = { x: e.clientX, y: e.clientY, l: e.currentTarget.scrollLeft, t: e.currentTarget.scrollTop }
      e.currentTarget.setPointerCapture(e.pointerId)
      setDragging(true)
    },
    onPointerMove: (e: React.PointerEvent<HTMLDivElement>) => {
      const d = drag.current
      if (!d) return
      e.currentTarget.scrollLeft = d.l - (e.clientX - d.x)
      e.currentTarget.scrollTop = d.t - (e.clientY - d.y)
    },
    onPointerUp: () => {
      drag.current = null
      setDragging(false)
    },
  }
  // A zoomed view takes every finger (it pans itself); a fitted one leaves one-finger swipes to the browser.
  const cursor = zoom === 'fit' ? undefined : cn('touch-none', dragging ? 'cursor-grabbing' : 'cursor-grab')
  return { capture, pan, cursor }
}

/**
 * Image viewer. Loads progressively: the small thumbnail (usually already in the browser cache, the one
 * shown in the chat or the grid) appears at once, blurred; the light preview (WebP <= 2048 px for heavy
 * images, else the original) fades in over it; the ORIGINAL is only fetched when zooming in.
 */
export function ImageView({ path, version, onPrev, onNext, position, className }: { path: string; version?: number | null; onPrev?: () => void; onNext?: () => void; position?: string; className?: string }) {
  const t = useT()
  const [zoom, setZoom] = React.useState<'fit' | number>('fit')
  /** Real pixel size of the image used for zooming (the original, or the preview when it is the original). */
  const [natural, setNatural] = React.useState<{ w: number; h: number } | null>(null)
  const [failed, setFailed] = React.useState(false)
  const [loaded, setLoaded] = React.useState(false)
  /** The preview is already full resolution (small image): zooming never needs the original. */
  const [previewFull, setPreviewFull] = React.useState(false)
  /** Zoom asked on a downscaled preview: the original is loading / loaded. */
  const [full, setFull] = React.useState(false)
  const [fullLoaded, setFullLoaded] = React.useState(false)
  type Pending = { dir: 1 | -1 } | { to: 'toggle'; anchor: Centre }
  type Centre = { fx: number; fy: number; cx: number; cy: number }
  const pending = React.useRef<Pending | null>(null)
  /** A zoom is waiting for the original: show the loading pill. */
  const [pendingShown, setPendingShown] = React.useState(false)
  const anchor = React.useRef<Centre | null>(null)
  const box = React.useRef<HTMLDivElement>(null)
  const ready = fullLoaded || previewFull

  React.useEffect(() => {
    setZoom('fit')
    setNatural(null)
    setFailed(false)
    setLoaded(false)
    setPreviewFull(false)
    setFull(false)
    setFullLoaded(false)
    setPendingShown(false)
    pending.current = null
  }, [path])

  const fitOf = (n: { w: number; h: number } | null) => {
    const b = box.current
    if (!b || !n) return 1
    return Math.min(1, (b.clientWidth - 32) / n.w, (b.clientHeight - 32) / n.h)
  }
  const current = zoom === 'fit' ? fitOf(natural) : zoom
  const nextStep = (from: number, dir: 1 | -1) => (dir > 0 ? ZOOMS.find((x) => x > from + 0.001) : [...ZOOMS].reverse().find((x) => x < from - 0.001))
  const toggleTarget = (_n: { w: number; h: number } | null) => 1

  const step = (dir: 1 | -1) => {
    if (!ready) {
      pending.current = { dir }
      setPendingShown(true)
      setFull(true)
      return
    }
    pz.capture()
    const next = nextStep(current, dir)
    if (next) setZoom(next)
  }
  const toggle = (a: Centre | null) => {
    if (zoom !== 'fit') {
      anchor.current = null
      return setZoom('fit')
    }
    const centre = a ?? { fx: 0.5, fy: 0.5, cx: (box.current?.clientWidth ?? 0) / 2, cy: (box.current?.clientHeight ?? 0) / 2 }
    if (!ready) {
      pending.current = { to: 'toggle', anchor: centre }
      setPendingShown(true)
      setFull(true)
      return
    }
    setZoom(toggleTarget(natural))
  }
  // The original is fetched quietly once the preview is on screen, so zooming is instant (as before) while
  // opening stays fast. It replaces the preview without any visible change.
  React.useEffect(() => {
    if (!loaded || previewFull || full) return
    const id = setTimeout(() => setFull(true), 150)
    return () => clearTimeout(id)
  }, [loaded, previewFull, full])

  const pz = usePanZoom(
    box,
    zoom,
    (dir) => {
      if (!ready) return step(dir)
      setZoom(wheelZoom(current, dir))
    },
    `${path}:${failed}`,
    {
      current,
      fit: fitOf(natural),
      set: setZoom,
      toggle: (p) => {
        pz.capture(p)
        toggle(null)
      },
      // Pinching a downscaled preview: fetch the original first (it usually is already there).
      ready: () => {
        if (!ready) {
          setPendingShown(true)
          setFull(true)
        }
        return ready
      },
    },
  )

  useHotkey('arrowleft', () => onPrev?.(), { enabled: !!onPrev })
  useHotkey('arrowright', () => onNext?.(), { enabled: !!onNext })
  useHotkey('+', () => step(1))
  useHotkey('=', () => step(1))
  useHotkey('-', () => step(-1))
  useHotkey('0', () => {
    pz.capture()
    toggle(null)
  })

  const applyPending = (n: { w: number; h: number }) => {
    const act = pending.current
    pending.current = null
    setPendingShown(false)
    if (!act) return
    if ('dir' in act) {
      const next = nextStep(fitOf(n), act.dir)
      setZoom(next ?? fitOf(n))
    } else {
      anchor.current = act.anchor
      setZoom(toggleTarget(n))
    }
  }

  if (failed) return <FileInfoCard path={path} reason={t('files.imageError')} className={className} />
  const thumb = fileThumbUrl(path, 320, version)
  const zoomStyle = zoom !== 'fit' && natural ? { width: natural.w * zoom, height: natural.h * zoom } : undefined
  // Zoomed: centred while smaller than the view (auto margins never push it out of reach when bigger).
  const zoomCls = zoom === 'fit' ? 'max-h-full max-w-full object-contain' : 'm-auto max-w-none shrink-0'
  return (
    <div className={cn('relative flex min-h-0 flex-1 flex-col', className)}>
      <div
        ref={box}
        className={cn(
          'relative min-h-0 flex-1 [background:repeating-conic-gradient(var(--muted)_0%_25%,transparent_0%_50%)_50%/20px_20px]',
          zoom === 'fit' ? 'flex items-center justify-center overflow-hidden p-4' : 'flex overflow-auto p-4',
          pz.cursor,
        )}
        data-zoomed={zoom !== 'fit' || undefined}
        onDoubleClick={(e) => {
          pz.capture({ x: e.clientX, y: e.clientY })
          toggle(null)
        }}
        {...pz.pan}
      >
        <Sensitive placeholder={<div className="size-full rounded-lg bg-muted/60" aria-label={t('presentation.hidden')} />}>
          {!loaded && (
            // Instant placeholder: the cached thumbnail, blurred, at the size the image will have.
            <img src={thumb} alt="" aria-hidden draggable={false} className="pointer-events-none absolute inset-4 m-auto max-h-[calc(100%-2rem)] max-w-[calc(100%-2rem)] object-contain blur-md select-none" />
          )}
          {/* The light preview stays on screen until the original (zoom) has loaded: no blank frame. */}
          {!fullLoaded && (
            <img
              key="preview"
              data-zoomable={!fullLoaded || undefined}
              src={filePreviewUrl(path, PREVIEW_W, version)}
              alt={basename(path)}
              draggable={false}
              decoding="async"
              onLoad={(e) => {
                setLoaded(true)
                const n = { w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight }
                // Narrower than the preview width = not downscaled: this IS the full resolution. TIFF / HEIC:
                // the browser cannot show the original, the converted preview is all there is.
                if ((n.w < PREVIEW_W && n.h < PREVIEW_W * 4) || CONVERTED_IMAGE.has(extOf(path))) {
                  setNatural(n)
                  setPreviewFull(true)
                  setFull(false)
                  applyPending(n)
                }
              }}
              onError={() => setFailed(true)}
              className={cn('relative transition-opacity duration-300 select-none', previewFull ? zoomCls : 'max-h-full max-w-full object-contain', !loaded && 'opacity-0')}
              style={previewFull ? zoomStyle : undefined}
            />
          )}
          {full && !previewFull && (
            <img
              key="full"
              data-zoomable={fullLoaded || undefined}
              src={fileRawUrl(path, false, version)}
              alt={fullLoaded ? basename(path) : ''}
              draggable={false}
              decoding="async"
              onLoad={(e) => {
                const n = { w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight }
                setNatural(n)
                setFullLoaded(true)
                applyPending(n)
              }}
              onError={() => setFull(false)}
              className={cn('select-none', !fullLoaded ? 'pointer-events-none absolute size-px opacity-0' : zoomCls)}
              style={fullLoaded ? zoomStyle : undefined}
            />
          )}
        </Sensitive>
      </div>
      {full && !fullLoaded && !previewFull && pendingShown && (
        <div className="pointer-events-none absolute inset-x-0 top-3 flex justify-center">
          <span className="inline-flex items-center gap-2 rounded-full border bg-popover px-3 py-1 text-xs text-muted-foreground shadow-pop">
            <Spinner className="size-3.5 text-primary" /> {t('files.loadingOriginal')}
          </span>
        </div>
      )}
      <div className="pointer-events-none absolute inset-x-0 bottom-3 flex justify-center px-3">
        <div className="pointer-events-auto flex items-center gap-0.5 rounded-lg border bg-popover p-1 shadow-pop">
          {onPrev && (
            <Tooltip content={`${t('files.prev')} (←)`}>
              <Button variant="ghost" size="icon-sm" onClick={onPrev} aria-label={t('files.prev')}>
                <ChevronLeft />
              </Button>
            </Tooltip>
          )}
          {position && <span className="px-1 text-xs text-muted-foreground tabular-nums">{position}</span>}
          {onNext && (
            <Tooltip content={`${t('files.next')} (→)`}>
              <Button variant="ghost" size="icon-sm" onClick={onNext} aria-label={t('files.next')}>
                <ChevronRight />
              </Button>
            </Tooltip>
          )}
          {(onPrev || onNext) && <span className="mx-1 h-5 w-px bg-border" aria-hidden />}
          <Button variant="ghost" size="icon-sm" onClick={() => step(-1)} aria-label={t('files.zoomOut')}>
            <Minus />
          </Button>
          <button
            type="button"
            onClick={() => {
              pz.capture()
              toggle(null)
            }}
            className="h-8 min-w-14 rounded-md px-2 text-xs font-medium text-muted-foreground tabular-nums outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring max-md:h-10"
            aria-label={zoom === 'fit' ? t('files.actualSize') : t('files.fit')}
          >
            {zoom === 'fit' ? t('files.fit') : `${Math.round(current * 100)}%`}
          </button>
          <Button variant="ghost" size="icon-sm" onClick={() => step(1)} aria-label={t('files.zoomIn')}>
            <Plus />
          </Button>
          <Tooltip content={t('files.fit')}>
            <Button variant="ghost" size="icon-sm" onClick={() => setZoom('fit')} aria-label={t('files.fit')} disabled={zoom === 'fit'}>
              <Maximize />
            </Button>
          </Tooltip>
          {natural && ready && <span className="px-1.5 text-xs text-muted-foreground tabular-nums max-sm:hidden">{natural.w}×{natural.h}</span>}
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ diagram */
/** A ```mermaid diagram of a conversation, opened like an image: fitted (up to 2x), zoom, drag to pan. */
export function DiagramView({ code, className }: { code: string; className?: string }) {
  const t = useT()
  const { svg, failed } = useDiagramSvg(code, 0)
  const [zoom, setZoom] = React.useState<'fit' | number>('fit')
  const box = React.useRef<HTMLDivElement>(null)
  const [boxSize, setBoxSize] = React.useState<{ w: number; h: number } | null>(null)
  React.useLayoutEffect(() => {
    const b = box.current
    if (!b) return
    const ro = new ResizeObserver(() => setBoxSize({ w: b.clientWidth, h: b.clientHeight }))
    ro.observe(b)
    return () => ro.disconnect()
  }, [])
  // Mermaid gives the drawing its size in the viewBox and caps it with an inline max-width: the viewer sizes it.
  const natural = React.useMemo(() => {
    const m = svg && /viewBox="[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)"/.exec(svg)
    return m ? { w: +m[1], h: +m[2] } : null
  }, [svg])
  const html = React.useMemo(() => svg?.replace(/max-width:\s*[\d.]+px;?/, ''), [svg])
  const fit = natural && boxSize ? Math.min(2, (boxSize.w - 32) / natural.w, (boxSize.h - 32) / natural.h) : 1
  const current = zoom === 'fit' ? fit : zoom
  const pz = usePanZoom(box, zoom, (dir) => setZoom(wheelZoom(current, dir)), null, {
    current,
    fit,
    set: setZoom,
    toggle: (p) => toggle(p),
    ready: () => !!natural,
  })
  const step = (dir: 1 | -1) => {
    pz.capture()
    const next = dir > 0 ? ZOOMS.find((x) => x > current + 0.001) : [...ZOOMS].reverse().find((x) => x < current - 0.001)
    if (next) setZoom(next)
  }
  const toggle = (point?: { x: number; y: number }) => {
    if (zoom === 'fit') pz.capture(point)
    setZoom(zoom === 'fit' ? Math.min(8, Math.max(1, fit * 2)) : 'fit')
  }
  useHotkey('+', () => step(1))
  useHotkey('=', () => step(1))
  useHotkey('-', () => step(-1))
  useHotkey('0', () => toggle())

  const size = natural ? { width: natural.w * current, height: natural.h * current } : undefined
  return (
    <div className={cn('relative flex min-h-0 flex-1 flex-col', className)} data-testid="diagram-view">
      <div
        ref={box}
        className={cn(
          'relative min-h-0 flex-1 bg-card',
          zoom === 'fit' ? 'flex items-center justify-center overflow-hidden p-4' : 'flex overflow-auto p-4',
          pz.cursor,
        )}
        data-zoomed={zoom !== 'fit' || undefined}
        onDoubleClick={(e) => toggle({ x: e.clientX, y: e.clientY })}
        {...pz.pan}
      >
        <Sensitive placeholder={<div className="size-full rounded-lg bg-muted/60" aria-label={t('presentation.hidden')} />}>
          {html ? (
            <div
              data-zoomable
              className={cn('shrink-0 select-none animate-in [&_svg]:size-full', zoom !== 'fit' && 'm-auto', failed && 'opacity-70')}
              style={size}
              dangerouslySetInnerHTML={{ __html: html }}
            />
          ) : failed ? (
            <span className="text-sm text-muted-foreground">{t('diagram.error')}</span>
          ) : (
            <Spinner className="size-5 text-primary" />
          )}
        </Sensitive>
      </div>
      <div className="pointer-events-none absolute inset-x-0 bottom-3 flex justify-center px-3">
        <div className="pointer-events-auto flex items-center gap-0.5 rounded-lg border bg-popover p-1 shadow-pop">
          <Button variant="ghost" size="icon-sm" onClick={() => step(-1)} aria-label={t('files.zoomOut')}>
            <Minus />
          </Button>
          <button
            type="button"
            onClick={() => toggle()}
            className="h-8 min-w-14 rounded-md px-2 text-xs font-medium text-muted-foreground tabular-nums outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring max-md:h-10"
            aria-label={zoom === 'fit' ? t('files.zoomIn') : t('files.fit')}
          >
            {zoom === 'fit' ? t('files.fit') : `${Math.round(current * 100)}%`}
          </button>
          <Button variant="ghost" size="icon-sm" onClick={() => step(1)} aria-label={t('files.zoomIn')}>
            <Plus />
          </Button>
          <Tooltip content={t('files.fit')}>
            <Button variant="ghost" size="icon-sm" onClick={() => setZoom('fit')} aria-label={t('files.fit')} disabled={zoom === 'fit'}>
              <Maximize />
            </Button>
          </Tooltip>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ video / audio / pdf */
/** The player in the space it is given. A size container (`cqw` / `cqh`): the video box fits it with the video's shape
 *  before anything loads. Only a file this browser cannot play at all (no copy possible) ends in the info card - a
 *  lost connection keeps the player (it resumes by itself). */
export function MediaView({ path, kind, version, className }: { path: string; kind: 'video' | 'audio'; version?: number | null; className?: string }) {
  const t = useT()
  const [failed, setFailed] = React.useState(false)
  const fail = React.useCallback(() => setFailed(true), [])
  React.useEffect(() => setFailed(false), [path])
  if (failed) return <FileInfoCard path={path} reason={t('files.mediaError')} className={className} />
  return (
    <div className={cn('flex min-h-40 flex-1 items-center justify-center p-4 [container-type:size] md:p-6', className)}>
      <Sensitive placeholder={<div className="aspect-video w-full max-w-3xl rounded-lg bg-muted/60" aria-label={t('presentation.hidden')} />}>
        <MediaPlayer key={path} path={path} kind={kind} version={version} onError={fail} />
      </Sensitive>
    </div>
  )
}


/** The browser's own PDF viewer in a frame where it has one. Where it has none (most phones: an empty frame, or
 *  the first page only), the pages come as pictures from the server (PdfPages); without the server's PDF tools, or
 *  for a file it cannot read, the frame and its "open in a new tab" stay. */
export function PdfView({ path, className }: { path: string; className?: string }) {
  const t = useT()
  const touch = useMediaQuery('(pointer: coarse)')
  const paged = touch || !navigator.pdfViewerEnabled
  const info = usePdfInfo(path, paged)
  const actions = (short: boolean) => (
    <>
      <Button asChild variant="ghost" size="sm" className="h-7 pointer-coarse:h-9">
        <a {...openRawProps(path)} aria-label={t(inIosApp() ? 'files.openRawInApp' : 'files.openRaw')}>
          <ExternalLink />
          <span className={cn(short && 'max-sm:sr-only')}>{t(inIosApp() ? 'files.openRawInApp' : 'files.openRaw')}</span>
        </a>
      </Button>
      <Button asChild variant="ghost" size="sm" className="h-7 pointer-coarse:h-9">
        <a {...downloadProps(path)} aria-label={t('files.download')}>
          <Download />
          <span className={cn(short && 'max-sm:sr-only')}>{t('files.download')}</span>
        </a>
      </Button>
    </>
  )
  if (paged && info.isPending) return <PageSkeleton />
  if (paged && info.data)
    return (
      <Sensitive placeholder={<div className="m-4 flex-1 rounded-lg bg-muted/60" aria-label={t('presentation.hidden')} />}>
        <PdfPages key={path} path={path} pages={info.data.pages} ratio={info.data.ratio} version={info.data.mtime} className={className}>
          {actions(true)}
        </PdfPages>
      </Sensitive>
    )
  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', className)}>
      <Sensitive placeholder={<div className="m-4 flex-1 rounded-lg bg-muted/60" aria-label={t('presentation.hidden')} />}>
        <iframe key={path} src={fileRawUrl(path)} title={basename(path)} className="min-h-0 w-full flex-1 border-0 bg-muted/30" />
      </Sensitive>
      {/* Some browsers do not render PDFs inline: always offer a way out. */}
      <div className="flex shrink-0 items-center justify-end gap-1 border-t px-3 py-1.5">
        <span className="mr-auto text-xs text-muted-foreground max-sm:hidden">{t('files.pdfHint')}</span>
        {actions(false)}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ info card */
export function FileInfoCard({
  path,
  size,
  mime,
  reason,
  icon: Icon = FileWarning,
  className,
  children,
}: {
  path: string
  size?: number
  mime?: string
  reason?: React.ReactNode
  icon?: LucideIcon
  className?: string
  children?: React.ReactNode
}) {
  const t = useT()
  const ext = extOf(path)
  return (
    <div className={cn('flex min-h-0 flex-1 items-center justify-center p-6', className)}>
      <div className="grid w-full max-w-sm justify-items-center gap-4 rounded-xl border bg-card p-6 text-center">
        <div className="flex size-12 items-center justify-center rounded-xl border bg-muted/60 text-muted-foreground">
          <Icon className="size-6" strokeWidth={1.6} />
        </div>
        <div className="grid min-w-0 gap-1">
          <p className="truncate text-sm font-medium">
            <Sensitive length={10}>{basename(path)}</Sensitive>
          </p>
          <p className="text-[13px] text-muted-foreground">
            {[ext ? ext.toUpperCase() : null, mime, size != null ? fmtBytes(size) : null].filter(Boolean).join(' · ')}
          </p>
          {reason && <p className="text-[13px] text-muted-foreground">{reason}</p>}
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <Button asChild variant="secondary" size="sm">
            <a {...downloadProps(path, { size })}>
              <Download />
              {t('files.download')}
            </a>
          </Button>
          <Button asChild variant="ghost" size="sm">
            <a {...openRawProps(path)}>
              <ExternalLink />
              {t(inIosApp() ? 'files.openRawInApp' : 'files.openRaw')}
            </a>
          </Button>
          {children}
        </div>
      </div>
    </div>
  )
}
