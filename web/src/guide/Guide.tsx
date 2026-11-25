// Getting-started guide (Help -> Getting started guide; proposed once after the onboarding or the update that
// brings it). A first dialog asks the level (beginner / intermediate) and the tour (full ~5 min, partial ~2 min with
// the uses to show, recommended ones ticked), then each step lights up a part of the interface with its card: a fixed
// explanation and tip, plus the personal part written by Opus on the server (a line linking it to what the user just
// did, ready-to-send prompts in one of their topics). "Try it" puts the prompt in a new session's message box and
// pauses the guide in a small pill on the right edge ("Continue"); the progress lives on the server (every device, any
// time later from Help). Keyboard: Esc pauses, ←/→ move.
import * as React from 'react'
import { createPortal } from 'react-dom'
import { useLocation, useNavigate, useSearchParams } from 'react-router'
import { ArrowRight, BookOpen, Check, Compass, GraduationCap, Lightbulb, Pause, Play, RefreshCw, Sparkles, X } from 'lucide-react'
import { useT, type TKey } from '@/i18n'
import { useIsMobile } from '@/stores/media'
import { useTouchNav } from '@/components/shell/TouchNav'
import { useSaveSettings, useSettings, useWorkspace } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { Badge, Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, Spinner } from '@/components/ui'
import type { StepCtx } from '@/tour/steps'
import { clampHole, firstEl, measure, sameRect, useCardPosition, type Rect } from '@/tour/spot'
import { useGuideOn, useGuideOpen, useTutorialHref } from '@/tour/store'
import { useGuide, useGuideActions, useGuideContext, type GuidePrompt, type GuideState } from './api'
import { plan, STEP_BY_ID, stepBody, stepTip, stepTitle, useLabel, USES, type Use } from './steps'

export function GuideHost() {
  const { data } = useGuide()
  const open = useGuideOpen((s) => s.open)
  const loc = useLocation()
  const [params, setParams] = useSearchParams()
  // ?guide opens it (a link from the docs, the demo)
  React.useEffect(() => {
    if (!params.has('guide')) return
    useGuideOpen.getState().setOpen(true)
    const next = new URLSearchParams(params)
    next.delete('guide')
    setParams(next, { replace: true })
  }, [params]) // eslint-disable-line react-hooks/exhaustive-deps
  // Proposed once: never opened here, onboarding done (a fresh install, or the first visit after the update).
  const offer = !!data?.offer && !loc.pathname.startsWith('/welcome')
  React.useEffect(() => {
    if (!offer) return
    const id = setTimeout(() => useGuideOpen.getState().setOpen(true), 900)
    return () => clearTimeout(id)
  }, [offer])
  if (!data) return null
  return (
    <>
      {open && <GuideDialog state={data} />}
      {!open && data.status === 'running' && data.index < data.steps.length && createPortal(<GuideRun state={data} />, document.body)}
      {!open && data.status === 'paused' && data.index < data.steps.length && createPortal(<GuideDock state={data} />, document.body)}
    </>
  )
}

/* ------------------------------------------------------------------ first dialog: resume, level, tour */

