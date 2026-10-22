// Guided tour: spotlight overlay (cut-out around `data-tour` targets) + a coach-mark card.
// Mounted once in the AppShell. Keyboard: Esc skips, ←/→ move, Tab stays inside the card (focus trap).
// A missing target never blocks: the step is skipped. Positions follow resize/scroll (rAF measuring).
import * as React from 'react'
import { createPortal } from 'react-dom'
import { useLocation, useNavigate } from 'react-router'
import { BookOpen, GraduationCap, X } from 'lucide-react'
import { useT } from '@/i18n'
import { useUI } from '@/stores/ui'
import { useIsMobile } from '@/stores/media'
import { useTouchNav } from '@/components/shell/TouchNav'
import { useWorkspace } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui'
import { STEPS, type StepCtx, type TourStep } from './steps'
import { TOUR_PENDING_KEY, useTutorialHref, useTour } from './store'

type Rect = { x: number; y: number; w: number; h: number }
const PAD = 6

/** First visible element for each target id, unioned. */
function measure(targets: string[]): Rect | null {
  let r: Rect | null = null
  for (const id of targets) {
    const els = document.querySelectorAll<HTMLElement>(`[data-tour="${id}"]`)
    for (const el of els) {
      const b = el.getBoundingClientRect()
      if (b.width < 1 || b.height < 1 || getComputedStyle(el).visibility === 'hidden') continue
      if (!r) r = { x: b.left, y: b.top, w: b.width, h: b.height }
      else {
        const x = Math.min(r.x, b.left)
        const y = Math.min(r.y, b.top)
        r = { x, y, w: Math.max(r.x + r.w, b.right) - x, h: Math.max(r.y + r.h, b.bottom) - y }
      }
      break
    }
  }
  return r
}
function firstEl(targets: string[]): HTMLElement | null {
  for (const id of targets)
    for (const el of document.querySelectorAll<HTMLElement>(`[data-tour="${id}"]`)) {
      const b = el.getBoundingClientRect()
      if (b.width >= 1 && b.height >= 1) return el
    }
  return null
}
const sameRect = (a: Rect | null, b: Rect | null) =>
  a === b || (!!a && !!b && Math.abs(a.x - b.x) < 0.5 && Math.abs(a.y - b.y) < 0.5 && Math.abs(a.w - b.w) < 0.5 && Math.abs(a.h - b.h) < 0.5)

