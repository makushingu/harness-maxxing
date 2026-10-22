import * as React from 'react'
import { cn } from '@/lib/utils'

export function Card({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-col rounded-xl border bg-card text-card-foreground shadow-xs', className)} {...props} />
}
export function CardHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1 p-[var(--pad-card)] pb-0', className)} {...props} />
}
export function CardTitle({ className, ...props }: React.ComponentProps<'h3'>) {
  return <h3 className={cn('text-[15px] leading-tight font-semibold tracking-tight', className)} {...props} />
}
export function CardDescription({ className, ...props }: React.ComponentProps<'p'>) {
  return <p className={cn('text-[13px] text-muted-foreground', className)} {...props} />
}
export function CardContent({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('p-[var(--pad-card)]', className)} {...props} />
}
export function CardFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex items-center gap-2 border-t px-[var(--pad-card)] py-3', className)} {...props} />
}
