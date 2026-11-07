import * as React from 'react'
import { Link2, RefreshCw, Send, Unlink } from 'lucide-react'
import { useSessions, useTelegram, useTelegramSettings, useTelegramSync, useTelegramTest, useTelegramUnlink } from '@/lib/queries'
import { useLang, useT } from '@/i18n'
import { fmtRelative } from '@/lib/format'
import type { Session, TelegramMode, TelegramSettings, TelegramStatus, TelegramTestResult } from '@/lib/types'
import { Badge, Button, Segmented, Sensitive, Skeleton, StatusDot, Switch, confirm, toast } from '@/components/ui'
import { TwoFactorRow } from '@/features/auth/TwoFactorRow'
import { ChangeBot, LinkPanel, TelegramErrors, TelegramSetup, ThreadList, TokenRejected, TopicsNotice, telegramStage, tokenRejected } from '@/features/telegram/TelegramSetup'
import { Callout, OptionCard, SettingRow } from '@/features/common'
import { SettingsCard, SectionStack } from './ui'

/** Simple (one chat) / one thread per session / threads + web mirror. Leaving the threads asks first: they are
 * deleted from Telegram. */
function ModeCard({ status: s }: { status: TelegramStatus }) {
  const t = useT()
  const save = useTelegramSettings()
  const mode = s.settings.mode ?? s.mode ?? 'simple'
  const pick = async (m: TelegramMode) => {
    if (m === mode) return
    const n = s.threads.length
    if (m === 'simple' && n > 0 && !(await confirm({ title: t('telegram.modeConfirm', { count: n }), description: t('telegram.modeConfirmDesc'), destructive: true, confirmText: t('telegram.modeConfirmOk') }))) return
    save.mutate({ mode: m, mirror_web: m === 'mirror' })
  }
  return (
    <SettingsCard title={t('telegram.mode')} description={t('telegram.modeDesc')}>
      <div className="grid gap-2">
        {(['simple', 'threads', 'mirror'] as const).map((m) => (
          <OptionCard
            key={m}
            name="telegram-mode"
            value={m}
            selected={mode === m}
            onSelect={() => pick(m)}
            title={t(`telegram.mode.${m}`)}
            description={t(`telegram.mode.${m}.desc`)}
            badge={m === 'simple' ? <Badge variant="muted">{t('telegram.mode.recommended')}</Badge> : undefined}
          />
        ))}
      </div>
      {mode !== 'simple' && !s.topics_enabled && (
        <Callout tone="info" className="mt-3">
          {t('telegram.mode.needsThreads')}
        </Callout>
      )}
    </SettingsCard>
  )
}

function DisconnectCard() {
  const t = useT()
  const unlink = useTelegramUnlink()
  return (
    <SettingsCard danger title={t('telegram.unlink')} description={t('telegram.unlinkDesc')}>
      <Button
        variant="destructive"
        loading={unlink.isPending}
        onClick={async () => {
          if (await confirm({ title: t('telegram.unlinkConfirm'), description: t('telegram.unlinkDesc'), destructive: true, confirmText: t('telegram.unlink') })) unlink.mutate()
        }}
      >
        <Unlink /> {t('telegram.unlink')}
      </Button>
    </SettingsCard>
  )
}

