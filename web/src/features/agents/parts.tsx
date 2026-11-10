// Building blocks shared by the Agents page, the creation sheet and an agent's page.
import * as React from 'react'
import { Link, useNavigate } from 'react-router'
import { Bot, Clock, MessagesSquare, Rss, Send, Settings2, Webhook } from 'lucide-react'
import { useT, type TFn, type TKey } from '@/i18n'
import { useClaudeStatus, useContinueRun, useFeedSettings, usePatchHook, useRunAgent, useSecrets, useSettings } from '@/lib/queries'
import type { Agent, AgentLimits, AgentWebhookResult, AgentTrigger, AgentTriggerInput, AgentWebhookKind, Cron, FeedLevel, PermissionMode } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Badge, Button, Checkbox, CopyButton, toast, EmptyState, FormField, Input, Select, Sensitive, Textarea, Tooltip, useMask, type DotTone } from '@/components/ui'
import { Callout } from '@/features/common'
import { Page } from '@/components/shell/Page'
import { fmtRelative } from '@/lib/format'
import { fmtCost, sessionsUrl } from '@/pages/sessions/util'

export const FEED_LEVELS: FeedLevel[] = ['info', 'success', 'warning', 'error']
export const WEBHOOK_KINDS: AgentWebhookKind[] = ['generic', 'stripe', 'shopify', 'github']
export const DEFAULT_LIMITS: AgentLimits = { usd_per_day: 2, runs_per_hour: 6, timeout_s: 1800, debounce_s: 60 }

/** When something happened, to fill "Ran {when}": "just now" under a minute (Intl alone says a bare "now", which
 *  reads oddly after a verb), otherwise the relative date ("5 min ago"). For past moments only. */
export function agoText(at: number, lang: string, t: TFn): string {
  const age = Date.now() / 1000 - at
  return age > -60 && age < 60 ? t('agents.justNow') : fmtRelative(at, lang)
}

export type Status = { id: 'waiting' | 'running' | 'unread' | 'failed' | 'off' | 'idle'; tone: DotTone; pulse?: boolean; text: string }

/** One status per agent in words, the most pressing first (working beats new results: it is live). */
export function statusOf(a: Agent, t: TFn, lang: string): Status {
  const last = a.last_run
  if ((a.waiting || 0) > 0) return { id: 'waiting', tone: 'warn', pulse: true, text: t('agents.list.waiting') }
  if ((a.running_now || 0) > 0) return { id: 'running', tone: 'running', pulse: true, text: t('agents.list.working') }
  if ((a.thread_unread || 0) > 0) return { id: 'unread', tone: 'unread', text: t('agents.list.unread', { count: a.thread_unread || 0 }) }
  if (!a.enabled) return { id: 'off', tone: 'idle', text: t('agents.side.state.off') }
  if (last?.kind === 'result' && last.ok === false) return { id: 'failed', tone: 'error', text: t('agents.lastFailed', { when: agoText(last.at, lang, t) }) }
  if (!last) return { id: 'idle', tone: 'idle', text: t('agents.neverRun') }
  return { id: 'idle', tone: 'ok', text: t('agents.overview.ran', { when: agoText(last.at, lang, t) }) }
}

/** Settings -> Features -> agents_page (undefined while the settings load). */
export function useAgentsOn(): boolean | undefined {
  const { data: s } = useSettings()
  return s ? !!s.agents_page : undefined
}

/** The page shown when the feature is off. */
export function AgentsOff() {
  const t = useT()
  return (
    <Page title={t('agents.title')} description={t('agents.desc')}>
      <EmptyState
        icon={Bot}
        title={t('agents.off')}
        description={t('agents.offDesc')}
        action={
          <Button asChild>
            <Link to="/settings/features">
              <Settings2 /> {t('agents.turnOn')}
            </Link>
          </Button>
        }
      />
    </Page>
  )
}

