// Showcases (What's new -> Show me): spotlight overlay (cut-out around `data-tour` targets) + a coach-mark card.
// Mounted once in the AppShell (the getting-started guide is guide/Guide.tsx). Keyboard: Esc skips, ←/→ move, Tab stays inside the card (focus trap).
// A missing target never blocks: the step is skipped. Positions follow resize/scroll (rAF measuring).
import * as React from 'react'
import { createPortal } from 'react-dom'
import { useLocation, useNavigate } from 'react-router'
import { X } from 'lucide-react'
import { useT } from '@/i18n'
import { useIsMobile } from '@/stores/media'
import { useWorkspace } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui'
import type { StepCtx, TourStep } from './steps'
import { useTour } from './store'

import { clampHole, firstEl, measure, sameRect, useCardPosition, type Rect } from './spot'

export function TourHost() {
  const active = useTour((s) => s.active)
  const run = useTour((s) => s.run)
  const showcase = useTour((s) => s.showcase)
  if (!active || !showcase) return null
  return createPortal(<TourRun key={run} steps={showcase} />, document.body)
}

function TourRun({ steps }: { steps: TourStep[] }) {
  const t = useT()
  const FINAL = steps.length
  const navigate = useNavigate()
  const loc = useLocation()
  const mobile = useIsMobile()
  const { data: ws } = useWorkspace()
  const [index, setIndex] = React.useState(0)
  const [dir, setDir] = React.useState<1 | -1>(1)
  const [rect, setRect] = React.useState<Rect | null>(null)
  /** The step whose target is currently shown (−1 while looking for it). */
  const [shown, setShown] = React.useState(-1)
  const card = React.useRef<HTMLDivElement>(null)
  const restoreFocus = React.useRef<Element | null>(document.activeElement)

  const topics = React.useMemo(() => (ws?.projects || []).flatMap((p) => p.topics), [ws])
  const locRef = React.useRef(loc)
  locRef.current = loc
  const ctxRef = React.useRef<StepCtx>(null as unknown as StepCtx)
  ctxRef.current = { pathname: loc.pathname, search: new URLSearchParams(loc.search), mobile, firstTopic: topics[0]?.path ?? null }

  const finish = React.useCallback(() => {
    useTour.getState().stop()
    const el = restoreFocus.current
    if (el instanceof HTMLElement && el.isConnected) el.focus({ preventScroll: true })
  }, [])

  const go = React.useCallback((d: 1 | -1) => {
    setDir(d)
    setIndex((i) => Math.max(0, Math.min(FINAL, i + d)))
  }, [FINAL])

  // Resolve the current step: route if needed, then wait (≤ 3 s) for the target, else skip it.
  React.useEffect(() => {
    if (index >= FINAL) {
      // → on the last card does what its button does ("Try it" opens the demo).
      finish()
      steps[FINAL - 1]?.after?.()
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
  const hole = step && rect ? clampHole(rect) : null
  const pos = useCardPosition(hole, mobile, card, shown)

  return (
    <div className="fixed inset-0 z-[80]" data-tour-overlay>
      {/* Click shield: the app stays visible but inert during the tour. */}
      <div className="absolute inset-0" onClick={(e) => e.stopPropagation()} aria-hidden />
      {/* keyed: the same element reused between the two would keep the dim off (its shadow mid-transition) */}
      {hole ? (
        <div
          key="hole"
          aria-hidden
          className="pointer-events-none absolute rounded-lg shadow-[0_0_0_9999px_var(--overlay)] ring-2 ring-primary transition-all duration-200 ease-out motion-reduce:transition-none"
          style={{ left: hole.x, top: hole.y, width: hole.w, height: hole.h }}
        />
      ) : (
        <div key="dim" aria-hidden className="pointer-events-none absolute inset-0 bg-overlay" />
      )}
      {step && (
        <div
          ref={card}
          role="dialog"
          aria-modal="true"
          aria-labelledby="mx-tour-title"
          aria-describedby="mx-tour-body"
          className={cn(
            'absolute grid gap-3 rounded-xl border bg-popover p-4 text-popover-foreground shadow-pop animate-in',
            mobile ? 'inset-x-3' : 'w-[340px]',
          )}
          style={pos}
        >
          <>
                <div className="flex items-start gap-3">
                  <div className="grid min-w-0 flex-1 gap-1">
                    <span className="text-xs font-medium text-primary tabular-nums">
                      {steps.length === 1 ? t('show.badge') : t('tour.step', { n: shown + 1, total: steps.length })}
                    </span>
                    <h2 id="mx-tour-title" className="text-[15px] font-semibold tracking-tight">
                      {t(step.title)}
                    </h2>
                  </div>
                  <button
                    type="button"
                    onClick={finish}
                    aria-label={t('tour.skip')}
                    className="-mt-1 -mr-1 flex size-8 shrink-0 items-center pointer-coarse:size-10 justify-center rounded-md text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
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
                        if (shown < steps.length - 1) return go(1)
                        finish()
                        step.after?.()
                      }}
                      data-tour-primary
                    >
                      {shown === steps.length - 1 ? t(step.cta ?? 'show.done') : t('tour.next')}
                    </Button>
                  </div>
                </div>
              </>
        </div>
      )}
      <span className="sr-only" aria-live="polite">
        {step ? `${t('tour.step', { n: shown + 1, total: steps.length })}: ${t(step.title)}` : ''}
      </span>
    </div>
  )
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


