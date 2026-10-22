import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'
import { Spinner } from './spinner'

export const buttonVariants = cva(
  'relative inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium select-none transition-[color,background-color,border-color,box-shadow,opacity] outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*=size-])]:size-4',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground shadow-xs hover:bg-primary/90',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        outline: 'border border-input bg-transparent shadow-xs hover:bg-accent hover:text-accent-foreground',
        ghost: 'hover:bg-accent hover:text-accent-foreground',
        destructive: 'bg-destructive text-destructive-foreground shadow-xs hover:bg-destructive/90',
        link: 'h-auto px-0 text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-9 px-4 max-md:h-11 pointer-coarse:h-11',
        sm: 'h-8 rounded-md px-3 text-[13px] max-md:h-10 pointer-coarse:h-10',
        lg: 'h-11 rounded-md px-6 text-[15px]',
        icon: 'size-9 max-md:size-11 pointer-coarse:size-11',
        'icon-sm': 'size-8 max-md:size-10 pointer-coarse:size-10',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export type ButtonProps = React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
    /** Shows a spinner, keeps the width (no layout shift) and disables the button. */
    loading?: boolean
  }

export function Button({ className, variant, size, asChild = false, loading = false, disabled, children, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : 'button'
  if (asChild) {
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} {...props}>
        {children}
      </Comp>
    )
  }
  return (
    <button
      type="button"
      className={cn(buttonVariants({ variant, size, className }))}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? (
        <>
          <span className="invisible inline-flex items-center gap-2">{children}</span>
          <span className="absolute inset-0 flex items-center justify-center">
            <Spinner className="size-4" />
          </span>
        </>
      ) : (
        children
      )}
    </button>
  )
}
