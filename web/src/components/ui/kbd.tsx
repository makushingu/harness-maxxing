import { cn, isMac } from '@/lib/utils'

export function Kbd({ className, children, ...props }: React.ComponentProps<'kbd'>) {
  return (
    <kbd
      className={cn(
        'pointer-events-none inline-flex h-5 min-w-5 items-center justify-center gap-0.5 rounded border bg-muted px-1 font-sans text-[11px] font-medium text-muted-foreground select-none',
        className,
      )}
      {...props}
    >
      {children}
    </kbd>
  )
}

/** "Mod" = ⌘ on Apple, Ctrl elsewhere. */
export const MOD = isMac ? '⌘' : 'Ctrl'
