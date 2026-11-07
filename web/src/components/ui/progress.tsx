import { cn } from '@/lib/utils'

/** `grow`: the bar fills from 0 when it first shows (dashboard cards). */
export function ProgressBar({ value, max = 100, tone, className, label, grow }: { value: number; max?: number; tone?: 'ok' | 'warn' | 'error'; className?: string; label?: string; grow?: boolean }) {
  // an extension may send a missing or non-numeric value: an empty bar, never "NaN%"
  const v = Number.isFinite(Number(value)) ? Number(value) : 0
  const pct = Number(max) > 0 ? Math.max(0, Math.min(100, (v / Number(max)) * 100)) : 0
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={v}
      aria-label={label}
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-muted', className)}
    >
      <div
        className={cn('h-full rounded-full transition-[width] duration-500', grow && 'mx-sweep', tone === 'error' ? 'bg-destructive' : tone === 'warn' ? 'bg-warning' : tone === 'ok' ? 'bg-success' : 'bg-primary')}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}
