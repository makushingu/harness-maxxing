import * as React from 'react'
import { Bot, Check, ExternalLink, Link2, RefreshCw, Send, Smartphone, Timer } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { useTelegram, useTelegramLink, useTelegramLinkStart, useTelegramRemoveWebhook, useTelegramSync, useTelegramToken, qk } from '@/lib/queries'
import { ApiError, errorMessage } from '@/lib/api'
import type { TelegramLink, TelegramStatus, TelegramSyncResult } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Button, CodeBlock, FormField, SecretInput, Sensitive, Skeleton, Spinner, toast } from '@/components/ui'
import { QRCode } from '@/components/ui/qr-code'
import { Callout, Steps } from '../common'

export type TelegramStage = 'token' | 'link' | 'done'

/** Done once a chat is linked: threads are a bonus (off when the bot has no BotFather "Threaded Mode" -> notice). */
export function telegramStage(s: TelegramStatus | undefined): TelegramStage {
  if (!s || !s.bot) return 'token'
  if (!s.chat) return 'link'
  return 'done'
}

/** The bot token was revoked (401): the poller stopped, a new token is needed. */
export const tokenRejected = (s: TelegramStatus | undefined) => s?.poll_error_code === 'token_rejected'

function SubSteps({ stage, threadsOk }: { stage: TelegramStage; threadsOk: boolean }) {
  const t = useT()
  const idx = stage === 'token' ? 0 : stage === 'link' ? 1 : threadsOk ? 3 : 2
  const labels = [t('telegram.sub.bot'), t('telegram.sub.link'), t('telegram.sub.threads')]
  return (
    <ol className="flex items-center gap-2 text-[13px]">
      {labels.map((l, i) => (
        <li key={l} className="flex items-center gap-2">
          <span
            className={cn(
              'flex size-5 items-center justify-center rounded-full border text-[11px] font-semibold',
              i < idx ? 'border-success bg-success text-background' : i === idx ? 'border-primary text-primary' : 'text-muted-foreground',
            )}
          >
            {i < idx ? <Check className="size-3" strokeWidth={3} /> : i + 1}
          </span>
          <span className={cn(i === idx ? 'font-medium' : 'text-muted-foreground')}>{l}</span>
          {i < labels.length - 1 && <span className="h-px w-4 bg-border sm:w-8" />}
        </li>
      ))}
    </ol>
  )
}

const SETUP_ERRORS = ['conflict', 'webhook_check_failed', 'unreachable'] as const

/** Token field: verify + store. A webhook set by another program can be removed from here, then the token saved again. */
export function TokenForm({ onDone, onCancel, autoFocus }: { onDone?: () => void; onCancel?: () => void; autoFocus?: boolean }) {
  const t = useT()
  const [token, setToken] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const [webhook, setWebhook] = React.useState(false)
  const save = useTelegramToken()
  const unhook = useTelegramRemoveWebhook()
  const submit = (tok: string) => {
    setError(null)
    setWebhook(false)
    save.mutate(tok, {
      onSuccess: (r) => {
        if (!r.ok) return setError(r.error || t('telegram.tokenInvalid'))
        setToken('')
        onDone?.()
      },
      onError: (e) => {
        const code = e instanceof ApiError ? e.code : ''
        if (code === 'webhook_set') return setWebhook(true)
        const known = SETUP_ERRORS.find((c) => c === code)
        setError(known ? t(`telegram.err.${known}`) : errorMessage(e))
      },
    })
  }
  return (
    <form
      className="grid gap-4"
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        if (!token.trim()) return setError(t('telegram.tokenRequired'))
        submit(token.trim())
      }}
    >
      <FormField label={t('telegram.token')} error={error || undefined} hint={t('telegram.tokenHint')}>
        <SecretInput value={token} autoFocus={autoFocus} onChange={(e) => setToken(e.target.value)} placeholder="123456789:AA…" />
      </FormField>
      {webhook && (
        <Callout
          tone="warning"
          className="mx-unfold"
          title={t('telegram.err.webhook_set')}
          action={
            <Button
              type="button"
              size="sm"
              loading={unhook.isPending || save.isPending}
              onClick={() =>
                unhook.mutate(token.trim(), {
                  onSuccess: () => submit(token.trim()),
                  onError: (e) => {
                    setWebhook(false)
                    setError(errorMessage(e))
                  },
                })
              }
            >
              {t('telegram.removeWebhook')}
            </Button>
          }
        >
          {t('telegram.err.webhookHelp')}
        </Callout>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" loading={save.isPending && !unhook.isPending}>
          <Check /> {t('telegram.verify')}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
        )}
      </div>
    </form>
  )
}

