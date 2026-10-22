// Renders API.md Card blocks with native components. Every user value goes through <Sensitive>.
import * as React from 'react'
import { Link } from 'react-router'
import { ArrowDownRight, ArrowUpRight, ChevronRight } from 'lucide-react'
import type { Block, StatBlock, TimelineBlock, Tone } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useLang } from '@/i18n'
import { NamedIcon, ProgressBar, Sensitive, Skeleton, StatusDot } from '@/components/ui'
import { reducedMotion } from '@/lib/presence'
import { Chart, compact } from './charts'

const Markdown = React.lazy(() => import('@/components/ui/markdown').then((m) => ({ default: m.Markdown })))

const toneText: Record<Tone, string> = { ok: 'text-success', warn: 'text-warning', error: 'text-destructive' }

function fmtValue(v: string | number, lang: string) {
  return typeof v === 'number' ? compact(v, lang) : v
}

/** A number that glides to its value: from 0 when it first shows, from the old value when it changes (ease-out,
 *  ~0.6 s; only the text changes, nothing is laid out again). Strings and reduced motion show the value at once. */
/** False while the card is below the fold and has not been seen yet (its animations wait, see index.tsx). */
export const InView = React.createContext(true)

function useCountUp(value: string | number, ms = 600): string | number {
  const inView = React.useContext(InView)
  const [shown, setShown] = React.useState<string | number>(() => (typeof value === 'number' && !reducedMotion() ? 0 : value))
  const from = React.useRef(typeof value === 'number' ? 0 : null)
  React.useEffect(() => {
    if (typeof value !== 'number' || reducedMotion()) {
      setShown(value)
      return
    }
    if (!inView) return                       // keeps 0 until the card is seen, then counts up
    const start = typeof from.current === 'number' ? from.current : value
    if (start === value) {
      setShown(value)
      return
    }
    const int = Number.isInteger(value) && Number.isInteger(start)
    const t0 = performance.now()
    let raf = 0
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / ms)
      const v = start + (value - start) * (1 - Math.pow(1 - k, 3))
      from.current = v
      setShown(k < 1 ? (int ? Math.round(v) : v) : value)
      if (k < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [value, ms, inView])
  return shown
}

/** Rows of a list / tiles of a grid: they rise in one after the other when they first show (28 ms apart). */
const rise = (i: number) => ({ className: 'mx-rise', style: { '--i': Math.min(i, 10) } as React.CSSProperties })

/** Internal links stay in the SPA; external ones open in a new tab. */
export function SmartLink({ href, className, children }: { href: string; className?: string; children: React.ReactNode }) {
  if (href.startsWith('/') && !href.startsWith('//'))
    return (
      <Link to={href} className={className}>
        {children}
      </Link>
    )
  if (!/^https?:/i.test(href)) return <span className={className}>{children}</span>
  return (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className={className}>
      {children}
    </a>
  )
}

function Delta({ delta }: { delta: string | number }) {
  const s = String(delta)
  const neg = s.trim().startsWith('-') || s.trim().startsWith('−')
  const pos = /^\+|^\d/.test(s.trim()) && !neg && s.trim() !== '0'
  const Icon = neg ? ArrowDownRight : ArrowUpRight
  return (
    <span className={cn('inline-flex items-center gap-0.5 text-xs font-medium', neg ? 'text-destructive' : pos ? 'text-success' : 'text-muted-foreground')}>
      {(neg || pos) && <Icon className="size-3.5" />}
      <Sensitive length={3}>{s}</Sensitive>
    </span>
  )
}

function Stat({ b, size = 'lg' }: { b: Omit<StatBlock, 'type'>; size?: 'lg' | 'md' }) {
  const lang = useLang()
  const value = useCountUp(b.value)
  return (
    <div className="grid min-w-0 gap-1">
      <span className="truncate text-[13px] text-muted-foreground">{b.label}</span>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className={cn('min-w-0 truncate font-semibold tracking-tight', size === 'lg' ? 'text-[28px] leading-9' : 'text-xl leading-7', b.tone && toneText[b.tone])}>
          <Sensitive length={4}>{fmtValue(value, lang)}</Sensitive>
        </span>
        {b.delta != null && b.delta !== '' && <Delta delta={b.delta} />}
      </div>
      {b.hint && <span className="truncate text-xs text-muted-foreground">{b.hint}</span>}
    </div>
  )
}

const pct = (at: number, b: TimelineBlock) => Math.min(100, Math.max(0, ((at - b.start) / (b.end - b.start)) * 100))

function axisLabel(at: number, span: number, lang: string) {
  const d = new Date(at * 1000)
  return span > 2 * 86400
    ? d.toLocaleDateString(lang, { day: 'numeric', month: 'short' })
    : d.toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
}

const laneGrid = 'grid grid-cols-[minmax(0,7.5rem)_1fr] gap-3 sm:grid-cols-[minmax(0,10rem)_1fr]'

/** One lane per row on a start..end axis (a 24 h span is labelled 00:00..24:00 from `start`, so the
 *  server's time zone wins over the browser's): filled dots = done (green ok / red failed), hollow = planned,
 *  pulsing = running, a glowing line = now. Dense lanes (too many runs to tell apart) draw a band. */
function Timeline({ b }: { b: TimelineBlock }) {
  const lang = useLang()
  const span = b.end - b.start
  if (!(span > 0)) return null
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => b.start + f * span)
  const now = b.now != null && b.now >= b.start && b.now <= b.end ? pct(b.now, b) : null
  return (
    <div className="grid gap-1.5">
      <div className="relative grid gap-1">
        {b.lanes.map((lane, i) => {
          const color = lane.color || 'var(--color-primary)'
          const shown = lane.dense ? lane.events.filter((e) => e.state === 'error' || e.state === 'running') : lane.events
          const name = (
            <span className="block truncate text-[13px] font-medium text-foreground/90">
              <Sensitive length={8}>{lane.name}</Sensitive>
            </span>
          )
          return (
            <div key={i} className={cn(laneGrid, 'mx-rise items-center')} style={{ '--i': Math.min(i, 10) } as React.CSSProperties}>
              <div className="min-w-0" title={lane.sub}>
                {lane.href ? (
                  <SmartLink href={lane.href} className="hover:underline">
                    {name}
                  </SmartLink>
                ) : (
                  name
                )}
                {lane.sub && <span className="block truncate text-[11px] text-muted-foreground">{lane.sub}</span>}
              </div>
              <div className="relative h-7 rounded-md bg-muted/40">
                <div
                  className="mx-sweep absolute inset-x-1 top-1/2 h-px -translate-y-1/2"
                  style={{ background: `color-mix(in oklab, ${color} 35%, transparent)`, '--i': Math.min(i, 10) } as React.CSSProperties}
                />
                {lane.dense && (
                  <div
                    className="mx-sweep absolute inset-x-0 inset-y-2.5 rounded-full"
                    style={{
                      '--i': Math.min(i, 10),
                      background: `repeating-linear-gradient(90deg, color-mix(in oklab, ${color} 60%, transparent) 0 2px, transparent 2px 6px)`,
                    } as React.CSSProperties}
                  />
                )}
                {shown.map((e, j) => {
                  const st = e.state || 'ok'
                  const tone = st === 'error' ? 'var(--color-destructive)' : st === 'ok' ? 'var(--color-success)' : color
                  return (
                    <span
                      key={j}
                      title={e.label || axisLabel(e.at, span, lang)}
                      className="mx-dot-in absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
                      style={{
                        '--i': Math.min(i, 10),
                        '--x': Math.round(pct(e.at, b)),
                        left: `${pct(e.at, b)}%`,
                        background: st === 'planned' ? 'var(--color-card)' : tone,
                        border: `2px solid ${tone}`,
                        boxShadow: st === 'planned' ? undefined : `0 0 8px color-mix(in oklab, ${tone} 60%, transparent)`,
                      } as React.CSSProperties}
                    >
                      {st === 'running' && (
                        <span className="absolute inset-0 rounded-full" style={{ background: tone, animation: 'mx-ping 1.4s ease-out infinite' }} />
                      )}
                    </span>
                  )
                })}
              </div>
            </div>
          )
        })}
        {now != null && (
          <div className={cn(laneGrid, 'mx-fade pointer-events-none absolute inset-0 [animation-delay:500ms]')}>
            <div />
            <div className="relative">
              <div
                className="absolute -inset-y-1 w-0.5 -translate-x-1/2 rounded-full bg-primary"
                style={{ left: `${now}%`, boxShadow: '0 0 10px var(--color-primary), 0 0 2px var(--color-primary)' }}
              />
            </div>
          </div>
        )}
      </div>
      <div className={laneGrid}>
        <span className="truncate text-[11px] text-muted-foreground">{b.more || ''}</span>
        <div className="relative h-4 text-[11px] tabular-nums text-muted-foreground">
          {ticks.map((at, i) => {
            const last = i === ticks.length - 1
            return (
              <span
                key={i}
                className={cn('absolute', i === 0 ? 'left-0' : last ? 'right-0' : '-translate-x-1/2', i % 2 === 1 && 'hidden sm:inline')}
                style={i === 0 || last ? undefined : { left: `${(i / (ticks.length - 1)) * 100}%` }}
              >
                {span === 86400 ? `${String(i * 6).padStart(2, '0')}:00` : axisLabel(at, span, lang)}
              </span>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export function BlockView({ block }: { block: Block }) {
  const lang = useLang()
  switch (block.type) {
    case 'stat':
      return <Stat b={block} />
    case 'stats':
      return (
        <div className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-[repeat(auto-fit,minmax(110px,1fr))]">
          {block.items.map((it, i) => (
            <Stat key={i} b={it} size="md" />
          ))}
        </div>
      )
    case 'list':
      if (!block.items.length) return <p className="py-2 text-sm text-muted-foreground">{block.empty || '—'}</p>
      if (block.grid)
        return (
          // sized by the card (container query), not the window: 1 tile per row in a narrow card, up to 3 in a wide one
          <div className="@container">
          <ul className="grid gap-2.5 @2xl:grid-cols-2 @4xl:grid-cols-3">
            {block.items.map((it, i) => {
              const inner = (
                <>
                  {it.icon ? (
                    <span aria-hidden className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <NamedIcon name={it.icon} />
                    </span>
                  ) : it.emoji ? (
                    <span aria-hidden className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-lg">
                      {it.emoji}
                    </span>
                  ) : null}
                  <span className="grid min-w-0 flex-1 gap-0.5">
                    <span className="line-clamp-2 text-sm font-medium">
                      <Sensitive length={10}>{it.title}</Sensitive>
                    </span>
                    {it.subtitle && (
                      <span className="line-clamp-2 text-xs leading-snug text-muted-foreground">
                        <Sensitive length={8}>{it.subtitle}</Sensitive>
                      </span>
                    )}
                  </span>
                  {it.value != null && (
                    <span className="shrink-0 text-sm font-medium tabular-nums">
                      <Sensitive length={3}>{fmtValue(it.value, lang)}</Sensitive>
                    </span>
                  )}
                </>
              )
              const cls = 'group flex h-full items-center gap-3 rounded-lg border bg-background/40 px-3 py-2.5'
              return (
                <li key={i} {...rise(i)}>
                  {it.href ? (
                    <SmartLink href={it.href} className={cn(cls, 'outline-none transition-colors hover:border-primary/50 hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring')}>
                      {inner}
                    </SmartLink>
                  ) : (
                    <div className={cls}>{inner}</div>
                  )}
                </li>
              )
            })}
          </ul>
          </div>
        )
      return (
        <ul className="-mx-2 grid">
          {block.items.map((it, i) => {
            const inner = (
              <>
                {it.status && <StatusDot tone={it.status} className="mt-[7px] self-start" />}
                {it.icon ? (
                  <NamedIcon name={it.icon} className="mt-0.5 shrink-0 self-start text-muted-foreground" />
                ) : it.emoji ? (
                  <span aria-hidden className="w-5 shrink-0 text-center">{it.emoji}</span>
                ) : null}
                <span className="grid min-w-0 flex-1">
                  <span className="truncate text-sm">
                    <Sensitive length={10}>{it.title}</Sensitive>
                  </span>
                  {it.subtitle && (
                    <span className="truncate text-xs text-muted-foreground">
                      <Sensitive length={8}>{it.subtitle}</Sensitive>
                    </span>
                  )}
                </span>
                {it.value != null && (
                  <span className="shrink-0 text-sm font-medium tabular-nums">
                    <Sensitive length={3}>{fmtValue(it.value, lang)}</Sensitive>
                  </span>
                )}
                {it.href && <ChevronRight className="size-4 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-100" />}
              </>
            )
            const cls = 'group flex min-h-10 items-center gap-2.5 rounded-md px-2 py-1.5'
            return (
              <li key={i} {...rise(i)}>
                {it.href ? (
                  <SmartLink href={it.href} className={cn(cls, 'outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring')}>
                    {inner}
                  </SmartLink>
                ) : (
                  <div className={cls}>{inner}</div>
                )}
              </li>
            )
          })}
        </ul>
      )
    case 'chart':
      return (
        <Sensitive placeholder={<div className="h-[140px] rounded-lg bg-muted/50" />}>
          <Chart kind={block.kind} series={block.series} unit={block.unit} />
        </Sensitive>
      )
    case 'table':
      return (
        <div className="-mx-1 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                {block.columns.map((c, i) => (
                  <th key={i} className={cn('px-1 py-1.5 font-medium', i > 0 && 'text-right')}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((r, ri) => (
                <tr key={ri} className="mx-rise border-b last:border-0" style={{ '--i': Math.min(ri, 10) } as React.CSSProperties}>
                  {r.map((cell, ci) => (
                    <td key={ci} className={cn('px-1 py-2', ci > 0 && 'text-right tabular-nums')}>
                      <Sensitive length={4}>{cell == null ? '—' : typeof cell === 'number' ? fmtValue(cell, lang) : cell}</Sensitive>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    case 'progress': {
      const pct = block.max ? (block.value / block.max) * 100 : 0
      return (
        <div className="grid gap-1.5">
          <div className="flex justify-between gap-3 text-sm">
            <span className="truncate text-muted-foreground">{block.label}</span>
            <span className="font-medium tabular-nums">
              <Sensitive length={5}>
                {block.format === 'percent'
                  ? `${new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(pct)} %`
                  : `${compact(block.value, lang)} / ${compact(block.max, lang)}${block.unit ? ` ${block.unit}` : ''}`}
              </Sensitive>
            </span>
          </div>
          <ProgressBar value={block.value} max={block.max} tone={pct >= 90 ? 'error' : pct >= 75 ? 'warn' : undefined} label={block.label} grow />
          {block.hint && <span className="text-xs text-muted-foreground">{block.hint}</span>}
        </div>
      )
    }
    case 'markdown':
      return (
        <Sensitive block>
          <React.Suspense fallback={<Skeleton className="h-10" />}>
            <Markdown className="text-[13px]">{block.text}</Markdown>
          </React.Suspense>
        </Sensitive>
      )
    case 'timeline':
      return <Timeline b={block} />
    default:
      return null
  }
}