/** Starts the tour once after onboarding (flag set by the onboarding "Finish" button). */
function useAutoStart() {
  const tourDone = useUI((s) => s.tourDone)
  React.useEffect(() => {
    let pending = false
    try {
      pending = sessionStorage.getItem(TOUR_PENDING_KEY) === '1'
      sessionStorage.removeItem(TOUR_PENDING_KEY)
    } catch {
      /* ignore */
    }
    if (!pending || tourDone) return
    const id = setTimeout(() => useTour.getState().start(), 700)
    return () => clearTimeout(id)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
}

export function TourHost() {
  useAutoStart()
  const active = useTour((s) => s.active)
  const run = useTour((s) => s.run)
  if (!active) return null
  return createPortal(<TourRun key={run} />, document.body)
}

function TourRun() {
  const t = useT()
  const showcase = useTour((s) => s.showcase)
  const steps = showcase ?? STEPS
  // The guided tour ends on a closing card (tutorial / docs); a showcase just closes after its last step.
  const FINAL = steps.length
  const navigate = useNavigate()
  const loc = useLocation()
  const mobile = useIsMobile()
  const { data: ws } = useWorkspace()
  const setTourDone = useUI((s) => s.setTourDone)
  const [index, setIndex] = React.useState(0)
  const [dir, setDir] = React.useState<1 | -1>(1)
  const [rect, setRect] = React.useState<Rect | null>(null)
  /** The step whose target is currently shown (−1 while looking for it). */
  const [shown, setShown] = React.useState(-1)
  const card = React.useRef<HTMLDivElement>(null)
  const restoreFocus = React.useRef<Element | null>(document.activeElement)

  const topics = React.useMemo(() => (ws?.projects || []).flatMap((p) => p.topics), [ws])
  const tutorialHref = useTutorialHref()
  const locRef = React.useRef(loc)
  locRef.current = loc
  const ctxRef = React.useRef<StepCtx>(null as unknown as StepCtx)
  ctxRef.current = { pathname: loc.pathname, search: new URLSearchParams(loc.search), mobile, firstTopic: topics[0]?.path ?? null }

  const finish = React.useCallback(() => {
    if (!showcase) setTourDone(true)
    useTour.getState().stop()
    const el = restoreFocus.current
    if (el instanceof HTMLElement && el.isConnected) el.focus({ preventScroll: true })
  }, [setTourDone, showcase])

  const go = React.useCallback((d: 1 | -1) => {
    setDir(d)
    setIndex((i) => Math.max(0, Math.min(FINAL, i + d)))
  }, [FINAL])

  // Resolve the current step: route if needed, then wait (≤ 3 s) for the target, else skip it.
  React.useEffect(() => {
    if (index >= FINAL && showcase) {
      // → on the last card does what its button does ("Try it" opens the demo).
      finish()
      steps[FINAL - 1]?.after?.()
      return
    }
    if (index >= FINAL) {
      setShown(FINAL)
      setRect(null)
      // Touch layout: the last card is shown over the app, not over a drawer.
      if (ctxRef.current.mobile) useTouchNav.getState().setPanel(null)
      return
    }
    const step = steps[index]
    step.before?.(ctxRef.current)
    // The previous card stays on screen until this step's target is found (no flash between steps).
    let cancelled = false
    let routed = false
    let navAt = 0
    const started = performance.now()
    const tick = () => {
      if (cancelled) return
      if (!routed && step.route && !(step.routeIfMissing && measure(step.targets))) {
        routed = true
        const to = step.route(ctxRef.current)
        const here = locRef.current.pathname + locRef.current.search
        if (to && to !== here) {
          navigate(to)
          navAt = performance.now()
        }
      }
      if (!step.targets.length && (!navAt || performance.now() - navAt > 150)) {
        setRect(null)
        setShown(index)
        return
      }
      const el = firstEl(step.targets)
      // After a route change, give the new page a moment so a target of the old page is not picked.
      if (el && (!navAt || performance.now() - navAt > 150)) {
        el.scrollIntoView({ block: 'nearest', inline: 'nearest' })
        setRect(measure(step.targets))
        setShown(index)
        return
      }
      if (performance.now() - started > 3000) {
        // Missing target: skip in the current direction (never block the app).
        setIndex((i) => (dir === -1 && i === 0 ? 1 : Math.max(0, Math.min(FINAL, i + dir))))
        return
      }
      timer = window.setTimeout(tick, 80)
    }
    let timer = window.setTimeout(tick, 0)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [index]) // eslint-disable-line react-hooks/exhaustive-deps

  // Follow the target (resize, scroll, layout changes) while a step is shown.
  React.useEffect(() => {
    if (shown < 0 || shown >= FINAL) return
    const targets = steps[shown].targets
    let raf = 0
    let last: Rect | null = null
    const loop = () => {
      const r = measure(targets)
      if (!sameRect(r, last)) {
        last = r
        setRect(r)
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [shown])

  // Focus the primary button of each new card.
  React.useEffect(() => {
    if (shown < 0) return
    const id = requestAnimationFrame(() => card.current?.querySelector<HTMLElement>('[data-tour-primary]')?.focus({ preventScroll: true }))
    return () => cancelAnimationFrame(id)
  }, [shown])

  // Keyboard + focus trap. Capture phase on window: the app's own shortcuts never see keys during the tour.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        finish()
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        go(1)
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        go(-1)
      } else if (e.key === 'Tab') {
        const items = Array.from(card.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href]') || [])
        if (items.length) {
          e.preventDefault()
          const i = items.indexOf(document.activeElement as HTMLElement)
          const n = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : i === items.length - 1 ? 0 : i + 1
          items[n].focus()
        }
      }
      e.stopPropagation()
      e.stopImmediatePropagation()
    }
    const onFocus = (e: FocusEvent) => {
      if (card.current && e.target instanceof Node && !card.current.contains(e.target)) card.current.querySelector<HTMLElement>('[data-tour-primary]')?.focus({ preventScroll: true })
    }
    window.addEventListener('keydown', onKey, true)
    document.addEventListener('focusin', onFocus)
    return () => {
      window.removeEventListener('keydown', onKey, true)
      document.removeEventListener('focusin', onFocus)
    }
  }, [finish, go])

  const step = shown >= 0 && shown < FINAL ? steps[shown] : null
  const isFinal = shown === FINAL
  const hole = step && rect ? clampHole(rect) : null
  const pos = useCardPosition(hole, mobile, card, shown)

  return (
    <div className="fixed inset-0 z-[80]" data-tour-overlay>
      {/* Click shield: the app stays visible but inert during the tour. */}
      <div className="absolute inset-0" onClick={(e) => e.stopPropagation()} aria-hidden />
      {hole ? (
        <div
          aria-hidden
          className="pointer-events-none absolute rounded-lg shadow-[0_0_0_9999px_var(--overlay)] ring-2 ring-primary transition-all duration-200 ease-out motion-reduce:transition-none"
          style={{ left: hole.x, top: hole.y, width: hole.w, height: hole.h }}
        />
      ) : (
        <div aria-hidden className="pointer-events-none absolute inset-0 bg-overlay" />
      )}
      {(step || isFinal) && (
        <div
          ref={card}
          role="dialog"
          aria-modal="true"
          aria-labelledby="mx-tour-title"
          aria-describedby="mx-tour-body"
          className={cn(
            'absolute grid gap-3 rounded-xl border bg-popover p-4 text-popover-foreground shadow-pop animate-in',
            mobile ? 'inset-x-3' : 'w-[340px]',
            isFinal && !mobile && 'w-[380px]',
          )}
          style={isFinal ? finalStyle(mobile) : pos}
        >
          {isFinal ? (
            <FinalCard tutorialHref={tutorialHref} onClose={finish} onGo={(to) => {
              finish()
              navigate(to)
            }} />
          ) : (
            step && (
              <>
                <div className="flex items-start gap-3">
                  <div className="grid min-w-0 flex-1 gap-1">
                    <span className="text-xs font-medium text-primary tabular-nums">
                      {showcase && steps.length === 1 ? t('show.badge') : t('tour.step', { n: shown + 1, total: steps.length })}
                    </span>
                    <h2 id="mx-tour-title" className="text-[15px] font-semibold tracking-tight">
                      {t(step.title)}
                    </h2>
                  </div>
                  <button
                    type="button"
                    onClick={finish}
                    aria-label={t('tour.skip')}
                    className="-mt-1 -mr-1 flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <X className="size-4" />
                  </button>
                </div>
                <p id="mx-tour-body" className="text-sm text-muted-foreground">
                  {t(mobile && step.bodyMobile ? step.bodyMobile : step.body)}
                </p>
                <div className="flex items-center gap-2 pt-1">
                  {steps.length > 1 && <Dots index={shown} steps={steps} />}
                  <div className="ml-auto flex gap-2">
                    {shown > 0 && (
                      <Button variant="ghost" size="sm" onClick={() => go(-1)}>
                        {t('tour.back')}
                      </Button>
                    )}
                    <Button
                      size="sm"
                      onClick={() => {
                        if (!showcase || shown < steps.length - 1) return go(1)
                        finish()
                        step.after?.()
                      }}
                      data-tour-primary
                    >
                      {shown === steps.length - 1 ? (showcase ? t(step.cta ?? 'show.done') : t('tour.finish')) : t('tour.next')}
                    </Button>
                  </div>
                </div>
              </>
            )
          )}
        </div>
      )}
      <span className="sr-only" aria-live="polite">
        {step ? `${t('tour.step', { n: shown + 1, total: steps.length })}: ${t(step.title)}` : isFinal ? t('tour.final.title') : ''}
      </span>
    </div>
  )
}

/** Padded target rect, kept 3 px inside the viewport so the ring is never cut by the screen edge. */
function clampHole(r: Rect): Rect {
  const m = 3
  const x = Math.max(m, r.x - PAD)
  const y = Math.max(m, r.y - PAD)
  const right = Math.min(window.innerWidth - m, r.x + r.w + PAD)
  const bottom = Math.min(window.innerHeight - m, r.y + r.h + PAD)
  return { x, y, w: Math.max(0, right - x), h: Math.max(0, bottom - y) }
}

function Dots({ index, steps }: { index: number; steps: TourStep[] }) {
  return (
    <span className="flex items-center gap-1" aria-hidden>
      {steps.map((s, i) => (
        <span key={s.id} className={cn('size-1.5 rounded-full bg-muted-foreground/30 transition-colors', i === index && 'w-3 bg-primary')} />
      ))}
    </span>
  )
}

function FinalCard({ tutorialHref, onClose, onGo }: { tutorialHref: string | null; onClose: () => void; onGo: (to: string) => void }) {
  const hasTutorial = !!tutorialHref
  const t = useT()
  return (
    <>
      <div className="flex size-10 items-center justify-center rounded-lg bg-primary/12 text-primary">
        <GraduationCap className="size-5" />
      </div>
      <div className="grid gap-1">
        <h2 id="mx-tour-title" className="text-base font-semibold tracking-tight">
          {t('tour.final.title')}
        </h2>
        <p id="mx-tour-body" className="text-sm text-muted-foreground">
          {hasTutorial ? t('tour.final.body') : t('tour.final.bodyNoTutorial')}
        </p>
      </div>
      <div className="flex flex-wrap justify-end gap-2 pt-1">
        <Button variant="ghost" size="sm" onClick={onClose}>
          {t('tour.close')}
        </Button>
        {hasTutorial ? (
          <Button size="sm" onClick={() => onGo(tutorialHref!)} data-tour-primary>
            <GraduationCap /> {t('tour.final.tutorial')}
          </Button>
        ) : (
          <Button size="sm" onClick={() => onGo('/docs')} data-tour-primary>
            <BookOpen /> {t('tour.final.docs')}
          </Button>
        )}
      </div>
    </>
  )
}

function finalStyle(mobile: boolean): React.CSSProperties {
  return mobile
    ? { bottom: 'calc(var(--safe-bottom) + 12px)' }
    : { left: '50%', top: '50%', transform: 'translate(-50%, -50%)' }
}

/** Card placement: desktop = beside the hole (right, below, above, left — first that fits), clamped to the
 *  viewport; mobile = a full-width card at the top or the bottom, away from the target. */
function useCardPosition(hole: Rect | null, mobile: boolean, card: React.RefObject<HTMLDivElement | null>, key: number): React.CSSProperties {
  const [size, setSize] = React.useState({ w: 340, h: 180 })
  React.useLayoutEffect(() => {
    const el = card.current
    if (!el) return
    const read = () => setSize((s) => (s.w === el.offsetWidth && s.h === el.offsetHeight ? s : { w: el.offsetWidth, h: el.offsetHeight }))
    const ro = new ResizeObserver(read)
    ro.observe(el)
    read()
    return () => ro.disconnect()
  }, [card, key])
  if (!hole) return { left: '50%', top: '50%', transform: 'translate(-50%, -50%)' }
  const vw = window.innerWidth
  const vh = window.innerHeight
  const gap = 12
  const m = 12
  if (mobile) {
    if (vh - (hole.y + hole.h) >= size.h + gap + m) return { top: hole.y + hole.h + gap }
    if (hole.y >= size.h + gap + m) return { bottom: vh - hole.y + gap }
    return { bottom: 'calc(var(--safe-bottom-ui) + 12px)' }
  }
  const clampX = (x: number) => Math.max(m, Math.min(vw - size.w - m, x))
  const clampY = (y: number) => Math.max(m, Math.min(vh - size.h - m, y))
  if (hole.x + hole.w + gap + size.w + m <= vw && hole.w < vw / 2) return { left: hole.x + hole.w + gap, top: clampY(hole.y) }
  if (hole.y + hole.h + gap + size.h + m <= vh) return { left: clampX(hole.x), top: hole.y + hole.h + gap }
  if (hole.y - gap - size.h >= m) return { left: clampX(hole.x), top: hole.y - gap - size.h }
  if (hole.x - gap - size.w >= m) return { left: hole.x - gap - size.w, top: clampY(hole.y) }
  return { left: clampX(hole.x), top: m }
}