export function TelegramSection() {
  const t = useT()
  const lang = useLang()
  const { data: s } = useTelegram()
  const save = useTelegramSettings()
  const test = useTelegramTest()
  const sync = useTelegramSync()
  const [relink, setRelink] = React.useState(false)
  const [report, setReport] = React.useState<TelegramTestResult | null>(null)
  const { data: sessions } = useSessions(undefined, false, !!s && telegramStage(s) === 'done')
  if (!s) return <Skeleton className="h-72 rounded-xl" />
  const stage = telegramStage(s)
  if (stage !== 'done')
    return (
      <SectionStack>
        <SettingsCard title={t('telegram.setup')} description={t('telegram.setupDesc')}>
          <TelegramSetup />
        </SettingsCard>
        {s.configured && <DisconnectCard />}
      </SectionStack>
    )
  const set = (patch: Partial<TelegramSettings>) => save.mutate(patch)
  const threads = (s.settings.mode ?? s.mode) !== 'simple'
  const linkPending = !!s.link && !s.link.expired
  const lastPoll = s.last_poll_ok ? fmtRelative(s.last_poll_ok, lang) : t('telegram.never')
  return (
    <SectionStack>
      {tokenRejected(s) && (
        <SettingsCard title={t('telegram.newToken')}>
          <TokenRejected />
        </SettingsCard>
      )}
      <SettingsCard
        title={t('telegram.status')}
        actions={
          <Button
            variant="outline"
            size="sm"
            loading={test.isPending}
            onClick={() =>
              test.mutate(undefined, {
                onSuccess: (r) => {
                  setReport(r.ok ? null : r)
                  if (r.ok) toast.success(t('telegram.testSent'))
                },
              })
            }
          >
            <Send /> {t('telegram.test')}
          </Button>
        }
      >
        <dl className="grid grid-cols-[minmax(0,1fr)] gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div className="grid min-w-0 gap-1">
            <dt className="text-[13px] text-muted-foreground">{t('telegram.gateway')}</dt>
            <dd className="flex items-center gap-2 font-medium">
              <StatusDot tone={s.running ? (s.poll_error ? 'warn' : 'ok') : 'error'} /> {s.running ? t('telegram.running') : t('telegram.stopped')}
            </dd>
          </div>
          <div className="grid min-w-0 gap-1">
            <dt className="text-[13px] text-muted-foreground">{t('telegram.lastPoll')}</dt>
            <dd className="font-medium tabular-nums">{lastPoll}</dd>
          </div>
          <div className="grid min-w-0 gap-1">
            <dt className="text-[13px] text-muted-foreground">{t('telegram.bot')}</dt>
            <dd className="font-medium [overflow-wrap:anywhere]">
              <Sensitive>@{s.bot?.username}</Sensitive>
            </dd>
          </div>
          <div className="grid min-w-0 gap-1">
            <dt className="text-[13px] text-muted-foreground">{t('telegram.chat')}</dt>
            <dd className="font-medium [overflow-wrap:anywhere]">
              <Sensitive>{s.chat?.title}</Sensitive>
            </dd>
          </div>
        </dl>
        <div className="mt-4 grid gap-3 empty:hidden">
          {report && (
            <Callout tone="warning" className="mx-unfold" title={report.sent ? t('telegram.testProblems') : t('telegram.testNotSent')}>
              <ul className="grid list-disc gap-1 pl-4">
                {report.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </Callout>
          )}
          <TelegramErrors status={s} />
          <TopicsNotice status={s} />
          {(relink || linkPending) && (
            <div className="grid gap-2 mx-unfold">
              <p className="text-[13px] text-muted-foreground">{t('telegram.relinkDesc')}</p>
              <LinkPanel status={s} />
              <div>
                <Button variant="ghost" size="sm" onClick={() => setRelink(false)}>
                  {t('common.cancel')}
                </Button>
              </div>
            </div>
          )}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {!relink && !linkPending && (
            <Button variant="ghost" size="sm" onClick={() => setRelink(true)}>
              <Link2 /> {t('telegram.relink')}
            </Button>
          )}
          <ChangeBot />
        </div>
      </SettingsCard>

      <ModeCard status={s} />

      <SettingsCard title={t('telegram.behaviour')}>
        <div className="divide-y">
          <SettingRow label={t('telegram.notifyCrons')} description={t('telegram.notifyCronsDesc')} htmlFor="tg-crons">
            <Switch id="tg-crons" checked={s.settings.notify_crons} onCheckedChange={(v) => set({ notify_crons: v })} />
          </SettingRow>
          <SettingRow label={t('telegram.notifySystem')} description={t('telegram.notifySystemDesc')} htmlFor="tg-system">
            <Switch id="tg-system" checked={s.settings.notify_system ?? true} onCheckedChange={(v) => set({ notify_system: v })} />
          </SettingRow>
          <SettingRow label={t('telegram.loginAlerts')} description={t('telegram.loginAlertsDesc')} htmlFor="tg-login">
            <Switch id="tg-login" checked={s.settings.login_alerts} onCheckedChange={(v) => set({ login_alerts: v })} />
          </SettingRow>
          <TwoFactorRow on={!!s.settings.two_factor} />
          <SettingRow label={t('telegram.replyMode')} description={t('telegram.replyModeDesc')}>
            <Segmented
              value={s.settings.reply_mode}
              onChange={(v) => set({ reply_mode: v })}
              aria-label={t('telegram.replyMode')}
              options={[
                { value: 'progress', label: t('telegram.reply.progress') },
                { value: 'final', label: t('telegram.reply.final') },
              ]}
            />
          </SettingRow>
          {threads && <SettingRow label={t('telegram.threadDays')} description={t('telegram.threadDaysDesc')}>
            <Segmented
              value={String(s.settings.thread_days ?? 30)}
              onChange={async (v) => {
                const days = Number(v)
                const lost = threadsLost(s, sessions, days)
                if (lost > 0 && !(await confirm({ title: t('telegram.threadDaysConfirm', { count: lost }), description: t('telegram.threadDaysConfirmDesc'), destructive: true, confirmText: t('telegram.threadDaysConfirmOk') }))) return
                set({ thread_days: days })
              }}
              aria-label={t('telegram.threadDays')}
              options={[7, 14, 30, 90].map((d) => ({ value: String(d), label: t('telegram.days', { count: d }) }))}
            />
          </SettingRow>}
        </div>
      </SettingsCard>

      {threads && <SettingsCard
        title={
          <span className="flex items-center gap-2">
            {t('telegram.threads')} <Badge variant="muted">{s.threads.length}</Badge>
          </span>
        }
        description={t('telegram.threadsDesc')}
        actions={
          <Button variant="outline" size="sm" loading={sync.isPending} onClick={() => sync.mutate(undefined, { onSuccess: (r) => (r.error ? toast.error(r.error) : toast.success(t('telegram.created', { count: r.created }))) })}>
            <RefreshCw /> {t('telegram.sync')}
          </Button>
        }
      >
        <ThreadList status={s} />
      </SettingsCard>}

      {!threads && !!s.agent_threads?.length && (
        <SettingsCard
          title={
            <span className="flex items-center gap-2">
              {t('telegram.agentThreads')} <Badge variant="muted">{s.agent_threads.length}</Badge>
            </span>
          }
          description={t('telegram.agentThreadsDesc')}
        >
          <ul className="grid gap-1 text-sm">
            {s.agent_threads.map((a) => (
              <li key={a.path} className="truncate">
                {a.name || a.path}
              </li>
            ))}
          </ul>
        </SettingsCard>
      )}

      <DisconnectCard />
    </SectionStack>
  )
}


/** Session threads the sync would delete with a shorter `thread_days` (idle sessions, not running). */
function threadsLost(s: TelegramStatus, sessions: Session[] | undefined, days: number): number {
  if (days >= (s.settings.thread_days ?? 30) || !sessions) return 0
  const cutoff = Date.now() / 1000 - days * 86400
  const byId = new Map(sessions.map((x) => [x.id, x]))
  return s.threads.filter((th) => {
    const x = th.session_id ? byId.get(th.session_id) : undefined
    return !!x && x.state !== 'running' && (x.updated || 0) < cutoff
  }).length
}