function GuideDialog({ state }: { state: GuideState }) {
  const t = useT()
  const actions = useGuideActions()
  const { data: withCtx } = useGuideContext(true)
  const ctx = withCtx?.context
  const resumable = state.steps.length > 0 && state.index < state.steps.length && state.status !== 'done'
  // the guide follows the language of Harness (Settings -> General): no question about it
  const [phase, setPhase] = React.useState<'resume' | 'level' | 'mode'>(resumable ? 'resume' : 'level')
  const [level, setLevel] = React.useState<'beginner' | 'intermediate'>(state.level ?? 'beginner')
  const [uses, setUses] = React.useState<Use[] | null>(null)
  const chosen = uses ?? (state.uses.length ? state.uses : (ctx?.recommended ?? []))
  const close = (dismiss: boolean) => {
    useGuideOpen.getState().setOpen(false)
    // closed without starting: not proposed again (Help -> Getting started guide stays)
    if (dismiss && state.status !== 'running' && state.status !== 'paused') void actions.patch({ status: 'dismissed' })
  }
  const start = (mode: 'full' | 'partial') => {
    const steps = plan(mode, chosen, ctx?.case === 'existing')
    void actions.patch({ status: 'running', level, mode, uses: chosen, steps, index: 0, done: [] }).then(() => actions.cards(steps.slice(0, 4)))
    useGuideOpen.getState().setOpen(false)
  }
  const caseLine: TKey = ctx?.case === 'import' ? 'guide.case.import' : ctx?.case === 'existing' ? 'guide.case.existing' : 'guide.case.new'

  return (
    <Dialog open onOpenChange={(o) => !o && close(true)}>
      <DialogContent className="md:max-w-xl" data-testid="guide-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Compass className="size-4 text-primary" /> {t('help.tour')}
          </DialogTitle>
          <DialogDescription>
            {phase === 'resume'
              ? t('guide.resumeDesc', { n: state.index + 1, total: state.steps.length })
              : ctx
                ? t(caseLine)
                : t('guide.intro')}
          </DialogDescription>
        </DialogHeader>

        {phase === 'resume' && (
          <div className="grid gap-2">
            <Button
              onClick={() => {
                void actions.patch({ status: 'running' })
                useGuideOpen.getState().setOpen(false)
              }}
              data-testid="guide-resume"
            >
              <Play /> {t('guide.resume')}
            </Button>
            <Button variant="ghost" onClick={() => void actions.reset().then(() => setPhase('level'))}>
              <RefreshCw /> {t('guide.restart')}
            </Button>
          </div>
        )}

        {phase === 'level' && (
          <div className="grid gap-2">
            {(['beginner', 'intermediate'] as const).map((l) => (
              <Choice
                key={l}
                title={t(`guide.level.${l}` as TKey)}
                desc={t(`guide.level.${l}Desc` as TKey)}
                onClick={() => {
                  setLevel(l)
                  setPhase('mode')
                }}
                testid={`guide-level-${l}`}
              />
            ))}
            <div className="flex items-center justify-center pt-1">
              <button type="button" className="py-2 text-[13px] text-muted-foreground hover:text-foreground" onClick={() => close(true)} data-testid="guide-close">
                {t('guide.notNow')}
              </button>
            </div>
          </div>
        )}

        {phase === 'mode' && (
          <div className="grid gap-2">
            <Choice title={t('guide.mode.full')} desc={t('guide.mode.fullDesc')} onClick={() => start('full')} testid="guide-mode-full" />
            <div className="grid gap-3 rounded-lg border p-3">
              <div className="grid gap-0.5">
                <span className="text-sm font-medium">{t('guide.mode.partial')}</span>
                <span className="text-[13px] text-muted-foreground">{t('guide.mode.partialDesc')}</span>
              </div>
              <div className="grid gap-1.5">
                {USES.map((u) => (
                  <label key={u} className="flex min-h-8 cursor-pointer items-center gap-2 text-[13px] pointer-coarse:min-h-10">
                    <Checkbox
                      checked={chosen.includes(u)}
                      onCheckedChange={(v) => setUses(v ? [...chosen, u] : chosen.filter((x) => x !== u))}
                      data-testid={`guide-use-${u}`}
                    />
                    <span className="truncate">{t(useLabel(u))}</span>
                    {ctx?.recommended.includes(u) && (
                      <Badge variant="secondary" className="ml-auto shrink-0 text-[11px]">
                        {t('guide.recommended')}
                      </Badge>
                    )}
                  </label>
                ))}
              </div>
              <Button size="sm" className="justify-self-end" onClick={() => start('partial')} data-testid="guide-mode-partial">
                {t('guide.start')} <ArrowRight />
              </Button>
            </div>
            <div className="flex items-center justify-between pt-1">
              <Button variant="ghost" size="sm" onClick={() => setPhase('level')}>
                {t('tour.back')}
              </Button>
              <button type="button" className="py-2 text-[13px] text-muted-foreground hover:text-foreground" onClick={() => close(true)}>
                {t('guide.notNow')}
              </button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Choice({ title, desc, onClick, testid, icon }: { title: string; desc: string; onClick: () => void; testid: string; icon?: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testid}
      className="group flex items-center gap-3 rounded-lg border p-3 text-left transition-colors outline-none hover:border-primary/60 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
    >
      {icon}
      <span className="grid min-w-0 flex-1 gap-0.5">
        <span className="text-sm font-medium">{title}</span>
        {desc && <span className="text-[13px] text-muted-foreground">{desc}</span>}
      </span>
      <ArrowRight className="size-4 shrink-0 text-muted-foreground group-hover:text-primary" />
    </button>
  )
}

/* ------------------------------------------------------------------ the tour itself */

function GuideRun({ state }: { state: GuideState }) {
  const t = useT()
  const navigate = useNavigate()
  const loc = useLocation()
  const mobile = useIsMobile()
  const actions = useGuideActions()
  const { data: ws } = useWorkspace()
  const { data: settings } = useSettings()
  const save = useSaveSettings()
  const tutorialHref = useTutorialHref()
  const { index, steps } = state
  const id = steps[index]
  const step = STEP_BY_ID[id]
  const total = steps.length
  const last = index === total - 1
  const card = state.cards[id]
  const [rect, setRect] = React.useState<Rect | null>(null)
  const [shown, setShown] = React.useState<string | null>(null)
  const [retry, setRetry] = React.useState(0)
  const cardRef = React.useRef<HTMLDivElement>(null)

  const locRef = React.useRef(loc)
  locRef.current = loc
  const ctxRef = React.useRef<StepCtx>(null as unknown as StepCtx)
  ctxRef.current = { pathname: loc.pathname, search: new URLSearchParams(loc.search), mobile, firstTopic: ws?.projects.flatMap((p) => p.topics)[0]?.path ?? null }

  React.useEffect(() => {
    useGuideOn.setState({ on: true })
    return () => useGuideOn.setState({ on: false })
  }, [])

  const featureOff = !!step?.feature && !!settings && !settings[step.feature]
  const offRef = React.useRef(featureOff)
  offRef.current = featureOff

  // Ask for the cards of this step and the next ones (the server skips those written or on their way).
  React.useEffect(() => {
    void actions.cards(steps.slice(index, index + 3))
  }, [index]) // eslint-disable-line react-hooks/exhaustive-deps

  // Resolve the step: its page, then its target (≤ 2 s); not found -> the card in the middle, never a blocked guide.
  React.useEffect(() => {
    if (!step) return
    step.before?.(ctxRef.current)
    let cancelled = false
    let navAt = 0
    const to = step.route?.(ctxRef.current)
    if (to && to !== locRef.current.pathname) {
      navigate(to)
      navAt = performance.now()
    }
    const started = performance.now()
    let timer = 0
    const tick = () => {
      if (cancelled) return
      const settled = !navAt || performance.now() - navAt > 150
      const el = step.targets.length ? firstEl(step.targets) : null
      // a page switched off has no entry to light up: the card at once (it offers to switch the page on)
      if (settled && (el || !step.targets.length || offRef.current || performance.now() - started > 2000)) {
        el?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
        setRect(el ? measure(step.targets) : null)
        setShown(id)
        return
      }
      timer = window.setTimeout(tick, 80)
    }
    timer = window.setTimeout(tick, 0)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [id, retry]) // eslint-disable-line react-hooks/exhaustive-deps

  // Follow the target while the card is shown (resize, scroll, a drawer sliding in).
  React.useEffect(() => {
    if (shown !== id || !step?.targets.length) return
    let raf = 0
    let prev: Rect | null = null
    const loop = () => {
      const r = measure(step.targets)
      if (!sameRect(r, prev)) {
        prev = r
        setRect(r)
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [shown, id]) // eslint-disable-line react-hooks/exhaustive-deps

  const done = (extra?: string) => [...new Set([...state.done, ...(extra ? [extra] : [])])]
  const go = (d: 1 | -1) => {
    if (d === 1 && last) return void actions.patch({ status: 'done', index: total, done: done(id) })
    void actions.patch({ index: Math.max(0, Math.min(total - 1, index + d)), done: d === 1 ? done(id) : state.done })
  }
  const pause = () => {
    // a drawer the step opened would cover the pill (and turns modal again once the guide is off)
    if (mobile) useTouchNav.getState().setPanel(null)
    void actions.patch({ status: 'paused' })
  }
  const tryPrompt = (p: GuidePrompt) => {
    // the next step waits in the pill at the top; the prompt is in the new session's box, not sent
    void actions.patch({ status: 'paused', index: last ? index : index + 1, done: done(id), tried: { step: id, label: p.label, topic: p.topic } })
    if (mobile) useTouchNav.getState().setPanel(null)
    navigate(`/sessions?path=${encodeURIComponent(p.topic)}&new=1&prompt=${encodeURIComponent(p.text)}`)
  }

  // Esc pauses, arrows move (not while typing in a field of the card).
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA)$/.test(e.target.tagName)
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        pause()
      } else if (!typing && e.key === 'ArrowRight') {
        e.preventDefault()
        go(1)
      } else if (!typing && e.key === 'ArrowLeft' && index > 0) {
        e.preventDefault()
        go(-1)
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  })

  React.useEffect(() => {
    if (shown !== id) return
    const r = requestAnimationFrame(() => cardRef.current?.querySelector<HTMLElement>('[data-guide-primary]')?.focus({ preventScroll: true }))
    return () => cancelAnimationFrame(r)
  }, [shown, id])

  const hole = shown === id && rect ? clampHole(rect) : null
  // keyed on the card being on screen: its size is measured once it exists
  const pos = useCardPosition(hole, mobile, cardRef, shown === id ? index : -1)
  if (!step) return null
  const writes = step.prompts || id === 'welcome'
  const prompts = card?.status === 'ready' ? card.prompts || [] : []

  return (
    <div className="fixed inset-0 z-[80]" data-testid="guide-overlay">
      <Shield hole={hole} />
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
      {shown === id && (
        <div
          ref={cardRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="mx-guide-title"
          data-testid="guide-card"
          data-step={id}
          className={cn(
            'absolute grid max-h-[calc(100dvh-24px)] gap-3.5 overflow-y-auto rounded-xl border bg-popover text-popover-foreground shadow-pop animate-in',
            mobile ? 'inset-x-3 p-4' : 'w-[min(500px,calc(100vw-24px))] p-5',
          )}
          style={hole ? pos : mobile ? { bottom: 'calc(var(--safe-bottom-ui) + 12px)' } : { left: '50%', top: '50%', transform: 'translate(-50%, -50%)' }}
        >
          <div className="flex items-start gap-3">
            <div className="grid min-w-0 flex-1 gap-1">
              <span className="text-[13px] font-medium text-primary tabular-nums">{t('tour.step', { n: index + 1, total })}</span>
              <h2 id="mx-guide-title" className="text-lg font-semibold tracking-tight">
                {t(stepTitle(id))}
              </h2>
            </div>
            <button
              type="button"
              onClick={pause}
              aria-label={t('guide.pause')}
              className="-mt-1 -mr-1 flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:size-10"
            >
              <X className="size-4" />
            </button>
          </div>

          {writes && card?.status === 'ready' && card.intro && (
            <p className="flex gap-2 text-[15px] text-foreground" data-testid="guide-intro">
              <Sparkles className="mt-1 size-4 shrink-0 text-primary" />
              <span>{card.intro}</span>
            </p>
          )}
          <p className="text-[15px] leading-relaxed text-muted-foreground">{t(stepBody(id))}</p>
          <p className="flex gap-2 rounded-md bg-fill-1 px-3 py-2.5 text-sm text-muted-foreground">
            <Lightbulb className="mt-0.5 size-4 shrink-0 text-primary" />
            <span>{t(stepTip(id))}</span>
          </p>

          {featureOff && step.feature && (
            <div className="flex items-center gap-2 rounded-md border border-dashed p-2.5 text-[13px]">
              <span className="flex-1 text-muted-foreground">{t('guide.featureOff')}</span>
              <Button
                size="sm"
                variant="outline"
                onClick={() => save.mutate({ [step.feature!]: true }, { onSuccess: () => setTimeout(() => setRetry((r) => r + 1), 300) })}
                data-testid="guide-enable"
              >
                {t('guide.enable')}
              </Button>
            </div>
          )}

          {writes && (!card || card.status === 'pending') && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="guide-writing">
              <Spinner className="size-3.5" /> {t('guide.writing')}
            </p>
          )}
          {writes && card?.status === 'failed' && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              {t('guide.failed')}
              <button type="button" className="font-medium text-primary hover:underline" onClick={() => void actions.cards([id], true)}>
                {t('guide.retry')}
              </button>
            </p>
          )}
          {prompts.length > 0 && (
            <div className="grid gap-2">
              {prompts.map((p, i) => (
                <div key={i} className="grid gap-2 rounded-lg border bg-sunken p-3" data-testid="guide-prompt">
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 text-sm font-medium">{p.label}</span>
                    <Button size="sm" variant={i === 0 ? 'default' : 'outline'} onClick={() => tryPrompt(p)} data-guide-primary={i === 0 ? '' : undefined}>
                      {t('guide.try')} <ArrowRight />
                    </Button>
                  </div>
                  <p className="line-clamp-6 text-[13px] whitespace-pre-wrap text-muted-foreground">{p.text}</p>
                </div>
              ))}
              {state.level === 'beginner' && <p className="text-[13px] text-muted-foreground">{t('guide.tryHint')}</p>}
            </div>
          )}

          {id === 'final' && (
            <div className="flex flex-wrap gap-2">
              {tutorialHref && (
                <Button variant="outline" size="sm" onClick={() => (void actions.patch({ status: 'done', index: total, done: done(id) }), navigate(tutorialHref))}>
                  <GraduationCap /> {t('help.tutorial')}
                </Button>
              )}
              <Button variant="outline" size="sm" onClick={() => (void actions.patch({ status: 'done', index: total, done: done(id) }), navigate('/docs'))}>
                <BookOpen /> {t('nav.docs')}
              </Button>
            </div>
          )}

          <div className="flex items-center gap-2 pt-1">
            <Button variant="ghost" size="sm" onClick={pause} className="text-muted-foreground">
              <Pause /> {t('guide.pauseShort')}
            </Button>
            <div className="ml-auto flex gap-2">
              {index > 0 && (
                <Button variant="ghost" size="sm" onClick={() => go(-1)}>
                  {t('tour.back')}
                </Button>
              )}
              <Button size="sm" variant={prompts.length ? 'outline' : 'default'} onClick={() => go(1)} data-guide-primary={prompts.length ? undefined : ''} data-testid="guide-next">
                {last ? (
                  <>
                    <Check /> {t('guide.finish')}
                  </>
                ) : (
                  t('tour.next')
                )}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/** The app stays visible but inert around the lit part, which stays clickable (try the button it shows). */
function Shield({ hole }: { hole: Rect | null }) {
  const stop = (e: React.MouseEvent) => e.stopPropagation()
  if (!hole) return <div className="absolute inset-0" onClick={stop} aria-hidden />
  const parts: React.CSSProperties[] = [
    { left: 0, top: 0, right: 0, height: hole.y },
    { left: 0, top: hole.y + hole.h, right: 0, bottom: 0 },
    { left: 0, top: hole.y, width: hole.x, height: hole.h },
    { left: hole.x + hole.w, top: hole.y, right: 0, height: hole.h },
  ]
  return (
    <>
      {parts.map((s, i) => (
        <div key={i} className="absolute" style={s} onClick={stop} aria-hidden />
      ))}
    </>
  )
}

/* ------------------------------------------------------------------ paused: the pill on the right edge */

function GuideDock({ state }: { state: GuideState }) {
  const t = useT()
  const actions = useGuideActions()
  return (
    <div
      // the right edge, half-way down: the top holds the sessions' tabs, the bottom the message box
      className="fixed top-1/2 right-3 z-[60] flex -translate-y-1/2 items-center gap-1 rounded-full border bg-popover py-1 pr-1 pl-3 text-[13px] shadow-pop animate-in"

      data-testid="guide-dock"
    >
      <Compass className="size-3.5 shrink-0 text-primary" />
      <span className="px-1 whitespace-nowrap text-muted-foreground tabular-nums">{t('guide.dock', { n: state.index + 1, total: state.steps.length })}</span>
      <Button size="sm" className="h-7 rounded-full pointer-coarse:h-9" onClick={() => void actions.patch({ status: 'running' })} data-testid="guide-continue">
        {t('guide.continue')}
      </Button>
      <button
        type="button"
        aria-label={t('guide.later')}
        title={t('guide.later')}
        onClick={() => void actions.patch({ status: 'dismissed' })}
        className="flex size-7 items-center justify-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground pointer-coarse:size-9"
      >
        <X className="size-3.5" />
      </button>
    </div>
  )
}
