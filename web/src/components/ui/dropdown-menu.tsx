import * as React from 'react'
import * as DM from '@radix-ui/react-dropdown-menu'
import { Check, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useMenuSheetDrag } from './sheet-drag'

export const DropdownMenu = DM.Root
export const DropdownMenuTrigger = DM.Trigger
export const DropdownMenuGroup = DM.Group
export const DropdownMenuSub = DM.Sub
export const DropdownMenuRadioGroup = DM.RadioGroup

const panel =
  'z-50 min-w-[10rem] overflow-hidden rounded-lg border bg-popover p-1 text-popover-foreground shadow-pop data-[state=open]:animate-in data-[state=closed]:animate-out'

/** Anchored menu; on phones a bottom sheet (`.mx-sheet`, swipe down to close). */
export function DropdownMenuContent({ className, sideOffset = 6, ref, ...props }: React.ComponentProps<typeof DM.Content>) {
  const sheet = useMenuSheetDrag(ref)
  return (
    <DM.Portal>
      <DM.Content ref={sheet} sideOffset={sideOffset} className={cn(panel, 'mx-sheet max-h-[var(--radix-dropdown-menu-content-available-height)] overflow-y-auto', className)} {...props} />
    </DM.Portal>
  )
}

const item =
  'relative flex cursor-default items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground max-md:py-2.5 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground'

export function DropdownMenuItem({ className, destructive, ...props }: React.ComponentProps<typeof DM.Item> & { destructive?: boolean }) {
  return <DM.Item className={cn(item, destructive && 'text-destructive data-[highlighted]:bg-destructive/10 data-[highlighted]:text-destructive [&_svg]:!text-destructive', className)} {...props} />
}
export function DropdownMenuCheckboxItem({ className, children, ...props }: React.ComponentProps<typeof DM.CheckboxItem>) {
  return (
    <DM.CheckboxItem className={cn(item, 'group/cb pl-8', className)} {...props}>
      {/* Always a visible box, so it reads as a checkbox even when unchecked. */}
      <span
        aria-hidden
        className="absolute left-2 flex size-4 items-center justify-center rounded-[4px] border border-muted-foreground/50 bg-background transition-colors group-data-[state=checked]/cb:border-primary group-data-[state=checked]/cb:bg-primary group-data-[state=checked]/cb:text-primary-foreground"
      >
        <DM.ItemIndicator>
          <Check className="size-3" strokeWidth={3} />
        </DM.ItemIndicator>
      </span>
      {children}
    </DM.CheckboxItem>
  )
}
export function DropdownMenuRadioItem({ className, children, ...props }: React.ComponentProps<typeof DM.RadioItem>) {
  return (
    <DM.RadioItem className={cn(item, 'pl-8', className)} {...props}>
      <span className="absolute left-2 flex size-4 items-center justify-center">
        <DM.ItemIndicator>
          <Check className="size-4 !text-foreground" />
        </DM.ItemIndicator>
      </span>
      {children}
    </DM.RadioItem>
  )
}
export function DropdownMenuLabel({ className, ...props }: React.ComponentProps<typeof DM.Label>) {
  return <DM.Label className={cn('px-2 py-1.5 text-xs font-medium text-muted-foreground', className)} {...props} />
}
export function DropdownMenuSeparator({ className, ...props }: React.ComponentProps<typeof DM.Separator>) {
  return <DM.Separator className={cn('-mx-1 my-1 h-px bg-border', className)} {...props} />
}
export function DropdownMenuShortcut({ className, ...props }: React.ComponentProps<'span'>) {
  return <span className={cn('ml-auto text-xs tracking-widest text-muted-foreground', className)} {...props} />
}
export function DropdownMenuSubTrigger({ className, children, ...props }: React.ComponentProps<typeof DM.SubTrigger>) {
  return (
    <DM.SubTrigger className={cn(item, 'data-[state=open]:bg-accent', className)} {...props}>
      {children}
      <ChevronRight className="ml-auto" />
    </DM.SubTrigger>
  )
}
export function DropdownMenuSubContent({ className, ...props }: React.ComponentProps<typeof DM.SubContent>) {
  return (
    <DM.Portal>
      <DM.SubContent className={cn(panel, className)} {...props} />
    </DM.Portal>
  )
}
