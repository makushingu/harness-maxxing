import * as React from 'react'
import { cn } from '@/lib/utils'
import { Card } from '@/components/ui'

/** A titled block inside a settings section. */
export function SettingsCard({ title, description, actions, children, className, danger }: { title?: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string; danger?: boolean }) {
  return (
    <Card className={cn('gap-0', danger && 'border-destructive/30', className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-3 px-[var(--pad-card)] pt-[var(--pad-card)]">
          <div className="grid gap-1">
            {title && <h3 className={cn('text-[15px] font-semibold tracking-tight', danger && 'text-destructive')}>{title}</h3>}
            {description && <p className="max-w-2xl text-[13px] text-muted-foreground">{description}</p>}
          </div>
          {actions && <div className="flex max-w-full flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className="p-[var(--pad-card)]">{children}</div>
    </Card>
  )
}

/** The cards of a section; they rise in one after the other when the section opens (`.mx-rise`, 28 ms apart, the last from the 5th). */
export function SectionStack({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-6">
      {React.Children.toArray(children).map((child, i) => (
        <div key={React.isValidElement(child) && child.key != null ? child.key : i} className="mx-rise min-w-0" style={{ '--i': Math.min(i, 4) } as React.CSSProperties}>
          {child}
        </div>
      ))}
    </div>
  )
}
