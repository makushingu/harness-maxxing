import * as React from 'react'
import { cn } from '@/lib/utils'

/** Segmented control (radio group look-alike) for 2-5 exclusive options. Keyboard: arrows. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  className,
  'aria-label': ariaLabel,
  size = 'default',
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: React.ReactNode; icon?: React.ReactNode }[]
  className?: string
  'aria-label'?: string
  size?: 'default' | 'sm'
}) {
  const refs = React.useRef<(HTMLButtonElement | null)[]>([])
  return (
    <div role="radiogroup" aria-label={ariaLabel} className={cn('inline-flex w-fit max-w-full items-center gap-0.5 overflow-x-auto rounded-lg bg-muted p-1', className)}>
      {options.map((o, i) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el
            }}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => {
              const d = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
              if (!d) return
              e.preventDefault()
              const n = (i + d + options.length) % options.length
              onChange(options[n].value)
              refs.current[n]?.focus()
            }}
            className={cn(
              'inline-flex items-center justify-center gap-1.5 rounded-md px-3 font-medium whitespace-nowrap text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-4',
              size === 'sm' ? 'h-7 text-[13px] max-md:h-10 pointer-coarse:h-10' : 'h-7 text-sm max-md:h-10 pointer-coarse:h-10',
              active && 'bg-background text-foreground shadow-xs dark:bg-secondary',
            )}
          >
            {o.icon}
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
