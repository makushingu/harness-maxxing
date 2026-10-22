import { cn } from '@/lib/utils'

/** Placeholder with the exact footprint of the content it replaces (prevents layout shift). */
export function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return <div aria-hidden className={cn('animate-shimmer rounded-md bg-muted', className)} {...props} />
}

/** A few text-line skeletons. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn('grid gap-2', className)} aria-hidden>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className="h-3.5" style={{ width: `${i === lines - 1 ? 60 : 92 - i * 7}%` }} />
      ))}
    </div>
  )
}
