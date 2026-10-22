import * as React from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { cn, mergeRefs } from '@/lib/utils'
import { sheetIsBottom, useSheetDrag } from './sheet-drag'

export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogClose = DialogPrimitive.Close

export function DialogOverlay({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return <DialogPrimitive.Overlay className={cn('fixed inset-0 z-50 bg-overlay data-[state=closed]:animate-overlay-out data-[state=open]:animate-overlay-in', className)} {...props} />
}

type ContentProps = React.ComponentProps<typeof DialogPrimitive.Content> & { hideClose?: boolean }

/** Centered dialog on desktop; on mobile it becomes a bottom sheet (full width, safe-area aware, swipe down to close). */
export function DialogContent({ className, children, hideClose, ref, ...props }: ContentProps) {
  const overlay = React.useRef<HTMLDivElement>(null)
  const close = React.useRef<HTMLButtonElement>(null)
  const drag = useSheetDrag(() => close.current?.click(), sheetIsBottom(false), overlay)
  const refs = React.useMemo(() => mergeRefs(ref, drag), [ref, drag])
  return (
    <DialogPrimitive.Portal>
      <DialogOverlay ref={overlay} />
      <DialogPrimitive.Content
        ref={refs}
        className={cn(
          'fixed z-50 flex flex-col gap-4 border bg-popover text-popover-foreground shadow-pop outline-none',
          // mobile: bottom sheet
          'inset-x-0 bottom-[var(--kbd-inset)] max-h-[calc(var(--vvh,100dvh)*0.92)] overflow-y-auto overscroll-contain rounded-t-2xl p-5 pb-[calc(1.25rem+var(--safe-bottom))] data-[state=closed]:animate-sheet-down data-[state=open]:animate-sheet-up',
          // desktop: centered
          'md:inset-auto md:top-1/2 md:left-1/2 md:max-h-[85dvh] md:w-full md:max-w-lg md:-translate-x-1/2 md:-translate-y-1/2 md:rounded-xl md:p-6 md:data-[state=closed]:animate-out md:data-[state=open]:animate-in',
          className,
        )}
        {...props}
      >
        <div aria-hidden className="-mt-3 flex shrink-0 justify-center pt-1 pb-1 md:hidden">
          <div className="h-1 w-10 rounded-full bg-muted-foreground/30" />
        </div>
        <DialogPrimitive.Close ref={close} hidden tabIndex={-1} aria-hidden />
        {children}
        {!hideClose && (
          <DialogPrimitive.Close className="absolute top-3 right-3 rounded-md p-1.5 text-muted-foreground opacity-80 transition hover:bg-accent hover:opacity-100 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none max-md:hidden">
            <X className="size-4" />
            <span className="sr-only">Close</span>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}

export function DialogHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1.5 pr-6 text-left', className)} {...props} />
}
export function DialogFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end', className)} {...props} />
}
export function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return <DialogPrimitive.Title className={cn('text-base leading-tight font-semibold tracking-tight', className)} {...props} />
}
export function DialogDescription({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return <DialogPrimitive.Description className={cn('text-sm text-muted-foreground', className)} {...props} />
}
