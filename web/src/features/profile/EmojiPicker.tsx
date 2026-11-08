// A button that opens an emoji picker (search + categories): no more copying an emoji from elsewhere.
// The grid (frimousse + its data) is a separate chunk, loaded on first open.
import * as React from 'react'
import { SmilePlus, X } from 'lucide-react'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import { Popover, PopoverContent, PopoverTrigger, Spinner } from '@/components/ui'

const Body = React.lazy(() => import('./EmojiPickerBody'))

export function EmojiPicker({ value, onChange, className, label }: { value: string; onChange: (emoji: string) => void; className?: string; label?: string }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  return (
    <div className={cn('inline-flex items-center gap-1', className)}>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label={label || t('emoji.pick')}
            title={label || t('emoji.pick')}
            className="inline-flex h-9 min-w-12 items-center justify-center rounded-md border bg-background px-2.5 text-xl leading-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            {value || <SmilePlus className="size-4 text-muted-foreground" />}
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-auto overflow-hidden p-0">
          <React.Suspense fallback={<div className="flex h-[340px] w-[304px] items-center justify-center text-muted-foreground"><Spinner /></div>}>
            <Body
              onPick={(e) => {
                onChange(e)
                setOpen(false)
              }}
            />
          </React.Suspense>
        </PopoverContent>
      </Popover>
      {value && (
        <button
          type="button"
          onClick={() => onChange('')}
          aria-label={t('emoji.clear')}
          title={t('emoji.clear')}
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <X className="size-3.5" />
        </button>
      )}
    </div>
  )
}
