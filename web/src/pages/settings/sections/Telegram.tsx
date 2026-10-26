import * as React from 'react'
import { Link2, RefreshCw, Send, Unlink } from 'lucide-react'
import { useTelegram, useTelegramSettings, useTelegramSync, useTelegramTest, useTelegramUnlink } from '@/lib/queries'
import { useLang, useT } from '@/i18n'
import { fmtRelative } from '@/lib/format'
import type { TelegramSettings, TelegramTestResult } from '@/lib/types'
import { Badge, Button, Segmented, Sensitive, Skeleton, StatusDot, Switch, confirm, toast } from '@/components/ui'
import { TwoFactorRow } from '@/features/auth/TwoFactorRow'
import { ChangeBot, LinkPanel, TelegramErrors, TelegramSetup, ThreadList, TokenRejected, TopicsNotice, telegramStage, tokenRejected } from '@/features/telegram/TelegramSetup'
import { Callout, SettingRow } from '@/features/common'
import { SettingsCard, SectionStack } from './ui'

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
        <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div className="grid gap-1">
            <dt className="text-[13px] text-muted-foreground">{t('telegram.gateway')}</dt>
            <dd className="flex items-center gap-2 font-medium">
              <StatusDot tone={s.running ? (s.poll_error ? 'warn' : 'ok') : 'error'} /> {s.running ? t('telegram.running') : t('telegram.stopped')}
            </dd>
          </div>
          <div className="grid gap-1">
            <dt className="text-[13px] text-muted-foreground">{t('telegram.lastPoll')}</dt>
            <dd className="font-medium tabular-nums">{lastPoll}</dd>
          </div>
          <div className="grid gap-1">
            <dt className="text-[13px] text-muted-foreground">{t('telegram.bot')}</dt>
            <dd className="font-medium">
              <Sensitive>@{s.bot?.username}</Sensitive>
            </dd>
          </div>
          <div className="grid gap-1">
            <dt className="text-[13px] text-muted-foreground">{t('telegram.chat')}</dt>
            <dd className="font-medium">
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

      <SettingsCard title={t('telegram.behaviour')}>
        <div className="divide-y">
          <SettingRow label={t('telegram.notifyCrons')} description={t('telegram.notifyCronsDesc')} htmlFor="tg-crons">
            <Switch id="tg-crons" checked={s.settings.notify_crons} onCheckedChange={(v) => set({ notify_crons: v })} />
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
          <SettingRow label={t('telegram.mirrorWeb')} description={t('telegram.mirrorWebDesc')} htmlFor="tg-mirror">
            <Switch id="tg-mirror" checked={s.settings.mirror_web ?? false} onCheckedChange={(v) => set({ mirror_web: v })} />
          </SettingRow>
          <SettingRow label={t('telegram.threadDays')} description={t('telegram.threadDaysDesc')}>
            <Segmented
              value={String(s.settings.thread_days ?? 30)}
              onChange={(v) => set({ thread_days: Number(v) })}
              aria-label={t('telegram.threadDays')}
              options={[7, 14, 30, 90].map((d) => ({ value: String(d), label: t('telegram.days', { count: d }) }))}
            />
          </SettingRow>
        </div>
      </SettingsCard>

      <SettingsCard
        title={
          <span className="flex items-center gap-2">
            {t('telegram.threads')} <Badge variant="muted">{s.threads.length}</Badge>
          </span>
        }
        description={t('telegram.threadsDesc')}
        actions={
          <Button variant="outline" size="sm" loading={sync.isPending} onClick={() => sync.mutate(undefined, { onSuccess: (r) => toast.success(t('telegram.created', { count: r.created })) })}>
            <RefreshCw /> {t('telegram.sync')}
          </Button>
        }
      >
        <ThreadList status={s} />
      </SettingsCard>

      <DisconnectCard />
    </SectionStack>
  )
}

