// Settings -> Webhooks (trigger "in": another service calls a URL of the server) and Settings -> Events (trigger
// "event": something happened in Harness). Automations WITHOUT AI, made by Harness from a session (`maxxing
// webhooks`): these pages only show them, switch them, copy the URL, test, replay, and send the user to Harness.
// One chunk (and the i18n group `webhooks`) for both pages.
import * as React from 'react'
import { Link, useNavigate } from 'react-router'
import {
  Bell,
  Bot,
  ChevronRight,
  Clock,
  CreditCard,
  Download,
  GitBranch,
  KeyRound,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Send,
  ShoppingBag,
  Smartphone,
  Trash2,
  Webhook as WebhookIcon,
  Wrench,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { useLang, useT, type TKey } from '@/i18n'
import { cn } from '@/lib/utils'
import { fmtDate, fmtDuration, fmtRelative } from '@/lib/format'
import {
  AGENT_PATH_RE,
  useDeleteHook,
  useDeleteWebhook,
  usePatchHook,
  useReplayWebhookCall,
  useRotateWebhook,
  useSettings,
  useTestHook,
  useTestWebhook,
  useToggleWebhook,
  useWebhookCall,
  useWebhookCalls,
  useWebhookData,
  useWebhookSecret,
  useWebhooks,
  useWorkspace,
  webhookCsvUrl,
} from '@/lib/queries'
import type { FeedHookRef, Webhook, WebhookCallStatus, WebhookRow } from '@/lib/types'
import {
  Badge,
  Button,
  CodeBlock,
  CopyButton,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  SecretInput,
  Sensitive,
  Skeleton,
  Spinner,
  Switch,
  confirm,
  toast,
  useMask,
} from '@/components/ui'
import { Callout } from '@/features/common'
import { draftUrl } from '@/features/agents/EditWithClaude'
import { useHarnessTopic } from '@/pages/settings/sections/harnessTopic'
import { useRegisterCommands } from '@/commands/registry'
import { HookEditor, type HookSeed } from './HookEditor'

type Kind = 'in' | 'event'

export function WebhooksSection() {
  return <HooksPage kind="in" />
}
export function EventsSection() {
  return <HooksPage kind="event" />
}

/* ------------------------------------------------------------------ sessions with Harness */

const INBOX = 'projects/general/topics/inbox'

/** The topic of the sessions these pages start: general/inbox, else another inbox, else the Harness topic. */
function useInboxTopic(): string {
  const { data: ws } = useWorkspace()
  const harness = useHarnessTopic()
  const paths = (ws?.projects ?? []).flatMap((p) => p.topics.map((tp) => tp.path))
  if (!paths.length || paths.includes(INBOX)) return INBOX
  return paths.find((p) => p.endsWith('/topics/inbox')) ?? harness
}

/** Opens a new session draft in the inbox topic with `prompt` written (the user reads it and sends). */
function useAskHarness() {
  const navigate = useNavigate()
  const topic = useInboxTopic()
  return (prompt: string) => navigate(draftUrl(topic, prompt))
}

/* ------------------------------------------------------------------ helpers */

function useNow(ms = 30_000) {
  const [now, setNow] = React.useState(() => Date.now() / 1000)
  React.useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

/** The configured time zone (times are shown in it, as on the Crons page). */
function useTz() {
  return useSettings().data?.timezone
}

const agentPage = (path: string) => {
  const m = AGENT_PATH_RE.exec(path)
  return m ? `/agents/${m[1]}/${m[2]}/${m[3]}` : null
}
const agentName = (path: string) => path.split('/').pop() || path

const SOURCE_ICON: Record<string, LucideIcon> = { stripe: CreditCard, shopify: ShoppingBag, github: GitBranch, phone: Smartphone, generic: WebhookIcon }
const EVENT_ICON: Record<string, LucideIcon> = { feed: Bell, agent: Bot, cron: Clock }
const iconOf = (h: Webhook): LucideIcon => (h.trigger.kind === 'in' ? SOURCE_ICON[h.trigger.source] || WebhookIcon : EVENT_ICON[h.trigger.on] || Zap)

/** The hook's sentence: the one Harness wrote, else one made here from its trigger and action. */
function useSentence() {
  const t = useT()
  return (h: Webhook) => {
    if (h.description) return h.description
    const tr = h.trigger
    let when: string
    if (tr.kind === 'in') when = t(`webhooks.when.${tr.source}` as TKey)
    else if (tr.on === 'feed') when = tr.source ? t('webhooks.when.feedFrom', { source: tr.source }) : t('webhooks.when.feed')
    else {
      const who = tr.on === 'agent' ? tr.agent && agentName(tr.agent) : tr.cron
      const fail = tr.when === 'fail'
      const key = `webhooks.when.${tr.on}${who ? 'One' : ''}${fail ? 'Fail' : ''}` as TKey
      when = t(key, { name: who || '' })
    }
    const a = h.action
    const what =
      a.kind === 'shell'
        ? t('webhooks.do.shell', { command: a.command.length > 60 ? `${a.command.slice(0, 60)}…` : a.command })
        : a.kind === 'call'
          ? t('webhooks.do.call', { url: a.url.replace(/^https?:\/\//, '').replace(/[/?].*$/, '') })
          : t(`webhooks.do.${a.kind}` as TKey)
    return t('webhooks.sentence', { when, what })
  }
}

type Tone = 'success' | 'destructive' | 'warning' | 'muted' | 'secondary'
const CALL_TONE: Record<WebhookCallStatus, Tone> = { ok: 'success', failed: 'destructive', ignored: 'muted', queued: 'secondary', running: 'secondary' }

function CallBadge({ status, className }: { status: WebhookCallStatus; className?: string }) {
  const t = useT()
  return (
    <Badge variant={CALL_TONE[status]} className={cn('gap-1 font-normal', className)}>
      {status === 'running' && <Spinner className="size-3" />}
      {t(`webhooks.status.${status}` as TKey)}
    </Badge>
  )
}

/** The state of a hook in one badge: secret missing, waiting calls, the last call. */
function HookState({ hook, kind }: { hook: Webhook; kind: Kind }) {
  const t = useT()
  if (hook.needs_secret)
    return (
      <Badge variant="warning" className="gap-1 font-normal">
        <KeyRound className="size-3" />
        {t('webhooks.needsSecret')}
      </Badge>
    )
  const last = hook.last_call
  if (hook.waiting > 0 && last?.status !== 'running')
    return (
      <Badge variant="secondary" className="font-normal">
        {t('webhooks.waiting', { count: hook.waiting })}
      </Badge>
    )
  if (!last) return <Badge variant="muted" className="font-normal">{kind === 'in' ? t('webhooks.neverCalled') : t('webhooks.neverTriggered')}</Badge>
  if (last.status === 'ok' && hook.data)
    return (
      <Badge variant="success" className="font-normal">
        {t('webhooks.today', { count: hook.data.today })}
      </Badge>
    )
  return <CallBadge status={last.status} />
}

/** Seven bars: the rows added each of the last 7 days (store hooks). */
function Sparkline({ days }: { days: number[] }) {
  const t = useT()
  const max = Math.max(1, ...days)
  return (
    <span role="img" aria-label={t('webhooks.last7', { list: days.join(', ') })} className="inline-flex h-4 items-end gap-px">
      {days.map((n, i) => (
        <span key={i} className={cn('w-1 rounded-[1px]', n ? 'bg-primary' : 'bg-muted')} style={{ height: `${Math.max(12, (n / max) * 100)}%` }} />
      ))}
    </span>
  )
}

/* ------------------------------------------------------------------ the page */

function HooksPage({ kind }: { kind: Kind }) {
  const t = useT()
  const q = useWebhooks()
  const now = useNow()
  const [open, setOpen] = React.useState<string | null>(null)
  const hooks = (q.data?.hooks ?? []).filter((h) => h.trigger.kind === kind)
  const feedHooks = kind === 'in' ? (q.data?.feed_hooks ?? []) : []
  const [seed, setSeed] = React.useState<HookSeed | null>(null)
  const add = () => setSeed({ mode: 'new', kind })
  const edit = (h: Webhook) => setSeed({ mode: 'edit', kind, hook: h })
  const newLabel = t(kind === 'in' ? 'webhooks.new' : 'webhooks.newEvent')
  useRegisterCommands(`webhooks.${kind}`, [{ id: `webhooks.new.${kind}`, title: newLabel, group: t(kind === 'in' ? 'nav.webhooks' : 'nav.events'), icon: Plus, perform: ({ close }) => (close(), add()) }], [newLabel, kind])
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <div className="-mt-3 flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 flex-1 basis-64 text-sm text-muted-foreground">
          {t(kind === 'in' ? 'webhooks.noAi' : 'webhooks.noAiEvents')}{' '}
          <Link to="/agents" className="font-medium text-primary underline-offset-4 hover:underline">
            {t('webhooks.useAgent')}
          </Link>
        </p>
        <Button onClick={add} data-testid="hook-new" data-tour="webhooks-new">
          <Plus />
          {newLabel}
        </Button>
      </div>
      {q.isError && !q.data ? (
        <EmptyState
          tone="error"
          icon={kind === 'in' ? WebhookIcon : Zap}
          title={t('webhooks.loadError')}
          description={q.error.message}
          action={
            <Button variant="outline" onClick={() => q.refetch()}>
              {t('common.retry')}
            </Button>
          }
        />
      ) : !q.data ? (
        <div className="divide-y rounded-xl border" aria-hidden>
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-3 p-4">
              <Skeleton className="size-8 rounded-lg" />
              <div className="grid flex-1 gap-2">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3.5 w-72 max-w-full" />
              </div>
              <Skeleton className="h-5 w-9 rounded-full" />
            </div>
          ))}
        </div>
      ) : hooks.length === 0 && feedHooks.length === 0 ? (
        <div className="rounded-xl border">
          <EmptyState
            icon={kind === 'in' ? WebhookIcon : Zap}
            title={t(kind === 'in' ? 'webhooks.empty' : 'webhooks.emptyEvents')}
            description={t('webhooks.emptyDesc')}
            action={
              <Button onClick={add}>
                <Plus />
                {newLabel}
              </Button>
            }
          />
        </div>
      ) : (
        <ul className="divide-y overflow-hidden rounded-xl border bg-card" data-testid={kind === 'in' ? 'webhook-list' : 'event-list'}>
          {hooks.map((h) => (
            <HookRow key={h.id} hook={h} kind={kind} now={now} https={q.data.https} open={open === h.id} onOpen={() => setOpen((o) => (o === h.id ? null : h.id))} onEdit={edit} />
          ))}
          {feedHooks.map((h) => (
            <FeedHookRow key={h.id} hook={h} https={q.data.https} open={open === h.id} onOpen={() => setOpen((o) => (o === h.id ? null : h.id))} />
          ))}
        </ul>
      )}
      <HookEditor seed={seed} onOpenChange={(o) => !o && setSeed(null)} />
    </div>
  )
}

/* ------------------------------------------------------------------ one hook */

function HookRow({ hook, kind, now, https, open, onOpen, onEdit }: { hook: Webhook; kind: Kind; now: number; https: boolean; open: boolean; onOpen: () => void; onEdit: (h: Webhook) => void }) {
  const t = useT()
  const lang = useLang()
  const tz = useTz()
  const sentence = useSentence()
  const toggle = useToggleWebhook()
  const ask = useAskHarness()
  const Icon = iconOf(hook)
  const last = hook.last_call
  const failed = last?.status === 'failed'
  const fix = () => ask(t(kind === 'in' ? 'webhooks.fixPrompt' : 'webhooks.fixPromptEvent', { name: hook.name, id: hook.id, call: last?.id || '', error: last?.error || last?.summary || '' }))
  const when = last && (
    <span className="text-xs text-muted-foreground tabular-nums" title={fmtDate(last.at, lang, tz)}>
      {fmtRelative(last.at, lang, now)}
    </span>
  )
  const fixLink = failed && (
    <button type="button" onClick={fix} className="text-xs font-medium text-primary underline-offset-4 outline-none hover:underline focus-visible:underline pointer-coarse:py-1">
      {t('webhooks.fix')}
    </button>
  )
  return (
    <li className={cn('grid', open && 'bg-fill-1')} data-hook-id={hook.id}>
      <div className={cn('flex items-start gap-3 px-4 py-3 transition-colors', !open && 'hover:bg-muted', !hook.enabled && 'opacity-70')}>
        <button type="button" onClick={onOpen} aria-expanded={open} className="flex min-w-0 flex-1 items-start gap-3 rounded text-left outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border bg-muted text-muted-foreground">
            <Icon className="size-4" />
          </span>
          <span className="grid min-w-0 flex-1 gap-0.5">
            <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <span className="truncate text-sm font-medium">
                <Sensitive length={8}>{hook.name}</Sensitive>
              </span>
              {hook.owner?.startsWith('agent:') && (
                <Badge variant="muted" className="gap-1 font-normal">
                  <Bot className="size-3" />
                  {t('webhooks.byAgent')}
                </Badge>
              )}
            </span>
            <span className="text-[13px] break-words text-muted-foreground">
              <Sensitive length={14}>{sentence(hook)}</Sensitive>
            </span>
            {/* phones: the state under the sentence */}
            <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 sm:hidden">
              <HookState hook={hook} kind={kind} />
              {hook.data && <Sparkline days={hook.data.days} />}
              {when}
            </span>
          </span>
        </button>
        <div className="flex shrink-0 items-center gap-3">
          <div className="grid justify-items-end gap-1 max-sm:hidden">
            <span className="flex items-center gap-2">
              {hook.data && <Sparkline days={hook.data.days} />}
              <HookState hook={hook} kind={kind} />
            </span>
            <span className="flex items-center gap-1.5">
              {when}
              {fixLink && <span aria-hidden className="text-xs text-muted-foreground">·</span>}
              {fixLink}
            </span>
          </div>
          <Switch
            checked={hook.enabled}
            onCheckedChange={(v) => toggle.mutate({ id: hook.id, enabled: v })}
            aria-label={hook.enabled ? t('webhooks.turnOff') : t('webhooks.turnOn')}
            className="mt-1.5 sm:mt-0"
          />
          <ChevronRight aria-hidden className={cn('size-4 text-muted-foreground transition-transform max-sm:hidden', open && 'rotate-90')} />
        </div>
      </div>
      {open && <HookDetails hook={hook} kind={kind} now={now} https={https} onFix={failed ? fix : undefined} onEdit={hook.owner ? undefined : () => onEdit(hook)} />}
    </li>
  )
}

function HookDetails({ hook, kind, now, https, onFix, onEdit }: { hook: Webhook; kind: Kind; now: number; https: boolean; onFix?: () => void; onEdit?: () => void }) {
  const t = useT()
  const test = useTestWebhook()
  const rotate = useRotateWebhook()
  const del = useDeleteWebhook()
  const [secret, setSecret] = React.useState(false)
  const newUrl = async () => {
    if (await confirm({ title: t('webhooks.rotateTitle'), description: t('webhooks.rotateDesc'), confirmText: t('webhooks.rotate'), destructive: true }))
      rotate.mutate(hook.id, { onSuccess: () => toast.success(t('webhooks.rotated')) })
  }
  const remove = async () => {
    if (await confirm({ title: t('webhooks.removeTitle', { name: hook.name }), description: t('webhooks.removeDesc'), confirmText: t('common.delete'), destructive: true })) del.mutate(hook.id)
  }
  return (
    <div className="mx-unfold grid gap-4 px-4 pb-4 sm:pl-15">
      {hook.needs_secret && (
        <Callout
          tone="warning"
          action={
            <Button size="sm" variant="outline" onClick={() => setSecret(true)}>
              <KeyRound />
              {t('webhooks.setSecret')}
            </Button>
          }
        >
          {t('webhooks.needsSecretDesc')}
        </Callout>
      )}
      {kind === 'in' && hook.url && (
        <div className="grid gap-1.5">
          <div className="flex min-w-0 items-center gap-2 rounded-md border bg-background py-1 pr-1 pl-3 font-mono text-[13px]">
            <span className="min-w-0 flex-1 truncate select-all">
              <Sensitive length={24}>{hook.url}</Sensitive>
            </span>
            <CopyButton text={hook.url} label={t('webhooks.copyUrl')} />
          </div>
          {!https && <p className="text-xs text-warning">{t('webhooks.notHttps')}</p>}
        </div>
      )}
      <CallList hook={hook} now={now} />
      {hook.data && <DataTable hook={hook} />}
      <div className="flex flex-wrap items-center gap-2">
        {onFix && (
          <Button size="sm" onClick={onFix}>
            <Wrench />
            {t('webhooks.fix')}
          </Button>
        )}
        {onEdit && (
          <Button size="sm" variant="secondary" onClick={onEdit}>
            <Pencil />
            {t('webhooks.edit')}
          </Button>
        )}
        <Button size="sm" variant="secondary" loading={test.isPending} onClick={() => test.mutate(hook.id, { onSuccess: () => toast.success(t('webhooks.testSent')) })}>
          <Send />
          {t('webhooks.test')}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" aria-label={t('common.more')}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {kind === 'in' && (
              <>
                <DropdownMenuItem onSelect={newUrl}>
                  <RefreshCw />
                  {t('webhooks.rotate')}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => setSecret(true)}>
                  <KeyRound />
                  {hook.has_secret ? t('webhooks.changeSecret') : t('webhooks.setSecret')}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
              </>
            )}
            <DropdownMenuItem destructive onSelect={remove}>
              <Trash2 />
              {t('common.delete')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {secret && <SecretDialog hook={hook} onClose={() => setSecret(false)} />}
    </div>
  )
}

