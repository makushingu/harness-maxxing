import * as React from 'react'
import * as SwitchPrimitive from '@radix-ui/react-switch'
import { cn } from '@/lib/utils'

export function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        'peer relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-transparent shadow-xs transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary data-[state=unchecked]:bg-input dark:data-[state=unchecked]:bg-input/80',
        // larger hit area on touch without changing the visual size
        'before:absolute before:-inset-3 before:content-[""]',
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="pointer-events-none block size-4 rounded-full bg-background shadow-sm ring-0 transition-transform data-[state=checked]:translate-x-[calc(100%)] data-[state=unchecked]:translate-x-0.5 dark:data-[state=checked]:bg-primary-foreground dark:data-[state=unchecked]:bg-foreground" />
    </SwitchPrimitive.Root>
  )
}
