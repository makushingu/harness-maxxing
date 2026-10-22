// Small column widgets: model picker (shows the model that ACTUALLY answered), context gauge, state badge.
import { Check, ChevronDown, Cpu } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { useClaudeStatus } from '@/lib/queries'
import { Badge, confirm, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger, StatusDot, Tooltip } from '@/components/ui'
import type { Session } from '@/lib/types'
import { contextWindow, fmtTokens, modelLabel } from './util'

/** Family aliases follow resolved versions; pinned model ids still compare exactly. */
function matchesModel(real: string, chosen: string): boolean {
  return real === chosen || (['sonnet', 'opus', 'haiku'].includes(chosen) && real.startsWith(`claude-${chosen}-`))
}

/** Context size from which switching the model asks first: each model has its own prompt cache, so the new one
 * reads the whole conversation uncached on the next message. */
const SWITCH_WARN_TOKENS = 50_000

export function ModelPicker({
  chosen,
  real,
  contextTokens,
  onChange,
  disabled,
  compact,
}: {
  /** Model chosen for the next turns ("" = default). */
  chosen: string
  /** Model that answered the last turn (null before the first answer). */
  real?: string | null
  /** Context of the last turn: a switch above SWITCH_WARN_TOKENS asks first. */
  contextTokens?: number | null
  onChange: (model: string) => void
  disabled?: boolean
  compact?: boolean
}) {
  const t = useT()
  const { data } = useClaudeStatus()
  const models = data?.models || []
  const def = data?.default_model || ''
  const next = chosen || def
  const shown = real || next
  const differs = !!real && !!next && !matchesModel(real, next)
  const label = shown ? modelLabel(shown, models) : t('sessions.model.default')
  const tip = differs
    ? t('sessions.model.differs', { real: modelLabel(real, models), next: modelLabel(next, models) })
    : real
      ? t('sessions.model.answered', { model: modelLabel(real, models) })
      : t('sessions.model.next', { model: next ? modelLabel(next, models) : t('sessions.model.default') })
  const pick = async (model: string) => {
    const target = model || def
    const ctx = contextTokens ?? 0
    if (real && target && ctx >= SWITCH_WARN_TOKENS && !matchesModel(real, target)) {
      const ok = await confirm({
        title: t('sessions.switchModel.title'),
        description: t('sessions.switchModel.desc', { tokens: `${Math.round(ctx / 1000)}k` }),
        confirmText: t('sessions.switchModel.confirm'),
      })
      if (!ok) return
    }
    onChange(model)
  }
  const options = models.some((m) => m.id === chosen) || !chosen ? models : [...models, { id: chosen, label: modelLabel(chosen) }]
  return (
    <DropdownMenu>
      <Tooltip content={tip}>
        <DropdownMenuTrigger asChild disabled={disabled}>
          <button
            type="button"
            aria-label={`${t('sessions.model.label')}: ${label}`}
            className={cn(
              'inline-flex h-8 min-w-0 items-center gap-1.5 rounded-md px-2 text-xs font-medium text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50 max-md:h-10',
              compact && 'h-7 px-1.5',
            )}
          >
            <Cpu className="size-3.5 shrink-0" />
            {/* narrow composer + a pending switch: only "-> next model" (the tooltip says which one answered) */}
            <span className={cn('truncate', differs && '@max-sm:hidden')}>{label}</span>
            {differs && (
              <span className="shrink-0 rounded bg-warning/15 px-1 text-[10px] whitespace-nowrap text-warning">
                → {modelLabel(next, models)}
              </span>
            )}
            <ChevronDown className="size-3 shrink-0 opacity-60" />
          </button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          {real ? t('sessions.model.answered', { model: modelLabel(real, models) }) : t('sessions.model.nextTurn')}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void pick('')}>
          <span className="flex size-4 items-center justify-center">{!chosen && <Check className="!text-foreground" />}</span>
          <span className="flex-1">{t('sessions.model.default')}</span>
          {def && <span className="text-xs text-muted-foreground">{modelLabel(def, models)}</span>}
        </DropdownMenuItem>
        {options.map((m) => (
          <DropdownMenuItem key={m.id} onSelect={() => void pick(m.id)}>
            <span className="flex size-4 items-center justify-center">{chosen === m.id && <Check className="!text-foreground" />}</span>
            <span className="flex-1">{m.label || modelLabel(m.id)}</span>
            {real === m.id && <span className="text-[10px] text-muted-foreground">{t('sessions.model.lastUsed')}</span>}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function ContextGauge({ tokens, window: reported, model, realModel, ring }: { tokens: number | null; window?: number | null; model?: string | null; realModel?: string | null; ring?: boolean }) {
  const t = useT()
  const { data: claude } = useClaudeStatus()
  if (!tokens) return null
  const windows = Object.fromEntries((claude?.models || []).map((m) => [m.id, m.context_window]))
  const max = contextWindow(tokens, reported, { chosen: model || claude?.default_model || null, real: realModel, windows })
  const pct = Math.min(1, tokens / max)
  const tone = pct > 0.85 ? 'bg-destructive' : pct > 0.6 ? 'bg-warning' : 'bg-primary'
  const label = t('sessions.context', { used: fmtTokens(tokens), max: fmtTokens(max), pct: Math.round(pct * 100) })
  if (ring) {
    // phone header: a ring that fills with the context used (r = 6.5 -> circumference 40.84)
    const stroke = pct > 0.85 ? 'stroke-destructive' : pct > 0.6 ? 'stroke-warning' : 'stroke-primary'
    return (
      <Tooltip content={label}>
        <span tabIndex={0} className="inline-flex items-center gap-1 rounded outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={label}>
          <svg viewBox="0 0 16 16" className="size-4 -rotate-90" aria-hidden>
            <circle cx="8" cy="8" r="6.5" fill="none" strokeWidth="2.5" className="stroke-muted" />
            <circle cx="8" cy="8" r="6.5" fill="none" strokeWidth="2.5" strokeLinecap="round" className={cn(stroke, 'transition-[stroke-dasharray] duration-500 ease-out')} strokeDasharray={`${Math.max(1.5, pct * 40.84)} 40.84`} />
          </svg>
          <span className="tabular-nums">{fmtTokens(tokens)}</span>
        </span>
      </Tooltip>
    )
  }
  return (
    <Tooltip content={t('sessions.context', { used: fmtTokens(tokens), max: fmtTokens(max), pct: Math.round(pct * 100) })}>
      <span tabIndex={0} className="inline-flex items-center gap-1.5 rounded outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={t('sessions.context', { used: fmtTokens(tokens), max: fmtTokens(max), pct: Math.round(pct * 100) })}>
        <span className="relative h-1.5 w-10 overflow-hidden rounded-full bg-muted">
          <span className={cn('absolute inset-y-0 left-0 rounded-full', tone)} style={{ width: `${Math.max(4, pct * 100)}%` }} />
        </span>
        <span className="tabular-nums">{fmtTokens(tokens)}</span>
      </span>
    </Tooltip>
  )
}

export function StateBadge({ session }: { session: Pick<Session, 'state' | 'queue' | 'error'> }) {
  const t = useT()
  if (session.state === 'running')
    return (
      <Badge variant="outline" className="gap-1.5 border-primary/30 text-primary">
        <StatusDot tone="running" pulse className="size-1.5" />
        {t('sessions.state.running')}
      </Badge>
    )
  if (session.state === 'error')
    return (
      <Tooltip content={session.error || undefined}>
        <Badge variant="destructive">{t('sessions.state.error')}</Badge>
      </Tooltip>
    )
  return null
}