/* ------------------------------------------------------------------ calls */

function CallList({ hook, now }: { hook: Webhook; now: number }) {
  const t = useT()
  const lang = useLang()
  const q = useWebhookCalls(hook.id, 10)
  const tz = useTz()
  const replay = useReplayWebhookCall()
  const [shown, setShown] = React.useState<string | null>(null)
  if (q.isPending)
    return (
      <div className="grid gap-1.5" aria-hidden>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-9" />
        ))}
      </div>
    )
  if (q.isError)
    return (
      <Callout
        tone="error"
        action={
          <Button size="sm" variant="outline" onClick={() => q.refetch()}>
            {t('common.retry')}
          </Button>
        }
      >
        {t('webhooks.callsError')}
      </Callout>
    )
  const calls = q.data.calls
  return (
    <div className="grid gap-1.5">
      <h3 className="text-xs font-medium text-muted-foreground">{t('webhooks.lastCalls')}</h3>
      {!calls.length ? (
        <p className="text-[13px] text-muted-foreground">{t('webhooks.noCalls')}</p>
      ) : (
        <ul className="divide-y rounded-lg border bg-card">
          {calls.map((c) => (
            <li key={c.id} className="flex items-center gap-1 pr-1">
              <button
                type="button"
                onClick={() => setShown(c.id)}
                className="flex min-h-10 min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-0.5 rounded-md py-1.5 pl-3 text-left text-[13px] outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
              >
                <span className="w-16 shrink-0 text-muted-foreground tabular-nums" title={fmtDate(c.at, lang, tz)}>
                  {c.at > now - 86400 ? fmtDate(c.at, lang, tz, { dateStyle: undefined, timeStyle: 'short' }) : fmtRelative(c.at, lang, now)}
                </span>
                <span className="min-w-0 flex-1 basis-32 truncate">
                  <Sensitive length={10}>{c.summary || c.event || t(`webhooks.trigger.${c.trigger}` as TKey)}</Sensitive>
                  {(c.trigger === 'test' || c.trigger === 'replay') && (
                    <Badge variant="outline" className="ml-1.5 align-middle font-normal">
                      {t(`webhooks.trigger.${c.trigger}` as TKey)}
                    </Badge>
                  )}
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  {c.duration_s != null && <span className="text-xs text-muted-foreground tabular-nums">{fmtDuration(c.duration_s)}</span>}
                  <CallBadge status={c.status} />
                </span>
              </button>
              <Button
                size="sm"
                variant="ghost"
                className="shrink-0 px-2 text-muted-foreground"
                aria-label={t('webhooks.replay')}
                disabled={c.status === 'queued' || c.status === 'running'}
                onClick={() => replay.mutate({ id: hook.id, call: c.id }, { onSuccess: () => toast.success(t('webhooks.replayed')) })}
              >
                <RotateCcw />
                <span className="max-sm:hidden">{t('webhooks.replay')}</span>
              </Button>
            </li>
          ))}
        </ul>
      )}
      {shown && <CallDialog hook={hook} call={shown} onClose={() => setShown(null)} />}
    </div>
  )
}

