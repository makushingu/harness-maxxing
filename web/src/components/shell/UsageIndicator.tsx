import { useRef } from 'react'
import { Link } from 'react-router'
import { useUsage } from '@/lib/queries'
import { useIsMobile } from '@/stores/media'
import { fmtDate, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import type { UsageWindow } from '@/lib/types'
import { CalendarDays, ChevronRight, Clock } from 'lucide-react'
import { Sensitive, Tooltip } from '@/components/ui'
import { usePulseOnChange, useTween } from '@/lib/useTween'
import { MeterBar, MeterIcon, MeterValue, RingArc, toneText, type MeterTone } from './Meter'

/** The Claude plan usage rows (5-hour window, week) and their details; null when the server has no plan usage
 *  (API key, never read). `visible`: shown in the touch layout's menu (polls while it is open). */
export function usePlanUsage(visible?: boolean) {
  const t = useT()
  const lang = useLang()
  const desktop = !useIsMobile() || !!visible     // the sidebar is hidden in the touch layout: no polling for a bar nobody sees
  const { data: u } = useUsage(desktop, desktop)
  if (!u?.available) return null
  const rows = [
    { key: 'five', label: t('usage.fiveHour'), w: u.five_hour },
    { key: 'week', label: t('usage.week'), w: u.seven_day },
  ].filter((r): r is { key: string; label: string; w: UsageWindow & { pct: number } } => Number.isFinite(r.w?.pct)) // no percentage: no row (not "0 % used")
  if (!rows.length) return null
  const reset = (w: UsageWindow) =>
    w.resets_at ? t('usage.resets', { at: fmtDate(w.resets_at, lang, undefined, { dateStyle: undefined, timeStyle: undefined, weekday: 'short', hour: '2-digit', minute: '2-digit' }) }) : null
  const noFive = !u.five_hour && u.plan === 'Ultra' // verified Ultra accounts have no 5-hour window
  const title = u.plan ? t('usage.titlePlan', { plan: u.plan }) : t('usage.title')
  const details = (
    <div className="grid gap-1.5 text-xs">
      <span className="font-medium">{title}</span>
      {noFive && <span>{t('usage.noFiveHour')}</span>}
      {rows.map((r) => (
        <span key={r.key} className="tabular-nums">
          {r.label} · {t('usage.used', { pct: used(r.w) })}
          {reset(r.w) && <span className="opacity-70"> · {reset(r.w)}</span>}
        </span>
      ))}
      {u.source === 'turn' && u.seen_at && <span className="max-w-60 opacity-70">{t('usage.seen', { when: fmtRelative(u.seen_at, lang) })}</span>}
    </div>
  )
  return { rows, title, details, plan: u.plan || null }
}

const used = (w: { pct: number }) => Math.min(100, Math.max(0, Math.round(w.pct)))
const tone = (w: { pct: number }): MeterTone => (used(w) >= 90 ? 'error' : used(w) >= 70 ? 'warn' : undefined)
const rowIcon = (key: string) => (key === 'five' ? Clock : CalendarDays)

/** The plan figure of the sidebar's status line: the week when the server has it, else the 5-hour window; null
 *  without plan usage. */
export function usePlanPct(visible?: boolean): number | null {
  const p = usePlanUsage(visible)
  const r = p?.rows.find((x) => x.key === 'week') ?? p?.rows[0]
  return r ? used(r.w) : null
}

/** The plan in the status panel: a "Claude · Max  >" heading, then one line per window (icon, "5 h", "23 % used"
 *  counting to its new value) over a full-width bar; a link to Settings -> Stats (folded: the thin bars only).
 *  Bars glide and change colour smoothly (70 % warning, 90 % critical), the icon pops when the level changes. */
export function UsageLines({ collapsed, className, visible }: { collapsed?: boolean; className?: string; visible?: boolean }) {
  const t = useT()
  const p = usePlanUsage(visible)
  if (!p) return null
  return (
    <Tooltip content={collapsed ? p.details : null} side="right">
      <Link to="/settings/stats" className={cn('grid gap-2.5', className)} aria-label={p.title} data-testid="status-claude">
        {!collapsed && (
          <span className="flex items-center justify-between gap-2 text-xs font-medium text-muted-foreground">
            {p.plan ? `Claude · ${p.plan}` : 'Claude'} <ChevronRight className="size-3.5 shrink-0" />
          </span>
        )}
        {p.rows.map((r) =>
          collapsed ? (
            <MeterBar key={r.key} pct={used(r.w)} tone={tone(r.w)} label={r.label} className="h-1 w-8" />
          ) : (
            <span key={r.key} className="grid gap-1.5">
              <span className="flex items-center gap-2 text-xs leading-none text-muted-foreground">
                <MeterIcon icon={rowIcon(r.key)} tone={tone(r.w)} />
                <span className="min-w-0 flex-1 truncate">{r.label}</span>
                <MeterValue pct={used(r.w)} render={(n) => t('usage.used', { pct: n })} />
              </span>
              <MeterBar pct={used(r.w)} tone={tone(r.w)} label={r.label} />
            </span>
          ),
        )}
      </Link>
    </Tooltip>
  )
}

/** Plan usage as two small bars (the touch layout's menu). */
export function UsageIndicator({ collapsed, visible }: { collapsed?: boolean; visible?: boolean }) {
  const t = useT()
  const p = usePlanUsage(visible)
  if (!p) return null
  const { rows, title, details } = p
  return (
    <Tooltip content={details} side="right">
      <div className={cn('grid gap-1.5 px-2.5 py-1.5', collapsed && 'px-1')} aria-label={title}>
        {rows.map((r) =>
          collapsed ? (
            <MeterBar key={r.key} pct={used(r.w)} tone={tone(r.w)} label={r.label} className="h-1" />
          ) : (
            <div key={r.key} className="grid gap-1">
              <div className="flex justify-between text-[11px] leading-none text-muted-foreground">
                <span>Claude · {r.label}</span>
                <MeterValue pct={used(r.w)} className="text-inherit" render={(n) => t('usage.used', { pct: n })} />
              </div>
              <MeterBar pct={used(r.w)} tone={tone(r.w)} label={r.label} className="h-1" />
            </div>
          ),
        )}
      </div>
    </Tooltip>
  )
}

/** The ring's figures: the 5-hour window as the main ring (the week when there is no 5-hour window), the week as a
 *  thin inner ring when both exist; null without plan usage. */
export function useClaudeRing(visible?: boolean) {
  const p = usePlanUsage(visible)
  if (!p) return null
  const five = p.rows.find((r) => r.key === 'five')
  const week = p.rows.find((r) => r.key === 'week')
  const main = five ?? week!
  return { ...p, main: { label: main.label, pct: used(main.w), tone: tone(main.w) }, second: five && week ? { label: week.label, pct: used(week.w), tone: tone(week.w) } : null }
}

/** Claude plan usage as a ring: the main window's arc with its percentage counting in the centre, an optional thin
 *  inner arc (the week). Arcs glide (500 ms) and change colour smoothly (70 % warning, 90 % critical), the ring pops
 *  once when the main level changes; all instant under reduced motion. Presentational: see `useClaudeRing`. */
export function ClaudeRing({
  pct,
  tone: mainTone,
  second,
  size = 40,
  label,
  className,
}: {
  pct: number
  tone: MeterTone
  /** a thin inner ring (the week) */
  second?: { pct: number; tone: MeterTone } | null
  size?: number
  label?: string
  className?: string
}) {
  const ref = useRef<HTMLSpanElement>(null)
  usePulseOnChange(mainTone ?? 'ok', ref)
  const n = Math.round(useTween(pct))
  const w = Math.max(3, Math.round(size / 10)) // main arc: 4 px on a 40 px ring
  const r = size / 2 - w / 2
  const w2 = Math.max(1.5, w / 2)
  const r2 = r - w / 2 - 1.5 - w2 / 2
  return (
    <span ref={ref} role="img" aria-label={label} className={cn('relative inline-flex shrink-0 items-center justify-center', className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden className="absolute inset-0">
        <RingArc r={r} width={w} pct={pct} tone={mainTone} size={size} />
        {second && <RingArc r={r2} width={w2} pct={second.pct} tone={second.tone} size={size} />}
      </svg>
      <span
        aria-hidden
        className={cn('relative font-semibold tabular-nums leading-none transition-colors duration-[400ms] ease-out motion-reduce:transition-none', mainTone ? toneText(mainTone) : 'text-foreground')}
        style={{ fontSize: Math.round(size * 0.28) }}
      >
        <Sensitive length={2}>
          {n}
          <span className="text-[0.65em] font-medium">%</span>
        </Sensitive>
      </span>
    </span>
  )
}

/** The sidebar's Claude entry: the ring (folded bar: alone, centred), plus "Claude · Max" and "5 h 47 % · Semaine
 *  12 %" once the bar is unfolded; the plan details in a tooltip; a link to Settings -> Stats. Nothing without plan
 *  usage. The same link in both states, so the keyboard focus survives folding. */
export function ClaudeStatus({ collapsed }: { collapsed?: boolean }) {
  const lang = useLang()
  const c = useClaudeRing()
  if (!c) return null
  const pctText = (n: number) => (lang === 'en' ? `${n}%` : `${n} %`)
  const label = [c.title, ...c.rows.map((r) => `${r.label} ${pctText(used(r.w))}`)].join(' · ')
  return (
    <Tooltip content={c.details} side="right">
      <Link
        to="/settings/stats"
        aria-label={label}
        data-testid="status-claude"
        className={cn(
          'flex min-w-0 items-center gap-2.5 rounded-md px-1.5 py-1 outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring',
          collapsed && 'justify-center px-0',
        )}
      >
        <ClaudeRing pct={c.main.pct} tone={c.main.tone} second={c.second} size={collapsed ? 40 : 36} />
        {!collapsed && (
          <span className="grid min-w-0 flex-1 gap-0.5 leading-tight">
            <span className="truncate text-[13px] font-medium text-foreground">{c.plan ? `Claude · ${c.plan}` : 'Claude'}</span>
            <span className="truncate text-[11.5px] whitespace-nowrap text-muted-foreground">
              <Sensitive length={8}>
              {c.rows.map((r, i) => (
                <span key={r.key}>
                  {i > 0 && ' · '}
                  {r.label} <TweenPct pct={used(r.w)} tone={tone(r.w)} render={pctText} />
                </span>
              ))}
              </Sensitive>
            </span>
          </span>
        )}
      </Link>
    </Tooltip>
  )
}

function TweenPct({ pct, tone: tn, render }: { pct: number; tone: MeterTone; render: (n: number) => string }) {
  return <MeterValue pct={pct} tone={tn} render={render} className="font-medium" />
}
