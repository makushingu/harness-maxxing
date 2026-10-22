import * as React from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { cn, mergeRefs } from '@/lib/utils'
import { sheetIsBottom, useSheetDrag } from './sheet-drag'

export const Sheet = DialogPrimitive.Root
export const SheetTrigger = DialogPrimitive.Trigger
export const SheetClose = DialogPrimitive.Close

type Side = 'right' | 'left' | 'bottom'

/**
 * Side drawer (desktop) that becomes a bottom sheet on mobile (< md).
 * `side="bottom"` forces a bottom sheet everywhere.
 */
export function SheetContent({ side = 'right', className, children, hideClose, ref, ...props }: React.ComponentProps<typeof DialogPrimitive.Content> & { side?: Side; hideClose?: boolean }) {
  const overlay = React.useRef<HTMLDivElement>(null)
  const close = React.useRef<HTMLButtonElement>(null)
  const drag = useSheetDrag(() => close.current?.click(), sheetIsBottom(side === 'bottom'), overlay)
  const refs = React.useMemo(() => mergeRefs(ref, drag), [ref, drag])
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay ref={overlay} className="fixed inset-0 z-50 bg-overlay data-[state=closed]:animate-overlay-out data-[state=open]:animate-overlay-in" />
      <DialogPrimitive.Content
        ref={refs}
        className={cn(
          'fixed z-50 flex flex-col bg-popover text-popover-foreground shadow-pop outline-none',
          'inset-x-0 bottom-[var(--kbd-inset)] max-h-[calc(var(--vvh,100dvh)*0.92)] rounded-t-2xl border-t pb-[var(--safe-bottom)] data-[state=closed]:animate-sheet-down data-[state=open]:animate-sheet-up',
          side === 'right' && 'md:inset-y-0 md:right-0 md:left-auto md:h-dvh md:max-h-none md:w-[420px] md:max-w-[90vw] md:rounded-none md:border-t-0 md:border-l md:pb-0 md:data-[state=closed]:animate-sheet-right-out md:data-[state=open]:animate-sheet-right',
          side === 'left' && 'md:inset-y-0 md:right-auto md:left-0 md:h-dvh md:max-h-none md:w-[320px] md:max-w-[90vw] md:rounded-none md:border-t-0 md:border-r md:pb-0 md:data-[state=closed]:animate-sheet-left-out md:data-[state=open]:animate-sheet-left',
          className,
        )}
        {...props}
      >
        {/* Grab handle: a finger-sized strip (the whole sheet can be swiped down, see sheet-drag.ts). */}
        <div aria-hidden className={cn('flex shrink-0 justify-center pt-2 pb-0.5', side !== 'bottom' && 'md:hidden')}>
          <div className="h-1 w-10 rounded-full bg-muted-foreground/30" />
        </div>
        <DialogPrimitive.Close ref={close} hidden tabIndex={-1} aria-hidden />
        {children}
        {!hideClose && (
          <DialogPrimitive.Close className="absolute top-3 right-3 rounded-md p-1.5 text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none max-md:hidden">
            <X className="size-4" />
            <span className="sr-only">Close</span>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}
export function SheetHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1 px-5 pt-3 pb-3 md:pt-5', className)} {...props} />
}
export function SheetBody({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('min-h-0 flex-1 overflow-y-auto px-5 pb-5', className)} {...props} />
}
export const SheetTitle = ({ className, ...p }: React.ComponentProps<typeof DialogPrimitive.Title>) => (
  <DialogPrimitive.Title className={cn('text-base font-semibold tracking-tight', className)} {...p} />
)
export const SheetDescription = ({ className, ...p }: React.ComponentProps<typeof DialogPrimitive.Description>) => (
  <DialogPrimitive.Description className={cn('text-sm text-muted-foreground', className)} {...p} />
)
