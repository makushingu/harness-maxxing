import { useRef, type ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePulseOnChange, useTween } from '@/lib/useTween'

/** A meter's level: under the warning threshold, warning, critical. */
export type MeterTone = 'warn' | 'error' | undefined

/** Colour changes fade (400 ms); the width glides (500 ms ease-out); both instant under reduced motion. */
const fade = 'transition-colors duration-[400ms] ease-out motion-reduce:transition-none'
const barMotion = 'transition-[width,background-color] duration-500 ease-out motion-reduce:transition-none'

export const toneText = (tone: MeterTone) => (tone === 'error' ? 'text-destructive' : tone === 'warn' ? 'text-warning' : 'text-muted-foreground')
const toneBg = (tone: MeterTone) => (tone === 'error' ? 'bg-destructive' : tone === 'warn' ? 'bg-warning' : 'bg-primary')

/** A thin bar whose width and colour move smoothly when the value changes. */
export function MeterBar({ pct, tone, label, className }: { pct: number; tone: MeterTone; label?: string; className?: string }) {
  const v = Number.isFinite(pct) ? Math.max(0, Math.min(100, pct)) : 0
  return (
    <span
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(v)}
      aria-label={label}
      className={cn('block h-1.5 w-full overflow-hidden rounded-full bg-muted', className)}
    >
      <span className={cn('block h-full rounded-full', barMotion, toneBg(tone))} style={{ width: `${v}%` }} />
    </span>
  )
}

/** The line's icon: takes the meter's colour (fading) and pops once when the level changes. */
export function MeterIcon({ icon: Icon, tone, className }: { icon: LucideIcon; tone: MeterTone; className?: string }) {
  const ref = useRef<SVGSVGElement>(null)
  usePulseOnChange(tone ?? 'ok', ref)
  return <Icon ref={ref} aria-hidden className={cn('size-3.5 shrink-0', fade, toneText(tone), className)} />
}

/** A percentage that counts up / down to its new value (tabular figures: no width jitter). `render` formats the
 *  rounded number ("47 %", "47 % used"). */
export function MeterValue({ pct, tone, render, className }: { pct: number; tone?: MeterTone; render?: (n: number) => ReactNode; className?: string }) {
  const n = Math.round(useTween(pct))
  return <span className={cn('tabular-nums', fade, tone ? toneText(tone) : 'text-foreground', className)}>{render ? render(n) : `${n}%`}</span>
}

const toneStroke = (tone: MeterTone) => (tone === 'error' ? 'stroke-destructive' : tone === 'warn' ? 'stroke-warning' : 'stroke-primary')

/** One arc of a ring meter (`pathLength` 100: the dash is the percentage), drawn clockwise from 12 o'clock. */
export function RingArc({ r, width, pct, tone, size }: { r: number; width: number; pct: number; tone: MeterTone; size: number }) {
  const v = Number.isFinite(pct) ? Math.max(0, Math.min(100, pct)) : 0
  const c = size / 2
  return (
    <>
      <circle cx={c} cy={c} r={r} fill="none" strokeWidth={width} className="stroke-muted" />
      <circle
        cx={c}
        cy={c}
        r={r}
        fill="none"
        strokeWidth={width}
        strokeLinecap="round"
        pathLength={100}
        // a round cap on a 0 % arc still draws a dot: no dash at all then
        strokeDasharray={v > 0.5 ? `${v} 100` : '0 100'}
        transform={`rotate(-90 ${c} ${c})`}
        className={cn('mx-arc', toneStroke(tone))} // .mx-arc (globals.css): length glides 500 ms, colour fades 400 ms
      />
    </>
  )
}

/** The folded bar's tiny meter: icon (colour fading with the level) over / beside a short thin bar. */
export function MiniMeter({ icon, pct, tone, label, className }: { icon: LucideIcon; pct: number; tone: MeterTone; label: string; className?: string }) {
  return (
    <span className={cn('flex items-center gap-1', className)}>
      <MeterIcon icon={icon} tone={tone} className="size-3" />
      <MeterBar pct={pct} tone={tone} label={label} className="h-[3px] w-5 bg-muted-foreground/15" />
    </span>
  )
}
