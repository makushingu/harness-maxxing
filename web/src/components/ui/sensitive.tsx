import * as React from 'react'
import { useUI } from '@/stores/ui'
import { cn } from '@/lib/utils'

/**
 * Presentation mode (screen sharing / streaming).
 * <Sensitive>{value}</Sensitive> renders `value` normally, or a mask when presentation mode is on.
 * The real content is NOT rendered at all while active (not hidden with CSS): nothing leaks in the DOM.
 * Wrap every piece of user data: names, numbers, paths, tokens, ids, messages, file contents…
 */
export function Sensitive({
  children,
  length = 6,
  className,
  block,
  placeholder,
}: {
  children: React.ReactNode
  /** Number of mask dots (approximate width). */
  length?: number
  className?: string
  /** Render as a block-level mask bar (for paragraphs, charts, previews). */
  block?: boolean
  /** Custom masked rendering (e.g. a blurred chart outline). */
  placeholder?: React.ReactNode
}) {
  const on = usePresentation()
  if (!on) return <>{children}</>
  if (placeholder) return <>{placeholder}</>
  if (block)
    return (
      <div aria-label="Hidden (presentation mode)" className={cn('flex min-h-6 items-center rounded-md bg-muted/70 px-2 text-xs tracking-[0.3em] text-muted-foreground/70 select-none', className)}>
        ••••••
      </div>
    )
  return (
    <span aria-label="Hidden (presentation mode)" className={cn('tracking-[0.15em] text-muted-foreground select-none', className)}>
      {'•'.repeat(Math.max(2, Math.min(length, 16)))}
    </span>
  )
}

export const usePresentation = () => useUI((s) => s.presentation)

/** For attributes/strings (titles, input values): returns the mask when presentation mode is on. */
export function useMask() {
  const on = usePresentation()
  return React.useCallback((v: string | number | null | undefined, len = 6) => (on ? '•'.repeat(len) : v == null ? '' : String(v)), [on])
}
