import * as React from 'react'
import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

/** Empty / error / "coming soon" block: icon, title, one sentence, optional call to action. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  tone = 'default',
  compact,
}: {
  icon?: LucideIcon
  title: React.ReactNode
  description?: React.ReactNode
  action?: React.ReactNode
  className?: string
  tone?: 'default' | 'error'
  compact?: boolean
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center text-center', compact ? 'gap-2 px-4 py-8' : 'gap-3 px-6 py-16', className)}>
      {Icon && (
        <div
          className={cn(
            'flex items-center justify-center rounded-xl border',
            compact ? 'size-10' : 'size-12',
            tone === 'error' ? 'border-destructive/30 bg-destructive/10 text-destructive' : 'bg-muted/60 text-muted-foreground',
          )}
        >
          <Icon className={compact ? 'size-5' : 'size-6'} strokeWidth={1.6} />
        </div>
      )}
      <div className="grid max-w-sm gap-1">
        <h3 className={cn('font-semibold tracking-tight', compact ? 'text-sm' : 'text-base')}>{title}</h3>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {action && <div className="mt-1 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  )
}