/** defaultLabel: what the empty value means when it is not the default model (the conversation: "Same as the runs"). */
export function ModelSelect({ value, onChange, id, defaultLabel }: { value: string; onChange: (v: string) => void; id?: string; defaultLabel?: string }) {
  const t = useT()
  const { data: claude } = useClaudeStatus()
  const models = claude?.models || []
  const options = [
    { value: '__default', label: defaultLabel ? defaultLabel : claude?.default_model ? t('crons.modelDefaultNamed', { model: models.find((m) => m.id === claude.default_model)?.label || claude.default_model }) : t('crons.modelDefault') },
    ...models.map((m) => ({ value: m.id, label: m.label })),
    ...(value && !models.some((m) => m.id === value) ? [{ value, label: value }] : []),
  ]
  return <Select id={id} value={value || '__default'} onValueChange={(v) => onChange(v === '__default' ? '' : v)} options={options} />
}

export function PermissionSelect({ value, onChange, id }: { value: '' | PermissionMode; onChange: (v: '' | PermissionMode) => void; id?: string }) {
  const t = useT()
  return (
    <Select
      id={id}
      value={value || '__inherit'}
      onValueChange={(v) => onChange((v === '__inherit' ? '' : v) as '' | PermissionMode)}
      options={[
        { value: '__inherit', label: t('agents.permInherit') },
        { value: 'acceptEdits', label: t('claude.mode.acceptEdits') },
        { value: 'default', label: t('claude.mode.default') },
        { value: 'bypass', label: t('claude.mode.bypass') },
      ]}
    />
  )
}

