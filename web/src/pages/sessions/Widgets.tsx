// Small column widgets: model picker (shows the model that ACTUALLY answered), compaction gauge, state badge.
import { Check, ChevronDown, Cpu } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { useClaudeStatus } from '@/lib/queries'
import { Badge, confirm, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger, StatusDot, Tooltip } from '@/components/ui'
import { EFFORTS, type Effort, type Session } from '@/lib/types'
import { contextWindow, fmtTokens, modelLabel } from './util'

/** Family aliases follow resolved versions; pinned model ids still compare exactly. */
function matchesModel(real: string, chosen: string): boolean {
  return real === chosen || (['sonnet', 'opus', 'haiku'].includes(chosen) && real.startsWith(`claude-${chosen}-`))
}

/** Context size from which switching the model asks first: each model has its own prompt cache, so the new one
 * reads the whole conversation uncached on the next message. */
const SWITCH_WARN_TOKENS = 50_000

/** Intelligence of the next turns inside the model menu: Auto (Claude Code's default) then the 5 levels. */
function EffortRow({ effort, onEffort }: { effort: Effort | ''; onEffort: (effort: Effort | '') => void }) {
  const t = useT()
  return (
    <>
      <DropdownMenuSeparator />
      <DropdownMenuLabel className="flex items-center justify-between text-xs font-normal text-muted-foreground">
        <span>{t('effort.label')}</span>
        <span>{t(`effort.long.${effort || 'auto'}`)}</span>
      </DropdownMenuLabel>
      <div role="radiogroup" aria-label={t('effort.label')} className="mx-1 mb-1 grid grid-cols-6 gap-0.5 rounded-md bg-muted p-0.5">
        {(['', ...EFFORTS] as const).map((e) => (
          <Tooltip key={e || 'auto'} content={t(`effort.hint.${e || 'auto'}`)}>
            <button
              type="button"
              role="radio"
              aria-checked={effort === e}
              onClick={() => onEffort(e)}
              className={cn(
                'h-7 rounded px-0.5 text-[11px] font-medium text-muted-foreground transition hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none max-md:h-9 pointer-coarse:h-10',
                effort === e && 'bg-background text-foreground shadow-sm',
              )}
            >
              {t(`effort.${e || 'auto'}`)}
            </button>
          </Tooltip>
        ))}
      </div>
    </>
  )
}

export function ModelPicker({
  chosen,
  real,
  contextTokens,
  onChange,
  disabled,
  compact,
  effort,
  onEffort,
  defaultModel,
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
  /** Intelligence (`claude --effort`) of the next turns, "" = Claude Code's default; shown with `onEffort` only. */
  effort?: Effort | ''
  onEffort?: (effort: Effort | '') => void
  /** What "Default" runs when it is not the server's default model (an agent's conversation: the agent's model). */
  defaultModel?: string
}) {
  const t = useT()
  const { data } = useClaudeStatus()
  const models = data?.models || []
  const def = defaultModel || data?.default_model || ''
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
            {onEffort && effort && <span className="shrink-0 text-[10px] text-muted-foreground/80">· {t(`effort.${effort}`)}</span>}
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
        {onEffort && <EffortRow effort={effort || ''} onEffort={onEffort} />}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** The context left before the next compaction, next to the model picker of a composer. The threshold is the
 *  server's (runner._auto_compact): `auto_compact_tokens` raised to 100k, capped by the model's window
 *  (resume.fit: window - 70k, never under half of it). Automatic compaction off: the model's window.
 *  Two looks from the toolbar's width (`@container` of the composer bar): a bar + "75 % · 188k / 250k" with room,
 *  a ring + "75 %" without. */
export function CompactGauge({ tokens, window: reported, model, realModel }: { tokens: number | null | undefined; window?: number | null; model?: string | null; realModel?: string | null }) {
  const t = useT()
  const { data: claude } = useClaudeStatus()
  if (!tokens) return null
  const windows = Object.fromEntries((claude?.models || []).map((m) => [m.id, m.context_window]))
  const win = contextWindow(tokens, reported, { chosen: model || claude?.default_model || null, real: realModel, windows })
  const at = compactAt(claude?.auto_compact_tokens, win)
  const max = at ?? win
  const pct = Math.round(Math.min(1, tokens / max) * 100)
  const tip = at
    ? t('cgauge.tip', { at: fmtTokens(at), left: fmtTokens(Math.max(0, at - tokens)), used: fmtTokens(tokens), window: fmtTokens(win) })
    : t('cgauge.off', { used: fmtTokens(tokens), window: fmtTokens(win), pct })
  return (
    <Tooltip content={<span className="block max-w-72 whitespace-normal">{tip}</span>}>
      <span
        tabIndex={0}
        className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded px-1 text-[11px] text-muted-foreground tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={t('sessions.context', { used: fmtTokens(tokens), max: fmtTokens(max), pct })}
        data-testid="compact-gauge"
      >
        {/* narrow: a ring that fills up (r = 6 -> circumference 37.7) */}
        <svg viewBox="0 0 16 16" className="size-3.5 -rotate-90 @md:hidden" aria-hidden>
          <circle cx="8" cy="8" r="6" fill="none" strokeWidth="2.5" className="stroke-muted" />
          <circle cx="8" cy="8" r="6" fill="none" strokeWidth="2.5" strokeLinecap="round" className="stroke-primary transition-[stroke-dasharray] duration-500 ease-out" strokeDasharray={`${Math.max(1.5, (pct / 100) * 37.7)} 37.7`} />
        </svg>
        {/* wide: a bar */}
        <span className="relative hidden h-1.5 w-12 overflow-hidden rounded-full bg-muted @md:block" aria-hidden>
          <span className="absolute inset-y-0 left-0 rounded-full bg-primary transition-[width] duration-500 ease-out" style={{ width: `${Math.max(4, pct)}%` }} />
        </span>
        <span>
          {pct} %<span className="hidden @md:inline"> · {fmtTokens(tokens)} / {fmtTokens(max)}</span>
        </span>
      </span>
    </Tooltip>
  )
}

/** Tokens at which the server compacts a session (null: automatic compaction off). Mirrors runner._auto_compact. */
export function compactAt(setting: number | null | undefined, window: number | null | undefined): number | null {
  if (!setting || setting <= 0) return null
  const limit = Math.max(setting, 100_000)
  if (!window || window <= 0) return limit
  return Math.min(limit, Math.max(window - 70_000, Math.floor(window / 2)))
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
