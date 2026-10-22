import { cn } from '@/lib/utils'

export type DotTone = 'ok' | 'warn' | 'error' | 'idle' | 'running' | 'info' | 'unread'

const tones: Record<DotTone, string> = {
  ok: 'bg-success',
  warn: 'bg-warning',
  error: 'bg-destructive',
  idle: 'bg-muted-foreground/50',
  running: 'bg-primary',
  info: 'bg-sky-500',
  unread: 'bg-success/70 ring-2 ring-success/25',
}

/** Small status indicator. `pulse` for live/running states. Always pair with a text label or aria-label. */
export function StatusDot({ tone = 'idle', pulse, className, label }: { tone?: DotTone; pulse?: boolean; className?: string; label?: string }) {
  return (
    <span className={cn('relative inline-flex size-2 shrink-0', className)} role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      {pulse && <span className={cn('absolute inline-flex size-full animate-ping rounded-full opacity-60', tones[tone])} />}
      <span className={cn('relative inline-flex size-full rounded-full', tones[tone])} />
    </span>
  )
}