/** "acme / blog" of an agent. */
export const whereOf = (a: Pick<Agent, 'project' | 'topic'>) => `${a.project} / ${a.topic}`
/** First line of the role. */
export const firstLine = (s: string) => (s || '').split('\n').map((x) => x.replace(/^#+\s*/, '').trim()).find(Boolean) || ''

/** "$0.42 / $2.00 today" (no budget: "$0.42 today"). */
export function costLine(t: TFn, a: Agent): string {
  const spent = fmtCost(a.cost_today || 0)
  return a.limits.usd_per_day > 0 ? t('agents.costBudget', { spent, budget: fmtCost(a.limits.usd_per_day) }) : t('agents.costToday', { spent })
}

/** The triggers of an agent as chips: its crons, its feed triggers (webhooks included), Telegram. */
export function TriggerChips({ agent, crons, className }: { agent: Agent; crons?: Cron[]; className?: string }) {
  const t = useT()
  const mask = useMask()
  const feed = agent.triggers.filter((x) => x.enabled !== false)
  const chip = 'gap-1 font-normal'
  return (
    <div className={cn('flex flex-wrap gap-1', className)}>
      {(crons || []).filter((c) => c.enabled).map((c) => (
        <Badge key={c.id} variant="secondary" className={chip} title={c.human}>
          <Clock className="size-3" /> <span className="max-w-40 truncate">{mask(c.human || c.schedule, 6)}</span>
        </Badge>
      ))}
      {feed.map((x) => (
        <Badge key={x.id} variant="secondary" className={chip}>
          {x.hook_id ? <Webhook className="size-3" /> : <Rss className="size-3" />}
          <span className="max-w-40 truncate">{x.source ? mask(x.source, 6) : t('agents.trigger.anySource')}</span>
        </Badge>
      ))}
      {agent.telegram && (
        <Badge variant="secondary" className={chip}>
          <Send className="size-3" /> Telegram
        </Badge>
      )}
      {!crons?.length && !feed.length && !agent.telegram && <span className="text-xs text-muted-foreground">{t('agents.trigger.manualOnly')}</span>}
    </div>
  )
}

/** A number field that keeps what is typed ("0.", "0,5", empty) and only hands over a valid number; the text is
 *  rebuilt from the value when it changes from outside, or on blur. */
function NumberInput({ value, onValue, ...rest }: { value: number; onValue: (n: number) => void } & Omit<React.ComponentProps<typeof Input>, 'value' | 'onChange'>) {
  const [text, setText] = React.useState(String(value))
  const typed = React.useRef<number | null>(null)
  const parse = (s: string) => (s.trim() === '' ? NaN : Number(s.replace(',', '.')))
  // Follow the value when it changes from outside (not when it is just what is being typed, even rounded).
  React.useEffect(() => {
    if (typed.current === null) setText(String(value))
  }, [value])
  return (
    <Input
      {...rest}
      inputMode="decimal"
      value={text}
      onChange={(e) => {
        setText(e.target.value)
        const n = parse(e.target.value)
        if (Number.isFinite(n) && n >= 0) {
          typed.current = n
          onValue(n)
        }
      }}
      onBlur={(e) => {
        typed.current = null
        setText(String(value))
        rest.onBlur?.(e)
      }}
    />
  )
}

/** Daily budget, runs per hour, time limit, grouping window. */
export function LimitsFields({ value, onChange }: { value: AgentLimits; onChange: (l: AgentLimits) => void }) {
  const t = useT()
  const num = (k: Exclude<keyof AgentLimits, 'chat_idle_h'>, scale = 1) => ({
    value: Math.round((value[k] / scale) * 100) / 100,
    onValue: (n: number) => onChange({ ...value, [k]: k === 'usd_per_day' ? n : Math.round(n * scale) }),
  })
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <FormField label={t('agents.limits.usd')} hint={t('agents.limits.usdHint')}>
        <NumberInput {...num('usd_per_day')} data-testid="limit-usd" />
      </FormField>
      <FormField label={t('agents.limits.runs')} hint={t('agents.limits.runsHint')}>
        <NumberInput {...num('runs_per_hour')} />
      </FormField>
      <FormField label={t('agents.limits.timeout')} hint={t('agents.limits.timeoutHint')}>
        <NumberInput {...num('timeout_s', 60)} />
      </FormField>
      <FormField label={t('agents.limits.debounce')} hint={t('agents.limits.debounceHint')}>
        <NumberInput {...num('debounce_s')} />
      </FormField>
      {value.chat_idle_h !== undefined && (
        <FormField label={t('agents.limits.chatIdle')} hint={t('agents.limits.chatIdleHint')}>
          <NumberInput value={value.chat_idle_h} onValue={(n) => onChange({ ...value, chat_idle_h: Math.round(n) })} data-testid="limit-chat-idle" />
        </FormField>
      )}
    </div>
  )
}

/** A feed trigger: which source, which levels, which words, what to do. */
export function FeedTriggerFields({ value, onChange, sourceLocked }: { value: AgentTriggerInput; onChange: (v: AgentTriggerInput) => void; sourceLocked?: boolean }) {
  const t = useT()
  const mask = useMask()
  const { data: feed } = useFeedSettings()
  const sources = feed?.sources || []
  const levels = value.levels || []
  const opts = [
    { value: '__any', label: t('agents.trigger.anySource') },
    ...sources.map((s) => ({ value: s.source, label: mask(s.label || s.source, 6) })),
    ...(value.source && !sources.some((s) => s.source === value.source) ? [{ value: value.source, label: mask(value.source, 6) }] : []),
  ]
  return (
    <div className="grid gap-3">
      {!sourceLocked && (
        <FormField label={t('agents.trigger.source')} hint={t('agents.trigger.sourceHint')}>
          <Select value={value.source || '__any'} onValueChange={(v) => onChange({ ...value, source: v === '__any' ? '' : v })} options={opts} />
        </FormField>
      )}
      <div className="grid gap-1.5">
        <span className="text-sm font-medium">{t('agents.trigger.levels')}</span>
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          {FEED_LEVELS.map((l) => (
            <label key={l} className="flex items-center gap-2 text-sm">
              <Checkbox checked={levels.includes(l)} onCheckedChange={(c) => onChange({ ...value, levels: c ? [...levels, l] : levels.filter((x) => x !== l) })} />
              {t(`agents.level.${l}` as 'agents.level.info')}
            </label>
          ))}
        </div>
        <span className="text-xs text-muted-foreground">{t('agents.trigger.levelsHint')}</span>
      </div>
      <FormField label={t('agents.trigger.match')} hint={t('agents.trigger.matchHint')}>
        <Input value={value.match || ''} onChange={(e) => onChange({ ...value, match: e.target.value })} placeholder={t('agents.trigger.matchPlaceholder')} />
      </FormField>
      <FormField label={t('agents.trigger.prompt')} hint={t('agents.trigger.promptHint')}>
        <Textarea minRows={2} maxRows={8} value={value.prompt || ''} onChange={(e) => onChange({ ...value, prompt: e.target.value })} placeholder={t('agents.trigger.promptPlaceholder')} />
      </FormField>
    </div>
  )
}

/** What a feed trigger listens to, in one line. */
export function triggerSummary(t: TFn, x: AgentTrigger): string {
  const parts = [x.source || t('agents.trigger.anySource')]
  if (x.levels?.length) parts.push(x.levels.map((l) => t(`agents.level.${l}` as 'agents.level.info')).join(', '))
  if (x.match) parts.push(t('agents.trigger.matchShort', { match: x.match }))
  return parts.join(' · ')
}

export function WebhookKindSelect({ value, onChange }: { value: AgentWebhookKind; onChange: (v: AgentWebhookKind) => void }) {
  const t = useT()
  return <Select value={value} onValueChange={(v) => onChange(v as AgentWebhookKind)} options={WEBHOOK_KINDS.map((k) => ({ value: k, label: t(`agents.hook.${k}` as 'agents.hook.generic') }))} />
}

/** A webhook just made for an agent: where to paste its URL, and its signing secret for Stripe / Shopify / GitHub. */
export function WebhookMade({ hook }: { hook: AgentWebhookResult['hook'] }) {
  const t = useT()
  const patch = usePatchHook()
  const [secret, setSecret] = React.useState('')
  const [saved, setSaved] = React.useState(hook.has_secret)
  return (
    <div className="grid gap-3" data-testid="agent-hook-made">
      <p className="text-sm text-muted-foreground">{t(`feed.where.${hook.kind}` as TKey)}</p>
      <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2">
        <code className="min-w-0 flex-1 font-mono text-xs break-all" data-testid="agent-hook-url">
          <Sensitive>{hook.url}</Sensitive>
        </code>
        <CopyButton text={hook.url} />
      </div>
      {hook.kind !== 'generic' &&
        (saved ? (
          <Callout tone="success">{t('agents.hook.secretSaved')}</Callout>
        ) : (
          <form
            className="grid gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (secret.trim()) patch.mutate({ id: hook.id, secret: secret.trim() }, { onSuccess: () => setSaved(true) })
            }}
          >
            <FormField label={t('feed.secret')} hint={t(`feed.secretHelp.${hook.kind}` as TKey)}>
              <Input value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={t('feed.secretPlaceholder')} autoComplete="off" />
            </FormField>
            <div>
              <Button type="submit" size="sm" variant="outline" loading={patch.isPending} disabled={!secret.trim()}>
                {t('agents.hook.saveSecret')}
              </Button>
            </div>
          </form>
        ))}
    </div>
  )
}

