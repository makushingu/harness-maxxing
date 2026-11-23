import * as React from 'react'
import { cn } from '@/lib/utils'

export function Card({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('mx-lg flex flex-col rounded-xl border bg-card text-card-foreground shadow-xs', className)} {...props} />
}
