import * as React from 'react'
import { Command as Cmdk } from 'cmdk'
import { Check, ChevronsUpDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Popover, PopoverContent, PopoverTrigger } from './popover'

export type ComboOption = { value: string; label: string; hint?: string }

/** Searchable select for long lists (time zones, topics…). `options` may be a function: an expensive list is then
 *  only built when the popover opens (`labelOf` names the value while it is closed). */
export function Combobox({
  value,
  onChange,
  options,
  labelOf,
  placeholder,
  searchPlaceholder,
  className,
  id,
  trigger,
  ...aria
}: {
  value: string
  onChange: (v: string) => void
  options: ComboOption[] | (() => ComboOption[])
  labelOf?: (value: string) => string
  placeholder?: string
  searchPlaceholder?: string
  className?: string
  id?: string
  /** Custom trigger (replaces the select-looking button). */
  trigger?: React.ReactElement
  'aria-describedby'?: string
  'aria-invalid'?: boolean
  'aria-label'?: string
}) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const list = typeof options === 'function' ? (open ? options() : null) : options
  const current = list ? list.find((o) => o.value === value) : value ? { value, label: labelOf ? labelOf(value) : value } : undefined
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {trigger ?? (
        <button
          id={id}
          type="button"
          role="combobox"
          aria-expanded={open}
          {...aria}
          className={cn(
            'flex h-9 w-full min-w-0 items-center justify-between gap-2 rounded-md border border-input bg-transparent px-3 text-left text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25 max-md:h-11 max-md:text-base dark:bg-input/30',
            !current && 'text-muted-foreground',
            className,
          )}
        >
          <span className="truncate">{current?.label || value || placeholder}</span>
          <ChevronsUpDown className="size-4 shrink-0 opacity-50" />
        </button>
        )}
      </PopoverTrigger>
      <PopoverContent sheet className="w-[var(--radix-popover-trigger-width)] min-w-64 p-0" align="start">
        <Cmdk loop>
          <Cmdk.Input placeholder={searchPlaceholder || t('common.search')} className="h-10 w-full border-b bg-transparent px-3 text-sm outline-none placeholder:text-muted-foreground max-md:h-12 max-md:text-base" />
          <Cmdk.List className="max-h-64 overflow-y-auto p-1">
            <Cmdk.Empty className="py-6 text-center text-sm text-muted-foreground">{t('common.noResults')}</Cmdk.Empty>
            {(list ?? []).map((o) => (
              <Cmdk.Item
                key={o.value}
                value={`${o.label} ${o.value}`}
                onSelect={() => {
                  onChange(o.value)
                  setOpen(false)
                }}
                className="flex h-8 cursor-default items-center gap-2 rounded-md px-2 text-sm outline-none data-[selected=true]:bg-accent max-md:h-11"
              >
                <Check className={cn('size-4 shrink-0', o.value === value ? 'opacity-100' : 'opacity-0')} />
                <span className="flex-1 truncate">{o.label}</span>
                {o.hint && <span className="text-xs text-muted-foreground">{o.hint}</span>}
              </Cmdk.Item>
            ))}
          </Cmdk.List>
        </Cmdk>
      </PopoverContent>
    </Popover>
  )
}