/** Run an agent now (optional text): a toast says it started (with a link to its session) or why it did not. */
export function useRunNow() {
  const t = useT()
  const run = useRunAgent()
  const navigate = useNavigate()
  const go = React.useCallback(
    (a: Pick<Agent, 'path' | 'display_name'>, text?: string, onDone?: () => void) =>
      run.mutate(
        { path: a.path, text },
        {
          onSuccess: (r) => {
            if (r.started && r.session) {
              const sid = typeof r.session === 'string' ? r.session : r.session.id
              toast.action(t('agents.run.started', { name: a.display_name }), undefined, { label: t('agents.run.open'), onClick: () => navigate(sessionsUrl({ id: sid, path: a.path })) })
            } else if (r.started) toast.success(t('agents.run.queued', { name: a.display_name }))
            else toast.error(t('agents.run.notStarted'), reasonText(t, r.reason))
            onDone?.()
          },
        },
      ),
    [run, t, navigate],
  )
  return { go, pending: run.isPending, vars: run.variables }
}

/** Why a trigger did not start a turn (server reasons: disabled, budget, busy, rate, missing...). */
export function reasonText(t: TFn, reason?: string): string {
  if (reason === 'disabled' || reason === 'budget' || reason === 'busy' || reason === 'rate' || reason === 'missing' || reason === 'depth') return t(`agents.reason.${reason}` as 'agents.reason.budget')
  return reason || ''
}

