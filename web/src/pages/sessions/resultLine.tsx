/* The line under each answer (model, duration, cost, tokens, cache): which parts it shows (setting
   `result_line_hidden`, the same for every browser) and what the cost means for this installation. */
import * as React from 'react'
import { SlidersHorizontal } from 'lucide-react'
import { useT, type TKey } from '@/i18n'
import { useClaudeStatus, useSaveSettings, useSettings } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { ClaudeAuthMethod, ResultField } from '@/lib/types'
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui'

export const RESULT_FIELDS: { id: ResultField; label: TKey }[] = [
  { id: 'model', label: 'sessions.result.model' },
  { id: 'duration', label: 'sessions.result.duration' },
  { id: 'cost', label: 'sessions.result.cost' },
  { id: 'tokens', label: 'sessions.result.tokens' },
  { id: 'cache', label: 'sessions.result.cache' },
]

const NO_FIELDS: ResultField[] = []

export function useResultLine() {
  const { data: s } = useSettings()
  const save = useSaveSettings()
  const hidden = s?.result_line_hidden || NO_FIELDS
  const toggle = React.useCallback(
    (f: ResultField, shown: boolean) => save.mutate({ result_line_hidden: shown ? hidden.filter((x) => x !== f) : [...hidden.filter((x) => x !== f), f] }),
    [hidden, save],
  )
  return { hidden, toggle }
}

/** With an API key the cost is billed; with a Claude subscription (or unknown sign-in) it is Claude Code's
 *  estimate at API prices, not charged. */
export function useCostIsBilled(): boolean {
  const { data } = useClaudeStatus()
  return (data?.auth.method as ClaudeAuthMethod) === 'api_key'
}

export function costTip(t: ReturnType<typeof useT>, billed: boolean, turns?: number): string {
  const what = turns == null ? t('sessions.result.costTurn') : t('sessions.result.costTotal', { count: turns })
  return `${what} ${billed ? t('sessions.result.costBilled') : t('sessions.result.costEstimate')}`
}

/** The ⚙ at the end of the line: shown on hover / focus with a mouse, always (faint) on a touch screen. */
export function ResultLineMenu() {
  const t = useT()
  const { hidden, toggle } = useResultLine()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={t('sessions.result.choose')}
          data-testid="result-line-menu"
          className={cn(
            "relative inline-flex size-4 items-center justify-center rounded text-muted-foreground/70 outline-none hover:text-foreground focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:opacity-100 pointer-coarse:before:absolute pointer-coarse:before:-inset-2 pointer-coarse:before:content-['']",
            'max-md:size-6 max-md:opacity-60 md:opacity-0 md:group-hover/result:opacity-100',
          )}
        >
          <SlidersHorizontal className="size-3" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-48">
        <DropdownMenuLabel>{t('sessions.result.show')}</DropdownMenuLabel>
        {RESULT_FIELDS.map((f) => (
          <DropdownMenuCheckboxItem key={f.id} checked={!hidden.includes(f.id)} onCheckedChange={(c) => toggle(f.id, !!c)} onSelect={(e) => e.preventDefault()}>
            {t(f.label)}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
