import * as React from 'react'
import * as PopoverPrimitive from '@radix-ui/react-popover'
import { cn } from '@/lib/utils'
import { useMenuSheetDrag } from './sheet-drag'

export const Popover = PopoverPrimitive.Root
export const PopoverTrigger = PopoverPrimitive.Trigger
export const PopoverAnchor = PopoverPrimitive.Anchor
export const PopoverClose = PopoverPrimitive.Close

/** `sheet`: a list of choices - on phones it opens as a bottom sheet like the menus (`.mx-sheet`). */
export function PopoverContent({ className, align = 'center', sideOffset = 6, sheet, ref, ...props }: React.ComponentProps<typeof PopoverPrimitive.Content> & { sheet?: boolean }) {
  const drag = useMenuSheetDrag(ref)
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        ref={sheet ? drag : ref}
        align={align}
        sideOffset={sideOffset}
        collisionPadding={8}
        className={cn(
          'z-50 w-72 max-w-[calc(100vw-16px)] rounded-lg border bg-popover p-4 text-popover-foreground shadow-pop outline-none data-[state=open]:animate-in data-[state=closed]:animate-out',
          sheet && 'mx-sheet',
          className,
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )
}
