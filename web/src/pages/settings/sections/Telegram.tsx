import { RefreshCw, Send, Unlink } from 'lucide-react'
import { useTelegram, useTelegramSettings, useTelegramSync, useTelegramTest, useTelegramUnlink } from '@/lib/queries'
import { useT } from '@/i18n'
import type { TelegramSettings } from '@/lib/types'
import { Badge, Button, Segmented, Sensitive, Skeleton, StatusDot, Switch, confirm, toast } from '@/components/ui'
import { TwoFactorRow } from '@/features/auth/TwoFactorRow'
import { TelegramSetup, ThreadList, telegramStage } from '@/features/telegram/TelegramSetup'
import { SettingRow } from '@/features/common'
import { SettingsCard, SectionStack } from './ui'

export function TelegramSection() {
  const t = useT()
  const { data: s } = useTelegram()
  const save = useTelegramSettings()
  const test = useTelegramTest()
  const sync = useTelegramSync()
  const unlink = useTelegramUnlink()
  if (!s) return <Skeleton className="h-72 rounded-xl" />
  const stage = telegramStage(s)
  if (stage !== 'done')
    return (
      <SettingsCard title={t('telegram.setup')} description={t('telegram.setupDesc')}>
        <TelegramSetup />
      </SettingsCard>
    )
  const set = (patch: Partial<TelegramSettings>) => save.mutate(patch)
  return (
    <SectionStack>
      <SettingsCard
        title={t('telegram.status')}
        actions={
          <Button variant="outline" size="sm" loading={test.isPending} onClick={() => test.mutate(undefined, { onSuccess: () => toast.success(t('telegram.testSent')) })}>
            <Send /> {t('telegram.test')}
          </Button>
        }
      >
        <dl className="grid gap-4 text-sm sm:grid-cols-3">
          <div className="grid gap-1">
            <dt className="text-[13px] text-muted-foreground">{t('telegram.gateway')}</dt>
            <dd className="flex items-center gap-2 font-medium">
              <StatusDot tone={s.running ? 'ok' : 'error'} /> {s.running ? t('telegram.running') : t('telegram.stopped')}
            </dd>
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
        {s.last_error && <p className="mt-4 text-[13px] text-destructive">{s.last_error}</p>}
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
    </SectionStack>
  )
}