function TokenStep() {
  const t = useT()
  return (
    <div className="grid gap-5">
      <Steps
        items={[
          <span>
            {t('telegram.bf1')}{' '}
            <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">
              @BotFather
            </a>
          </span>,
          <div className="grid gap-2">
            <span>{t('telegram.bf2')}</span>
            <CodeBlock inline code="/newbot" className="max-w-xs" />
          </div>,
          <span>{t('telegram.bf3')}</span>,
          <span>{t('telegram.bf4')}</span>,
        ]}
      />
      <TokenForm />
    </div>
  )
}

/** Seconds left before `link` expires, ticking every second (counted from when the server answered). */
function useSecondsLeft(link: TelegramLink | null | undefined): number {
  const deadline = React.useMemo(() => (link ? Date.now() + link.expires_in * 1000 : 0), [link])
  const [now, setNow] = React.useState(() => Date.now())
  React.useEffect(() => {
    if (!deadline) return
    setNow(Date.now())
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [deadline])
  return deadline ? Math.max(0, Math.round((deadline - now) / 1000)) : 0
}

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

/** The link code: QR, deep link, countdown and "New link" once it expired. The code lives on the server
 *  (status.link), so leaving the page and coming back shows the same one. */
export function LinkPanel({ status, intro }: { status: TelegramStatus; intro?: React.ReactNode }) {
  const t = useT()
  const qc = useQueryClient()
  const start = useTelegramLinkStart()
  const link = status.link ?? null
  const left = useSecondsLeft(link)
  const expired = !!link && (link.expired || left === 0)
  // the status follows the link live (bus); this poll is the fallback while a code waits for /start
  const poll = useTelegramLink(!!link && !expired)
  React.useEffect(() => {
    if (poll.data?.linked && !poll.data.pending) qc.invalidateQueries({ queryKey: qk.telegram.all })
  }, [poll.data, qc])
  const newLink = (
    <Button loading={start.isPending} variant={link ? 'outline' : 'default'} onClick={() => start.mutate()}>
      <Link2 /> {link ? t('telegram.newLink') : t('telegram.link')}
    </Button>
  )
  if (!link || expired)
    return (
      <div className="grid gap-3 mx-unfold">
        {expired ? <Callout tone="warning" title={t('telegram.expired')}>{t('telegram.expiredDesc')}</Callout> : intro}
        <div>{newLink}</div>
      </div>
    )
  return (
    <div className="grid items-center gap-6 rounded-xl border p-5 md:grid-cols-[auto_1fr] mx-rise">
      <div className="mx-auto grid justify-items-center gap-2">
        <Sensitive placeholder={<div className="size-40 rounded-lg bg-muted" />}>
          <QRCode value={link.deep_link} className="size-40 p-1" label={t('telegram.qr')} />
        </Sensitive>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Smartphone className="size-3.5" /> {t('telegram.scan')}
        </span>
      </div>
      <div className="grid gap-4">
        <p className="text-sm">{t('telegram.openAndStart')}</p>
        <Button size="lg" asChild className="w-full sm:w-auto">
          <a href={link.deep_link} target="_blank" rel="noopener noreferrer">
            <Send /> {t('telegram.openTelegram')} <ExternalLink className="size-3.5 opacity-70" />
          </a>
        </Button>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted-foreground" aria-live="polite">
          <span className="flex items-center gap-2">
            <Spinner /> {t('telegram.waiting')}
          </span>
          <span className="flex items-center gap-1 tabular-nums">
            <Timer className="size-3.5" /> {t('telegram.expiresIn', { time: mmss(left) })}
          </span>
        </div>
        <p className="text-xs text-muted-foreground">
          {t('telegram.manualCode')} <code className="rounded bg-muted px-1 font-mono"><Sensitive>/start {link.code}</Sensitive></code>
        </p>
        <p className="text-xs text-muted-foreground">{t('telegram.startEarly')}</p>
        <div>
          <Button variant="ghost" size="sm" loading={start.isPending} onClick={() => start.mutate()}>
            <RefreshCw /> {t('telegram.newLink')}
          </Button>
        </div>
      </div>
    </div>
  )
}

/** "Change bot": the token field, inline. Nothing changes until the new token is verified. */
export function ChangeBot({ className }: { className?: string }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  if (!open)
    return (
      <Button variant="ghost" size="sm" className={className} onClick={() => setOpen(true)}>
        <Bot /> {t('telegram.changeBot')}
      </Button>
    )
  return (
    <div className="grid gap-3 rounded-xl border p-4 mx-unfold">
      <p className="text-[13px] text-muted-foreground">{t('telegram.changeBotHint')}</p>
      <TokenForm autoFocus onDone={() => setOpen(false)} onCancel={() => setOpen(false)} />
    </div>
  )
}

function LinkStep({ status }: { status: TelegramStatus }) {
  const t = useT()
  return (
    <div className="grid gap-5">
      <Callout tone="success" title={t('telegram.botOk')}>
        <Sensitive>@{status.bot?.username}</Sensitive> · <Sensitive>{status.bot?.name}</Sensitive>
      </Callout>
      <LinkPanel status={status} intro={<p className="text-sm text-muted-foreground">{t('telegram.linkIntro')}</p>} />
      <div>
        <ChangeBot />
      </div>
    </div>
  )
}

/** Threads are off for this bot (BotFather "Threaded Mode"): how to turn them on, and Retry. Not an error. */
export function TopicsNotice({ status }: { status: TelegramStatus }) {
  const t = useT()
  const sync = useTelegramSync()
  if (!status.topics_notice) return null
  return (
    <Callout tone="warning" className="mx-unfold" title={t('telegram.topicsOff')}>
      <p className="mb-2">{t('telegram.topicsOffDesc')}</p>
      <Steps className="mt-2" items={[t('telegram.topicsOff1'), t('telegram.topicsOff2'), t('telegram.topicsOff3')]} />
      <Button
        className="mt-3"
        size="sm"
        variant="outline"
        loading={sync.isPending}
        onClick={() =>
          sync.mutate(undefined, {
            onSuccess: (r: TelegramSyncResult) =>
              r.topics_enabled ? toast.success(t('telegram.created', { count: r.created })) : toast.info(t('telegram.topicsStillOff')),
          })
        }
      >
        <RefreshCw /> {t('telegram.retry')}
      </Button>
    </Callout>
  )
}

/** A revoked token (401): the poller stopped. The token field comes right away. */
export function TokenRejected() {
  const t = useT()
  return (
    <div className="grid gap-4 mx-unfold">
      <Callout tone="error" title={t('telegram.tokenRejected')}>
        {t('telegram.tokenRejectedDesc')}
      </Callout>
      <TokenForm />
    </div>
  )
}

/** Poller and thread-sync errors, kept apart (a sync no longer hides why the bot does not receive anything). */
export function TelegramErrors({ status }: { status: TelegramStatus }) {
  const t = useT()
  const poll = !tokenRejected(status) ? status.poll_error : null
  if (!poll && !status.sync_error) return null
  return (
    <div className="grid gap-2">
      {poll && (
        <Callout tone="error" className="mx-unfold" title={t('telegram.pollErrorTitle')}>
          {status.poll_error_code === 'conflict' ? t('telegram.err.conflict') : poll}
        </Callout>
      )}
      {status.sync_error && (
        <Callout tone="warning" className="mx-unfold" title={t('telegram.syncErrorTitle')}>
          {status.sync_error}
        </Callout>
      )}
    </div>
  )
}

export function ThreadList({ status }: { status: TelegramStatus }) {
  const t = useT()
  if (!status.threads.length) return <p className="text-sm text-muted-foreground">{t('telegram.noThreads')}</p>
  return (
    <ul className="divide-y rounded-lg border">
      {status.threads.map((th) => (
        <li key={`${th.thread_id}`} className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm">
          <span className="min-w-0 truncate font-medium">
            <Sensitive>{th.name}</Sensitive>
          </span>
          {th.session_id ? (
            <Link to={`/sessions/${th.session_id}`} className="shrink-0 text-xs text-muted-foreground hover:text-foreground hover:underline">
              {t('telegram.thread.session')}
            </Link>
          ) : (
            <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">
              {th.path === '' ? t('telegram.thread.general') : th.path === '#crons' ? t('telegram.thread.crons') : th.path === '#alerts' ? t('telegram.thread.alerts') : <Sensitive>{th.path}</Sensitive>}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

/** The whole Telegram wizard (onboarding step 4 and Settings › Telegram until a chat is linked). */
export function TelegramSetup() {
  const t = useT()
  const { data: s, isLoading } = useTelegram()
  if (isLoading || !s)
    return (
      <div className="grid gap-4">
        <Skeleton className="h-5 w-72" />
        <Skeleton className="h-40" />
      </div>
    )
  const stage = telegramStage(s)
  return (
    <div className="grid gap-6">
      <SubSteps stage={stage} threadsOk={s.topics_enabled && s.threads.length > 0} />
      {tokenRejected(s) ? (
        <TokenRejected />
      ) : (
        <>
          {stage === 'token' && <TokenStep />}
          {stage === 'link' && <LinkStep status={s} />}
          {stage === 'done' && (
            <div className="grid gap-5">
              <Callout tone="success" title={t('telegram.chatLinked')}>
                <Sensitive>{s.chat?.title}</Sensitive>
              </Callout>
              <p className="text-sm text-muted-foreground">{t('telegram.threadsIntro')}</p>
              <TopicsNotice status={s} />
              <ThreadList status={s} />
            </div>
          )}
        </>
      )}
      <TelegramErrors status={s} />
    </div>
  )
}