const pretty = (s: string) => {
  try {
    return JSON.stringify(JSON.parse(s), null, 2)
  } catch {
    return s
  }
}
const sizeOf = (n: number) => (n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} kB` : `${(n / 1024 / 1024).toFixed(1)} MB`)

function CallDialog({ hook, call, onClose }: { hook: Webhook; call: string; onClose: () => void }) {
  const t = useT()
  const lang = useLang()
  const tz = useTz()
  const q = useWebhookCall(hook.id, call)
  const replay = useReplayWebhookCall()
  const c = q.data
  const req = c?.request
  const headers = req?.headers && Object.keys(req.headers).length ? JSON.stringify(req.headers, null, 2) : ''
  const query = req?.query && Object.keys(req.query).length ? JSON.stringify(req.query, null, 2) : ''
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="md:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {t('webhooks.call')}
            {c && <CallBadge status={c.status} />}
          </DialogTitle>
          <DialogDescription>{c ? fmtDate(c.at, lang, tz) : ' '}</DialogDescription>
        </DialogHeader>
        {q.isError ? (
          <Callout tone="error">{q.error.message}</Callout>
        ) : !c ? (
          <div className="grid gap-2" aria-hidden>
            <Skeleton className="h-24" />
            <Skeleton className="h-40" />
          </div>
        ) : (
          <div className="grid min-w-0 gap-4">
            <dl className="grid grid-cols-[minmax(88px,auto)_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[13px]">
              {c.summary && (
                <>
                  <dt className="text-muted-foreground">{t('webhooks.field.summary')}</dt>
                  <dd className="min-w-0 break-words">
                    <Sensitive length={10}>{c.summary}</Sensitive>
                  </dd>
                </>
              )}
              <dt className="text-muted-foreground">{t('webhooks.field.trigger')}</dt>
              <dd>{t(`webhooks.trigger.${c.trigger}` as TKey)}</dd>
              {req?.method && (
                <>
                  <dt className="text-muted-foreground">{t('webhooks.field.request')}</dt>
                  <dd className="min-w-0 font-mono break-all">
                    {req.method}
                    {req.content_type ? ` · ${req.content_type}` : ''}
                    {req.size != null ? ` · ${sizeOf(req.size)}` : ''}
                  </dd>
                </>
              )}
              {(c.event || req?.event) && (
                <>
                  <dt className="text-muted-foreground">{t('webhooks.field.event')}</dt>
                  <dd className="min-w-0 font-mono break-all">
                    <Sensitive length={8}>{c.event || req?.event}</Sensitive>
                  </dd>
                </>
              )}
              {(c.duration_s != null || c.http != null || c.exit != null) && (
                <>
                  <dt className="text-muted-foreground">{t('webhooks.field.result')}</dt>
                  <dd className="tabular-nums">
                    {[c.duration_s != null && fmtDuration(c.duration_s), c.http != null && `HTTP ${c.http}`, c.exit != null && t('webhooks.exit', { code: c.exit }), (c.attempts || 0) > 1 && t('webhooks.attempts', { count: c.attempts || 0 })]
                      .filter(Boolean)
                      .join(' · ')}
                  </dd>
                </>
              )}
            </dl>
            {c.error && <Callout tone="error">{c.error}</Callout>}
            {headers && <Block title={t('webhooks.field.headers')} code={headers} />}
            {query && <Block title={t('webhooks.field.query')} code={query} />}
            {!!req?.files?.length && (
              <div className="grid gap-1.5">
                <h3 className="text-xs font-medium text-muted-foreground">{t('webhooks.field.files')}</h3>
                <ul className="grid gap-1 text-[13px]">
                  {req.files.map((f) => (
                    <li key={f.path} className="flex min-w-0 items-center gap-2">
                      <span className="min-w-0 truncate font-mono">
                        <Sensitive length={10}>{f.name}</Sensitive>
                      </span>
                      <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{sizeOf(f.size)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {c.body != null && c.body !== '' && <Block title={c.body_truncated ? t('webhooks.field.bodyCut') : t('webhooks.field.body')} code={pretty(c.body)} />}
            {c.output && <Block title={t('webhooks.field.output')} code={c.output} />}
          </div>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.close')}
          </Button>
          <Button
            disabled={!c || c.status === 'queued' || c.status === 'running'}
            loading={replay.isPending}
            onClick={() =>
              replay.mutate(
                { id: hook.id, call },
                {
                  onSuccess: () => {
                    toast.success(t('webhooks.replayed'))
                    onClose()
                  },
                },
              )
            }
          >
            <RotateCcw />
            {t('webhooks.replay')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Block({ title, code }: { title: string; code: string }) {
  return (
    <div className="grid min-w-0 gap-1.5">
      <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
      <Sensitive block className="h-16">
        <CodeBlock code={code} className="max-h-72 overflow-y-auto [&_pre]:break-all [&_pre]:whitespace-pre-wrap" />
      </Sensitive>
    </div>
  )
}

/* ------------------------------------------------------------------ store hooks: their table */

const cell = (v: unknown) => (v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v))

function DataTable({ hook }: { hook: Webhook }) {
  const t = useT()
  const lang = useLang()
  const tz = useTz()
  const q = useWebhookData(hook.id, 20)
  const rows = React.useMemo(() => [...(q.data?.rows ?? [])].reverse(), [q.data])
  const cols = React.useMemo(() => {
    const out: string[] = []
    for (const r of rows) {
      const src = r.fields ?? (r.data && typeof r.data === 'object' && !Array.isArray(r.data) ? (r.data as Record<string, unknown>) : {})
      for (const [k, v] of Object.entries(src)) if (!out.includes(k) && (r.fields || v == null || typeof v !== 'object')) out.push(k)
      if (out.length >= 5) break
    }
    return out.slice(0, 5)
  }, [rows])
  const valueOf = (r: WebhookRow, k: string) => cell(r.fields ? r.fields[k] : (r.data as Record<string, unknown> | null)?.[k])
  return (
    <div className="grid gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-medium text-muted-foreground">{t('webhooks.rows', { count: hook.data?.rows ?? 0 })}</h3>
        <a
          href={webhookCsvUrl(hook.id)}
          download
          className="inline-flex items-center gap-1 text-xs font-medium text-primary underline-offset-4 outline-none hover:underline focus-visible:underline pointer-coarse:py-2"
        >
          <Download className="size-3.5" />
          {t('webhooks.csv')}
        </a>
      </div>
      {q.isPending ? (
        <Skeleton className="h-28" />
      ) : !rows.length ? (
        <p className="text-[13px] text-muted-foreground">{t('webhooks.noRows')}</p>
      ) : (
        <div className="max-h-80 overflow-auto rounded-lg border bg-card">
          <Sensitive block className="h-24">
            <table className="w-full text-left text-[13px]">
              <thead className="sticky top-0 bg-card text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="px-3 py-1.5 font-medium whitespace-nowrap">{t('webhooks.at')}</th>
                  {cols.length ? (
                    cols.map((k) => (
                      <th key={k} className="px-3 py-1.5 font-medium whitespace-nowrap">
                        {k}
                      </th>
                    ))
                  ) : (
                    <th className="px-3 py-1.5 font-medium">{t('webhooks.data')}</th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y">
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="px-3 py-1.5 whitespace-nowrap text-muted-foreground tabular-nums">{fmtDate(r.at, lang, tz, { dateStyle: 'short', timeStyle: 'short' })}</td>
                    {cols.length ? (
                      cols.map((k) => (
                        <td key={k} className="max-w-56 truncate px-3 py-1.5" title={valueOf(r, k)}>
                          {valueOf(r, k)}
                        </td>
                      ))
                    ) : (
                      <td className="max-w-96 truncate px-3 py-1.5 font-mono text-xs">{cell(r.data)}</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </Sensitive>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ the signing secret */

function SecretDialog({ hook, onClose }: { hook: Webhook; onClose: () => void }) {
  const t = useT()
  const [v, setV] = React.useState('')
  const save = useWebhookSecret(hook.id, t('webhooks.secretSaved'))
  const source = hook.trigger.kind === 'in' ? hook.trigger.source : 'generic'
  const help = source === 'phone' ? t('webhooks.secretHelpPhone') : t(`feed.secretHelp.${source}` as TKey)
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('webhooks.secretTitle', { name: hook.name })}</DialogTitle>
          <DialogDescription>{help}</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (v.trim()) save.mutate(v.trim(), { onSuccess: onClose })
          }}
        >
          <SecretInput value={v} onChange={(e) => setV(e.target.value)} placeholder={t('webhooks.secretPlaceholder')} autoFocus />
          <DialogFooter>
            {hook.has_secret && (
              <Button type="button" variant="ghost" className="sm:mr-auto" onClick={() => save.mutate('', { onSuccess: onClose })}>
                {t('webhooks.removeSecret')}
              </Button>
            )}
            <Button type="button" variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={!v.trim()} loading={save.isPending}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/* ------------------------------------------------------------------ the notification webhooks */

// Webhooks of the notifications feed (feedhooks: Stripe, Shopify, GitHub, JSON -> one feed event each), made by
// Harness or by an agent (trigger "webhook"). Same list as the others; an agent's one is managed in the agent.
const FEED_KIND: Record<string, string> = { stripe: 'Stripe', shopify: 'Shopify', github: 'GitHub', generic: 'JSON' }
const SIGNED = ['stripe', 'shopify', 'github']

function FeedHookRow({ hook, https, open, onOpen }: { hook: FeedHookRef; https: boolean; open: boolean; onOpen: () => void }) {
  const t = useT()
  const mask = useMask()
  const page = hook.agent ? agentPage(hook.agent) : null
  const needsSecret = SIGNED.includes(hook.kind) && !hook.has_secret
  const agentBadge = hook.agent && (
    <Badge variant="muted" className="gap-1 font-normal">
      <Bot className="size-3" />
      {t('webhooks.byAgent')}
    </Badge>
  )
  return (
    <li className={cn('grid', open && 'bg-fill-1')} data-hook-id={hook.id} data-testid="feed-hook">
      <div className={cn('flex items-start gap-3 px-4 py-3 transition-colors', !open && 'hover:bg-muted')}>
        <button type="button" onClick={onOpen} aria-expanded={open} className="flex min-w-0 flex-1 items-start gap-3 rounded text-left outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border bg-muted text-muted-foreground">
            {hook.agent ? <Bot className="size-4" /> : <Bell className="size-4" />}
          </span>
          <span className="grid min-w-0 flex-1 gap-0.5">
            <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <span className="truncate text-sm font-medium">
                <Sensitive length={8}>{hook.name}</Sensitive>
              </span>
              <Badge variant="muted" className="shrink-0 font-normal">
                {FEED_KIND[hook.kind] || hook.kind}
              </Badge>
              {agentBadge}
            </span>
            <span className="text-[13px] break-words text-muted-foreground">
              {hook.agent ? t('webhooks.feedSentenceAgent', { name: mask(agentName(hook.agent), 6) }) : t('webhooks.feedSentence')}
            </span>
            {needsSecret && <span className="text-xs text-warning">{t('webhooks.needsSecret')}</span>}
          </span>
        </button>
        <ChevronRight aria-hidden className={cn('mt-2 size-4 shrink-0 text-muted-foreground transition-transform max-sm:hidden', open && 'rotate-90')} />
      </div>
      {open && <FeedHookDetails hook={hook} https={https} page={page} needsSecret={needsSecret} />}
    </li>
  )
}

function FeedHookDetails({ hook, https, page, needsSecret }: { hook: FeedHookRef; https: boolean; page: string | null; needsSecret: boolean }) {
  const t = useT()
  const test = useTestHook()
  const patch = usePatchHook()
  const del = useDeleteHook()
  const [secret, setSecret] = React.useState(false)
  const newUrl = async () => {
    if (await confirm({ title: t('webhooks.rotateTitle'), description: t('webhooks.rotateDesc'), confirmText: t('webhooks.rotate'), destructive: true }))
      patch.mutate({ id: hook.id, regenerate: true }, { onSuccess: () => toast.success(t('webhooks.rotated')) })
  }
  const remove = async () => {
    if (await confirm({ title: t('webhooks.removeTitle', { name: hook.name }), description: t('feed.deleteHookDesc'), confirmText: t('common.delete'), destructive: true })) del.mutate(hook.id)
  }
  return (
    <div className="mx-unfold grid gap-4 px-4 pb-4 sm:pl-15">
      {needsSecret && (
        <Callout
          tone="warning"
          action={
            <Button size="sm" variant="outline" onClick={() => setSecret(true)}>
              <KeyRound />
              {t('webhooks.setSecret')}
            </Button>
          }
        >
          {t('feed.noSecretWarn')}
        </Callout>
      )}
      <div className="grid gap-1.5">
        <div className="flex min-w-0 items-center gap-2 rounded-md border bg-background py-1 pr-1 pl-3 font-mono text-[13px]">
          <span className="min-w-0 flex-1 truncate select-all">
            <Sensitive length={24}>{hook.url}</Sensitive>
          </span>
          <CopyButton text={hook.url} label={t('webhooks.copyUrl')} />
        </div>
        {!https && <p className="text-xs text-warning">{t('webhooks.notHttps')}</p>}
        <p className="text-xs text-muted-foreground">{t(`feed.where.${hook.kind}` as TKey)}</p>
      </div>
      <p className="text-[13px] text-muted-foreground">
        {t('webhooks.feedCalls')}{' '}
        <Link to="/feed" className="font-medium text-primary underline-offset-4 hover:underline">
          {t('webhooks.feedCallsTo')}
        </Link>
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {page && (
          <Button size="sm" variant="secondary" asChild>
            <Link to={page}>
              <Bot />
              {t('webhooks.manageInAgent')}
            </Link>
          </Button>
        )}
        <Button size="sm" variant="secondary" loading={test.isPending} onClick={() => test.mutate(hook.id, { onSuccess: () => toast.success(t('webhooks.testSent')) })}>
          <Send />
          {t('webhooks.test')}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" aria-label={t('common.more')}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem onSelect={newUrl}>
              <RefreshCw />
              {t('webhooks.rotate')}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setSecret(true)}>
              <KeyRound />
              {hook.has_secret ? t('webhooks.changeSecret') : t('webhooks.setSecret')}
            </DropdownMenuItem>
            {!hook.agent && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem destructive onSelect={remove}>
                  <Trash2 />
                  {t('common.delete')}
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {secret && <FeedSecretDialog hook={hook} onClose={() => setSecret(false)} />}
    </div>
  )
}

function FeedSecretDialog({ hook, onClose }: { hook: FeedHookRef; onClose: () => void }) {
  const t = useT()
  const patch = usePatchHook()
  const [v, setV] = React.useState('')
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('feed.secretTitle', { name: hook.name })}</DialogTitle>
          <DialogDescription>{t(`feed.secretHelp.${hook.kind}` as TKey)}</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            patch.mutate({ id: hook.id, secret: v.trim() }, { onSuccess: onClose })
          }}
        >
          <SecretInput value={v} onChange={(e) => setV(e.target.value)} placeholder={t('webhooks.secretPlaceholder')} autoFocus />
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={!v.trim()} loading={patch.isPending}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
