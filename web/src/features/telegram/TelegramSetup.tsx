import * as React from 'react'
import { Check, ExternalLink, Link2, RefreshCw, Send, Smartphone } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { useTelegram, useTelegramLink, useTelegramLinkStart, useTelegramSync, useTelegramToken, qk } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import type { TelegramLinkStart, TelegramStatus, TelegramSyncResult } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Badge, Button, CodeBlock, FormField, SecretInput, Sensitive, Skeleton, Spinner } from '@/components/ui'
import { QRCode } from '@/components/ui/qr-code'
import { Callout, Steps } from '../common'

export type TelegramStage = 'token' | 'link' | 'threads' | 'done'

export function telegramStage(s: TelegramStatus | undefined): TelegramStage {
  if (!s || !s.bot) return 'token'
  if (!s.chat) return 'link'
  if (!s.topics_enabled || s.threads.length === 0) return 'threads'
  return 'done'
}

/** Mini progress for the 3 sub-steps. */
function SubSteps({ stage }: { stage: TelegramStage }) {
  const t = useT()
  const order: TelegramStage[] = ['token', 'link', 'threads']
  const idx = stage === 'done' ? 3 : order.indexOf(stage)
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

function TokenStep() {
  const t = useT()
  const [token, setToken] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const save = useTelegramToken()
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
      <form
        className="grid gap-4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          if (!token.trim()) return setError(t('telegram.tokenRequired'))
          setError(null)
          save.mutate(token.trim(), {
            onSuccess: (r) => (r.ok ? setToken('') : setError(r.error || t('telegram.tokenInvalid'))),
            onError: (e) => setError(errorMessage(e)),
          })
        }}
      >
        <FormField label={t('telegram.token')} error={error || undefined} hint={t('telegram.tokenHint')}>
          <SecretInput value={token} onChange={(e) => setToken(e.target.value)} placeholder="123456789:AA…" />
        </FormField>
        <div>
          <Button type="submit" loading={save.isPending}>
            <Check /> {t('telegram.verify')}
          </Button>
        </div>
      </form>
    </div>
  )
}

function LinkStep({ status }: { status: TelegramStatus }) {
  const t = useT()
  const qc = useQueryClient()
  const start = useTelegramLinkStart()
  const [link, setLink] = React.useState<TelegramLinkStart | null>(null)
  const poll = useTelegramLink(!!link)
  React.useEffect(() => {
    if (poll.data?.linked) qc.invalidateQueries({ queryKey: qk.telegram.all })
  }, [poll.data?.linked, qc])
  return (
    <div className="grid gap-5">
      <Callout tone="success" title={t('telegram.botOk')}>
        <Sensitive>@{status.bot?.username}</Sensitive> · <Sensitive>{status.bot?.name}</Sensitive>
      </Callout>
      {!link ? (
        <div className="grid gap-3">
          <p className="text-sm text-muted-foreground">{t('telegram.linkIntro')}</p>
          <div>
            <Button loading={start.isPending} onClick={() => start.mutate(undefined, { onSuccess: setLink })}>
              <Link2 /> {t('telegram.link')}
            </Button>
          </div>
        </div>
      ) : (
        <div className="grid items-center gap-6 rounded-xl border p-5 md:grid-cols-[auto_1fr]">
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
            <div className="flex items-center gap-2 text-[13px] text-muted-foreground" aria-live="polite">
              {poll.data?.linked ? (
                <>
                  <Check className="size-4 text-success" /> {t('telegram.linked')}
                </>
              ) : (
                <>
                  <Spinner /> {t('telegram.waiting')}
                </>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              {t('telegram.manualCode')} <code className="rounded bg-muted px-1 font-mono"><Sensitive>/start {link.code}</Sensitive></code>
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

function ThreadsStep({ status }: { status: TelegramStatus }) {
  const t = useT()
  const sync = useTelegramSync()
  const [res, setRes] = React.useState<TelegramSyncResult | null>(null)
  const created = res ? res.created : null
  const topicsOn = res ? res.topics_enabled : status.topics_enabled
  return (
    <div className="grid gap-5">
      <Callout tone="success" title={t('telegram.chatLinked')}>
        <Sensitive>{status.chat?.title}</Sensitive>
      </Callout>
      <p className="text-sm text-muted-foreground">{t('telegram.threadsIntro')}</p>
      {res?.error && <Callout tone="error">{res.error}</Callout>}
      {!topicsOn && created !== null && (
        <Callout tone="warning" title={t('telegram.topicsOff')}>
          <Steps className="mt-2" items={[t('telegram.topicsOff1'), t('telegram.topicsOff2'), t('telegram.topicsOff3')]} />
        </Callout>
      )}
      {created !== null && topicsOn && <Callout tone="success" title={t('telegram.created', { count: created })} />}
      <div>
        <Button
          loading={sync.isPending}
          onClick={() => sync.mutate(undefined, { onSuccess: setRes })}
          variant={created === null ? 'default' : 'outline'}
        >
          <RefreshCw /> {created === null ? t('telegram.createThreads') : t('telegram.syncAgain')}
        </Button>
      </div>
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

/** The whole Telegram wizard (onboarding step 4 and Settings › Telegram until configured). */
export function TelegramSetup() {
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
      <SubSteps stage={stage} />
      {stage === 'token' && <TokenStep />}
      {stage === 'link' && <LinkStep status={s} />}
      {(stage === 'threads' || stage === 'done') && <ThreadsStep status={s} />}
      {stage === 'done' && <ThreadList status={s} />}
      {s.last_error && (
        <Callout tone="error" title={<Badge variant="destructive">Telegram</Badge>}>
          {s.last_error}
        </Callout>
      )}
    </div>
  )
}
