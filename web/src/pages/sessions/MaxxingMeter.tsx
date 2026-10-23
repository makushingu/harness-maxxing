// Maxxing mode controls: the switch, the queue of finished sessions ("next", "back"), and the meter - a bar of
// liquid, always gently moving, from green to orange as the user and the sessions keep each other busy; it overflows
// its track (up to 110 %) past 100 %.
import * as React from 'react'
import { SkipBack, SkipForward, Zap } from 'lucide-react'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import { Button, Tooltip } from '@/components/ui'
import { useMaxxing } from './maxxing'
import { score as readScore, SCORE_MAX, type MaxxingScore } from './maxxingStats'

function useScore(on: boolean) {
  const [s, setS] = React.useState<MaxxingScore>(() => readScore())
  React.useEffect(() => {
    if (!on) return
    setS(readScore())
    const iv = window.setInterval(() => setS(readScore()), 1_000)
    return () => window.clearInterval(iv)
  }, [on])
  return s
}

const fmtDelay = (ms: number) => (ms < 60_000 ? `${Math.round(ms / 1000)} s` : `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`)

/** The liquid meter. `strip`: a thin bar along the bottom edge of the phone's session header (110 % = full width). */
export function MaxxingMeter({ strip }: { strip?: boolean }) {
  const t = useT()
  const on = useMaxxing((s) => s.on)
  const s = useScore(on)
  if (!on) return null
  const pct = Math.round(s.score * 100)
  const hot = s.score >= 0.6
  const over = s.score > 1
  if (strip)
    return (
      <div className={'mx-meter-strip pointer-events-none absolute inset-x-0 -bottom-px h-1'} role="meter" aria-label={t('maxxing.meter.title')} aria-valuemin={0} aria-valuemax={Math.round(SCORE_MAX * 100)} aria-valuenow={pct} data-testid="maxxing-meter">
        <div className="absolute inset-y-0 left-0 transition-[width] duration-700 ease-out" style={{ width: `${(s.score / SCORE_MAX) * 100}%` }}>
          <div className="mx-meter-fill absolute inset-0 overflow-hidden rounded-r-full">
            <div className="mx-liquid absolute inset-y-0 left-0" style={{ width: `${(SCORE_MAX / Math.max(s.score, 0.01)) * 100}%` }} />
          </div>
        </div>
      </div>
    )
  const tip = (
    <span className="block space-y-0.5 text-left">
      <span className="block font-semibold">{over ? t('maxxing.meter.overdrive') : t('maxxing.meter.title')} · {pct} %</span>
      <span className="block">{t('maxxing.meter.utilisation')} : {s.utilisation === null ? '-' : `${Math.round(s.utilisation * 100)} %`}</span>
      <span className="block">{t('maxxing.meter.delay')} : {s.delay === null ? '-' : fmtDelay(s.delay)}</span>
      <span className="block">{t('maxxing.meter.answered')} : {s.answered}</span>
      <span className="block max-w-64 whitespace-normal text-muted-foreground">{t('maxxing.meter.hint')}</span>
    </span>
  )
  return (
    <Tooltip content={tip}>
      <div
        tabIndex={0}
        role="meter"
        aria-label={t('maxxing.meter.title')}
        aria-valuemin={0}
        aria-valuemax={Math.round(SCORE_MAX * 100)}
        aria-valuenow={pct}
        data-testid="maxxing-meter"
        className="mr-4 flex shrink-0 items-center gap-2 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div className={'relative h-2.5 w-32 rounded-full bg-muted'}>
          {/* the fill: its liquid is laid on the full track (110 %), so the colour says how far it went */}
          <div className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-700 ease-out" style={{ width: `${s.score * 100}%` }}>
              <div className="mx-meter-fill absolute inset-0 overflow-hidden rounded-full">
              <div className="mx-liquid absolute inset-y-0 left-0" style={{ width: `${(SCORE_MAX / Math.max(s.score, 0.01)) * 100}%` }} />
            </div>
          </div>
        </div>
        <span className={cn('ml-3 min-w-9 text-right text-xs font-semibold tabular-nums', over ? 'text-orange-500' : hot ? 'text-amber-500' : 'text-muted-foreground')}>{pct} %</span>
      </div>
    </Tooltip>
  )
}

/** The switch (Alt+M), then - when on - the queue of finished sessions and "next". */
export function MaxxingControls({ compact }: { compact?: boolean }) {
  const t = useT()
  const on = useMaxxing((s) => s.on)
  const queued = useMaxxing((s) => s.queue.length)
  const current = useMaxxing((s) => s.current)
  const setOn = useMaxxing((s) => s.setOn)
  const skip = useMaxxing((s) => s.skip)
  const back = useMaxxing((s) => s.back)
  const canBack = useMaxxing((s) => s.history.length > 0)
  return (
    <div className="flex items-center">
      {on && !compact && <MaxxingMeter />}
      {on && (
        <Tooltip content={t('maxxing.backTip')}>
          <Button variant="ghost" size={compact ? 'icon-sm' : 'sm'} onClick={back} disabled={!canBack} aria-label={t('maxxing.back')} data-testid="maxxing-back">
            <SkipBack />
          </Button>
        </Tooltip>
      )}
      {on && (queued > 0 || current) && (
        <Tooltip content={t('maxxing.next')}>
          <Button variant="ghost" size={compact ? 'icon-sm' : 'sm'} onClick={skip} disabled={!queued} aria-label={t('maxxing.next')} data-testid="maxxing-next" className="relative tabular-nums">
            <SkipForward />
            {queued > 0 && <span className={cn('rounded-full bg-primary px-1.5 text-[11px] leading-4 font-semibold text-primary-foreground', compact && 'absolute -top-0.5 -right-0.5')}>{queued}</span>}
            {!compact && <span className="max-lg:hidden">{t('maxxing.waiting', { n: queued })}</span>}
          </Button>
        </Tooltip>
      )}
      <Tooltip content={`${on ? t('maxxing.off') : t('maxxing.on')} (Alt+M)`}>
        <Button
          variant="ghost"
          size={compact ? 'icon-sm' : 'sm'}
          aria-pressed={on}
          aria-label={t('maxxing.toggle')}
          onClick={() => setOn(!on)}
          data-testid="maxxing-toggle"
          className={cn(on && 'bg-primary/12 text-primary hover:bg-primary/20 hover:text-primary')}
        >
          <Zap className={cn(on && 'fill-current')} /> {!compact && <span className="max-md:hidden">{t('maxxing.toggle')}</span>}
        </Button>
      </Tooltip>
    </div>
  )
}
