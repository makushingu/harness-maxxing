import * as React from 'react'
import * as SA from '@radix-ui/react-scroll-area'
import { cn } from '@/lib/utils'

/** Custom-scrollbar container (use for side panels / popovers; page bodies use native scrolling). */
export function ScrollArea({ className, children, viewportRef, ...props }: React.ComponentProps<typeof SA.Root> & { viewportRef?: React.Ref<HTMLDivElement> }) {
  return (
    <SA.Root className={cn('relative overflow-hidden', className)} {...props}>
      <SA.Viewport ref={viewportRef} className="size-full rounded-[inherit] [&>div]:!block">
        {children}
      </SA.Viewport>
      <ScrollBar />
      <SA.Corner />
    </SA.Root>
  )
}
export function ScrollBar({ orientation = 'vertical' }: { orientation?: 'vertical' | 'horizontal' }) {
  return (
    <SA.Scrollbar
      orientation={orientation}
      className={cn('flex touch-none p-px transition-colors select-none', orientation === 'vertical' ? 'h-full w-2' : 'h-2 flex-col')}
    >
      <SA.Thumb className="relative flex-1 rounded-full bg-muted-foreground/30 hover:bg-muted-foreground/50" />
    </SA.Scrollbar>
  )
}
