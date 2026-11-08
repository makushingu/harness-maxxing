import * as React from 'react'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import { cn } from '@/lib/utils'

export const TooltipProvider = TooltipPrimitive.Provider
export const TooltipRoot = TooltipPrimitive.Root
export const TooltipTrigger = TooltipPrimitive.Trigger

export function TooltipContent({ className, sideOffset = 6, ...props }: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        sideOffset={sideOffset}
        className={cn(
          'z-[60] flex items-center gap-2 rounded-md bg-foreground px-2.5 py-1.5 text-xs font-medium text-background shadow-pop data-[state=delayed-open]:animate-in data-[state=closed]:animate-out',
          className,
        )}
        {...props}
      />
    </TooltipPrimitive.Portal>
  )
}

/** Trigger for a child whose className is a function (NavLink): Radix's Slot joins class names as strings, which
 *  turned the function into text (the link lost its classes). The trigger's props go to the child, handlers composed. */
const KeepClass = React.forwardRef<HTMLElement, Record<string, unknown>>(function KeepClass(props, ref) {
  const { child: c, className: _joined, ...slot } = props
  const child = c as React.ReactElement<Record<string, unknown>>
  const own = child.props
  const merged: Record<string, unknown> = { ...slot }
  for (const k of Object.keys(slot)) {
    const a = own[k]
    const b = slot[k]
    if (/^on[A-Z]/.test(k) && typeof a === 'function' && typeof b === 'function')
      merged[k] = (...args: unknown[]) => {
        ;(a as (...x: unknown[]) => void)(...args)
        ;(b as (...x: unknown[]) => void)(...args)
      }
  }
  if (own.style && slot.style) merged.style = { ...(slot.style as object), ...(own.style as object) }
  return React.cloneElement(child, { ...merged, ref })
})

/** Inside a provider set to true, a disabled tooltip keeps its Radix wrapper (closed) instead of returning the bare
 *  child: switching a tooltip off then does not remount the child, so it keeps the keyboard focus (the folding
 *  sidebar turns its tooltips off while it unfolds). */
export const KeepTooltipShape = React.createContext(false)

/** Shorthand: <Tooltip content="Label" side="right"><Button …/></Tooltip>. `content=null` disables it. */
export function Tooltip({ content, side, align, children, disabled }: { content: React.ReactNode; side?: 'top' | 'right' | 'bottom' | 'left'; align?: 'start' | 'center' | 'end'; children: React.ReactNode; disabled?: boolean }) {
  const keep = React.useContext(KeepTooltipShape)
  const [open, setOpen] = React.useState(false)
  const off = disabled || content == null || content === ''
  if (off && !keep) return <>{children}</>
  return (
    // While off, Radix still asks to open on hover/focus but never asks to close (the controlled value is already
    // false): ignore those opens, or every row touched while unfolded shows its tooltip once the bar folds.
    <TooltipRoot open={!off && open} onOpenChange={(o) => setOpen(off ? false : o)}>
      <TooltipTrigger asChild>
        {React.isValidElement<Record<string, unknown>>(children) && typeof children.props.className === 'function' ? <KeepClass child={children} /> : children}
      </TooltipTrigger>
      {!off && (
        <TooltipContent side={side} align={align}>
          {content}
        </TooltipContent>
      )}
    </TooltipRoot>
  )
}
