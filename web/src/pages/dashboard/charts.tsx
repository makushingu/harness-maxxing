// Dependency-free SVG charts for dashboard "chart" blocks (bar / line).
// Specs: 2px lines, ~10% area wash, bars ≤ 24px with a rounded data end, hairline solid gridlines,
// legend only for ≥ 2 series, hover tooltip (keyboard: focus + arrows).
import * as React from 'react'
import { cn } from '@/lib/utils'
import { useLang } from '@/i18n'

export type Series = { name: string; points: [number | string, number][] }

function useWidth<T extends HTMLElement>() {
  const ref = React.useRef<T>(null)
  const [w, setW] = React.useState(0)
  React.useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setW(el.clientWidth)
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

function niceMax(v: number) {
  if (v <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(v))
  const n = v / p
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p
}

export function compact(v: number, lang: string) {
  return new Intl.NumberFormat(lang, { notation: Math.abs(v) >= 10000 ? 'compact' : 'standard', maximumFractionDigits: Math.abs(v) < 10 ? 2 : 1 }).format(v)
}

function fmtX(x: number | string, lang: string) {
  if (typeof x === 'number' && x > 1e9) return new Intl.DateTimeFormat(lang, { day: 'numeric', month: 'short' }).format(new Date(x * 1000))
  return String(x)
}

const COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)', 'var(--series-6)']

