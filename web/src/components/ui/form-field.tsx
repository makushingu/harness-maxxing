import * as React from 'react'
import { cn } from '@/lib/utils'
import { Label } from './label'

type Props = {
  label?: React.ReactNode
  /** Help text under the control. */
  hint?: React.ReactNode
  /** Error message (replaces the hint, sets aria-invalid on the control). */
  error?: React.ReactNode
  /** Extra content right of the label (e.g. a link). */
  aside?: React.ReactNode
  className?: string
  /** A single control element; receives id, aria-describedby and aria-invalid. */
  children: React.ReactElement<Record<string, unknown>>
  id?: string
}

/** Label + control + hint/error with correct a11y wiring. Space for the message is reserved (no jump). */
export function FormField({ label, hint, error, aside, className, children, id }: Props) {
  const auto = React.useId()
  const cid = id || (children.props.id as string) || auto
  const msgId = `${cid}-msg`
  const control = React.cloneElement(children, {
    id: cid,
    'aria-describedby': hint || error ? msgId : undefined,
    'aria-invalid': error ? true : undefined,
  })
  return (
    <div className={cn('grid gap-2', className)}>
      {(label || aside) && (
        <div className="flex items-center justify-between gap-2">
          {label ? <Label htmlFor={cid}>{label}</Label> : <span />}
          {aside}
        </div>
      )}
      {control}
      {(hint || error) && (
        <p id={msgId} className={cn('text-[13px] leading-snug', error ? 'text-destructive' : 'text-muted-foreground')} role={error ? 'alert' : undefined}>
          {error || hint}
        </p>
      )}
    </div>
  )
}
