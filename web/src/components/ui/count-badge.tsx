import * as React from 'react'
import { cn } from '@/lib/utils'
import { reducedMotion } from '@/lib/presence'
import { useUI } from '@/stores/ui'

const BADGE_MS = 180

/** Pops in when it appears, shrinks and fades out when it reaches 0 (Web Animations: no clash with the pulse). */
function useBadgeMotion(count: number) {
  const ref = React.useRef<HTMLSpanElement>(null)
  // Last positive count: still shown while the badge animates out.
  const [shown, setShown] = React.useState(count)
  const [leaving, setLeaving] = React.useState(false)
  const appeared = React.useRef(count > 0)
  if (count > 0 && (shown !== count || leaving)) {
    setShown(count)
    setLeaving(false)
  }
  if (count <= 0 && shown > 0 && !leaving) setLeaving(true)

  React.useLayoutEffect(() => {
    const el = ref.current
    if (!el || reducedMotion()) return
    if (shown > 0 && !leaving && !appeared.current) {
      el.animate([{ opacity: 0, transform: 'scale(0.6)' }, { opacity: 1, transform: 'none' }], { duration: BADGE_MS, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' })
    }
    appeared.current = shown > 0 && !leaving
  }, [shown, leaving])

  React.useEffect(() => {
    if (!leaving) return
    const el = ref.current
    if (!el || reducedMotion()) {
      setShown(0)
      setLeaving(false)
      return
    }
    const a = el.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'scale(0.6)' }], { duration: BADGE_MS, easing: 'cubic-bezier(0.4, 0, 1, 1)', fill: 'forwards' })
    a.onfinish = () => {
      setShown(0)
      setLeaving(false)
    }
    return () => a.cancel()
  }, [leaving])

  return { ref, shown, leaving }
}

/** Round counter (unread answers, running turns). Pulses when Settings -> Notifications -> "Pulsing badge" is on. */
export function CountBadge({ count, tone = 'unread', className, title }: { count: number; tone?: 'unread' | 'running'; className?: string; title?: string }) {
  const pulse = useUI((s) => s.badgePulse) && tone === 'unread'
  const { ref, shown, leaving } = useBadgeMotion(count)
  if (shown <= 0) return null
  return (
    <span
      ref={ref}
      title={leaving ? undefined : title}
      aria-hidden={leaving || undefined}
      className={cn(
        'inline-flex h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded-full px-1 text-[11px] leading-none font-semibold tabular-nums',
        // Finished (unread): green, see-through, with a fine ring; running: the theme color, see-through.
        tone === 'unread' ? 'bg-success/15 text-success ring-1 ring-success/40 ring-inset' : 'bg-primary/15 text-primary',
        pulse && !leaving && 'mx-badge-pulse',
        leaving && 'pointer-events-none',
        className,
      )}
    >
      {shown > 99 ? '99+' : shown}
    </span>
  )
}

/** Round dot version (collapsed sidebar, tab bar icons). */
export function CountDot({ tone = 'unread', className }: { tone?: 'unread' | 'running'; className?: string }) {
  const pulse = useUI((s) => s.badgePulse) && tone === 'unread'
  return <span aria-hidden className={cn('size-2 rounded-full', tone === 'unread' ? 'bg-success/70 ring-2 ring-success/25' : 'bg-primary', pulse && 'mx-badge-pulse', className)} />
}