export function Chart({ kind, series, unit, height = 140 }: { kind: 'bar' | 'line'; series: Series[]; unit?: string; height?: number }) {
  const lang = useLang()
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = React.useState<number | null>(null)
  const id = React.useId().replace(/:/g, '')
  const xs = series[0]?.points.map((p) => p[0]) || []
  const n = xs.length
  const max = niceMax(Math.max(0, ...series.flatMap((s) => s.points.map((p) => p[1]))))
  const color = (i: number) => (series.length === 1 ? 'var(--primary)' : COLORS[i % COLORS.length])
  const padL = 34
  const padB = 18
  const padT = 6
  const W = Math.max(width, 10)
  const H = height
  const plotW = W - padL - 4
  const plotH = H - padB - padT
  const y = (v: number) => padT + plotH - (v / max) * plotH
  const band = n ? plotW / n : plotW
  const xc = (i: number) => padL + band * i + band / 2
  const xl = (i: number) => (n <= 1 ? padL + plotW / 2 : padL + (plotW * i) / (n - 1))
  const ticks = [0, max / 2, max]
  const labelEvery = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(plotW / 56))))
  const fmtV = (v: number) => `${compact(v, lang)}${unit ? ` ${unit}` : ''}`

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!n) return
    const r = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - r.left
    const i = kind === 'bar' ? Math.floor((px - padL) / band) : Math.round(((px - padL) / plotW) * (n - 1))
    setHover(Math.max(0, Math.min(n - 1, i)))
  }

  const hx = hover == null ? 0 : kind === 'bar' ? xc(hover) : xl(hover)
  return (
    <div className="grid gap-2">
      <div ref={ref} className="relative w-full" style={{ height: H }}>
        {width > 0 && n > 0 && (
          <svg
            width={W}
            height={H}
            className="block overflow-visible outline-none"
            role="img"
            aria-label={series.map((s) => `${s.name}: ${s.points.map((p) => `${fmtX(p[0], lang)} ${p[1]}`).join(', ')}`).join('; ')}
            tabIndex={0}
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
            onBlur={() => setHover(null)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight') setHover((h) => Math.min(n - 1, (h ?? -1) + 1))
              if (e.key === 'ArrowLeft') setHover((h) => Math.max(0, (h ?? n) - 1))
            }}
          >
            <defs>
              {series.map((_, si) => (
                <linearGradient key={si} id={`${id}-g${si}`} x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor={color(si)} stopOpacity="0.16" />
                  <stop offset="100%" stopColor={color(si)} stopOpacity="0.02" />
                </linearGradient>
              ))}
            </defs>
            {ticks.map((tk) => (
              <g key={tk}>
                <line x1={padL} x2={W - 4} y1={y(tk)} y2={y(tk)} stroke="var(--color-border)" strokeWidth={1} shapeRendering="crispEdges" />
                <text x={padL - 6} y={y(tk)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[10px] tabular-nums">
                  {compact(tk, lang)}
                </text>
              </g>
            ))}
            {xs.map((x, i) =>
              (i % labelEvery === 0 && n - 1 - i >= labelEvery) || i === n - 1 ? (
                <text key={i} x={kind === 'bar' ? xc(i) : xl(i)} y={H - 4} textAnchor={kind === 'line' && i === 0 ? 'start' : kind === 'line' && i === n - 1 ? 'end' : 'middle'} className="fill-muted-foreground text-[10px]">
                  {fmtX(x, lang)}
                </text>
              ) : null,
            )}
            {kind === 'bar'
              ? series.map((s, si) => {
                  const groupW = Math.min(band - 4, 24 * series.length + 2 * (series.length - 1))
                  const bw = Math.max(2, (groupW - 2 * (series.length - 1)) / series.length)
                  return s.points.map((p, i) => {
                    const x0 = xc(i) - groupW / 2 + si * (bw + 2)
                    const h = Math.max(0, y(0) - y(p[1]))
                    const r = Math.min(4, bw / 2, h)
                    return (
                      <path
                        key={`${si}-${i}`}
                        d={`M${x0},${y(0)} v${-(h - r)} q0,${-r} ${r},${-r} h${bw - 2 * r} q${r},0 ${r},${r} v${h - r} z`}
                        fill={color(si)}
                        opacity={hover == null || hover === i ? 1 : 0.45}
                        className="mx-grow-y transition-opacity"
                        style={{ '--i': Math.min(i, 16) } as React.CSSProperties}
                      />
                    )
                  })
                })
              : series.map((s, si) => {
                  const pts = s.points.map((p, i) => [xl(i), y(p[1])] as const)
                  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0]},${p[1]}`).join(' ')
                  const last = pts[pts.length - 1]
                  return (
                    <g key={si}>
                      {series.length === 1 && (
                        <path d={`${line} L${last[0]},${y(0)} L${pts[0][0]},${y(0)} Z`} fill={`url(#${id}-g${si})`} className="mx-fade [animation-delay:380ms] [animation-duration:420ms]" />
                      )}
                      {/* the line draws itself left to right, then its last point pops in */}
                      <path d={line} pathLength={1} fill="none" stroke={color(si)} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" className="mx-draw" />
                      <circle cx={last[0]} cy={last[1]} r={4} fill={color(si)} stroke="var(--color-card)" strokeWidth={2} className="mx-pop [animation-delay:720ms] [transform-box:fill-box] [transform-origin:center]" />
                      {hover != null && <circle cx={pts[hover][0]} cy={pts[hover][1]} r={4} fill={color(si)} stroke="var(--color-card)" strokeWidth={2} />}
                    </g>
                  )
                })}
            {hover != null && kind === 'line' && <line x1={hx} x2={hx} y1={padT} y2={y(0)} stroke="var(--color-muted-foreground)" strokeOpacity={0.35} strokeWidth={1} />}
          </svg>
        )}
        {hover != null && width > 0 && (
          <div
            className="pointer-events-none absolute top-0 z-10 rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-pop"
            style={{ left: Math.min(Math.max(hx - 70, 0), W - 140), minWidth: 120 }}
          >
            <div className="mb-1 font-medium">{fmtX(xs[hover], lang)}</div>
            {series.map((s, si) => (
              <div key={si} className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-1.5 text-muted-foreground">
                  <span className="size-2 rounded-full" style={{ background: color(si) }} />
                  {s.name}
                </span>
                <span className="font-medium tabular-nums">{fmtV(s.points[hover]?.[1] ?? 0)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      {series.length > 1 && (
        <ul className={cn('flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground')}>
          {series.map((s, si) => (
            <li key={s.name} className="flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: color(si) }} />
              {s.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
