import * as React from 'react'
import { cn } from '@/lib/utils'

export const inputBase =
  'w-full min-w-0 rounded-md border border-input bg-transparent px-3 text-foreground shadow-xs transition-[border-color,box-shadow] outline-none placeholder:text-muted-foreground/70 focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:bg-input/30'

export function Input({ className, type = 'text', ...props }: React.ComponentProps<'input'>) {
  return <input type={type} className={cn(inputBase, 'h-9 py-1 max-md:h-11 pointer-coarse:h-11 file:mr-3 file:border-0 file:bg-transparent file:text-sm file:font-medium', className)} {...props} />
}
