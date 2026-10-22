// Small building blocks shared by onboarding steps and settings sections.
import * as React from 'react'
import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

type Tone = 'success' | 'error' | 'warning' | 'info'
const toneCls: Record<Tone, string> = {
  success: 'border-success/30 bg-success/8 [&>svg]:text-success',
  error: 'border-destructive/30 bg-destructive/8 [&>svg]:text-destructive',
  warning: 'border-warning/35 bg-warning/8 [&>svg]:text-warning',
  info: 'border-border bg-muted/40 [&>svg]:text-muted-foreground',
}
const toneIcon: Record<Tone, typeof Info> = { success: CheckCircle2, error: XCircle, warning: AlertTriangle, info: Info }

/** Inline callout (status, result of a test, explanation). */
export function Callout({ tone = 'info', title, children, className, action, icon }: { tone?: Tone; title?: React.ReactNode; children?: React.ReactNode; className?: string; action?: React.ReactNode; icon?: typeof Info }) {
  const Icon = icon || toneIcon[tone]
  return (
    <div role={tone === 'error' ? 'alert' : undefined} className={cn('flex flex-wrap gap-3 rounded-lg border p-3.5 text-sm', toneCls[tone], className)}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="grid min-w-0 flex-[1_1_12rem] gap-1">
        {title && <div className="font-medium">{title}</div>}
        {children && <div className="text-[13px] text-muted-foreground [&_strong]:text-foreground">{children}</div>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  )
}

/** Numbered instruction list (BotFather steps, token creation…). */
export function Steps({ items, className }: { items: React.ReactNode[]; className?: string }) {
  return (
    <ol className={cn('grid gap-3', className)}>
      {items.map((it, i) => (
        <li key={i} className="flex gap-3 text-sm">
          <span className="flex size-6 shrink-0 items-center justify-center rounded-full border bg-muted text-xs font-semibold tabular-nums">{i + 1}</span>
          <div className="min-w-0 flex-1 pt-0.5 [&_a]:font-medium [&_a]:text-primary [&_a]:underline-offset-2 hover:[&_a]:underline">{it}</div>
        </li>
      ))}
    </ol>
  )
}

/** Selectable card used as a radio option (permission mode, auth kind…). */
export function OptionCard({
  selected,
  onSelect,
  title,
  description,
  badge,
  icon: Icon,
  name,
  value,
}: {
  selected: boolean
  onSelect: () => void
  title: React.ReactNode
  description?: React.ReactNode
  badge?: React.ReactNode
  icon?: typeof Info
  name: string
  value: string
}) {
  return (
    <label
      className={cn(
        'relative flex cursor-pointer gap-3 rounded-lg border p-3.5 transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring',
        selected ? 'border-primary/60 bg-primary/5' : 'hover:bg-accent/50',
      )}
    >
      <input type="radio" name={name} value={value} checked={selected} onChange={onSelect} className="sr-only" />
      <span className={cn('mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border', selected ? 'border-primary' : 'border-input')}>
        {selected && <span className="size-2 rounded-full bg-primary" />}
      </span>
      <span className="grid min-w-0 flex-1 gap-1">
        <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
          {Icon && <Icon className="size-4 text-muted-foreground" />}
          {title}
          {badge}
        </span>
        {description && <span className="text-[13px] text-muted-foreground">{description}</span>}
      </span>
    </label>
  )
}

/** A row in a settings list: label + description on the left, control on the right. */
export function SettingRow({ label, description, children, htmlFor, className }: { label: React.ReactNode; description?: React.ReactNode; children: React.ReactNode; htmlFor?: string; className?: string }) {
  return (
    <div className={cn('flex flex-wrap items-center justify-between gap-x-6 gap-y-3 py-4 first:pt-0 last:pb-0', className)}>
      <div className="grid min-w-[min(100%,14rem)] flex-1 gap-0.5">
        <label htmlFor={htmlFor} className="text-sm font-medium">
          {label}
        </label>
        {description && <p className="text-[13px] text-muted-foreground">{description}</p>}
      </div>
      <div className="flex max-w-full shrink-0 items-center gap-2">{children}</div>
    </div>
  )
}