/** Checkboxes of the Keys vault entries an agent's runs get (plus checked names the vault no longer holds). */
export function KeyChecks({ value, onChange }: { value: string[]; onChange: (keys: string[]) => void }) {
  const t = useT()
  const { data: secrets } = useSecrets()
  const [q, setQ] = React.useState('')
  const names = Array.from(new Set([...(secrets || []).map((x) => x.name), ...value])).sort()
  if (!names.length) return <p className="text-xs text-muted-foreground">{t('agents.settings.keysNone')}</p>
  // A long vault: a filter; the checked keys always show, first.
  const ql = q.trim().toLowerCase()
  const shown = [...value.filter((n) => names.includes(n)).sort(), ...names.filter((n) => !value.includes(n) && (!ql || n.toLowerCase().includes(ql)))]
  return (
    <div className="grid gap-2">
      {names.length > 8 && <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('agents.settings.keysFilter', { count: names.length })} className="h-8 text-[13px]" />}
      <div className="grid max-h-56 gap-1.5 overflow-y-auto sm:grid-cols-2">
      {shown.map((n) => (
        <label key={n} className="flex min-w-0 items-center gap-2 text-[13px]">
          <Checkbox checked={value.includes(n)} onCheckedChange={(v) => onChange(v === true ? [...value, n] : value.filter((k) => k !== n))} />
          <span className="truncate font-mono">{n}</span>
        </label>
      ))}
      </div>
    </div>
  )
}

/** "Continue in Sessions": the run becomes a normal session of the topic (same history, same Claude thread), opened
 *  in Sessions; the run itself stays in the agent's thread. Not while it runs (the server answers 409). */
export function ContinueButton({ agent: a, sid, variant = 'button' }: { agent: Pick<Agent, 'path' | 'running_sessions'>; sid: string; variant?: 'button' | 'link' }) {
  const t = useT()
  const navigate = useNavigate()
  const cont = useContinueRun()
  const running = (a.running_sessions || []).some((s) => s.id === sid)
  const go = () => cont.mutate({ path: a.path, sid }, { onSuccess: ({ session: s }) => navigate(`/sessions?path=${encodeURIComponent(s.path)}&session=${s.id}`) })
  const tip = running ? t('agents.continue.busy') : t('agents.continue.tip')
  if (variant === 'link')
    return (
      <Tooltip content={tip}>
        <button
          type="button"
          onClick={go}
          disabled={running || cont.isPending}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary disabled:opacity-50 disabled:hover:text-muted-foreground pointer-coarse:min-h-10"
          data-testid="agent-continue"
        >
          <MessagesSquare className="size-3" /> {t('agents.continue.button')}
        </button>
      </Tooltip>
    )
  return (
    <Tooltip content={tip}>
      <span>
        <Button size="sm" variant="outline" onClick={go} disabled={running} loading={cont.isPending} data-testid="agent-continue">
          <MessagesSquare /> <span className="max-sm:sr-only">{t('agents.continue.button')}</span>
        </Button>
      </span>
    </Tooltip>
  )
}
