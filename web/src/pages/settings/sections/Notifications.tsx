import * as React from 'react'
import { BellRing } from 'lucide-react'
import { useUI } from '@/stores/ui'
import { useSettings } from '@/lib/queries'
import { useT } from '@/i18n'
import { Button, CountBadge, Switch, toast } from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { notificationsSupported, playChime, showSystemNotification } from '@/features/notify/useDoneNotifier'
import { SettingsCard, SectionStack } from './ui'
import { FeedSettingsCards } from '@/features/feed/FeedSettings'

export function usePermission(): [NotificationPermission | 'unsupported', () => Promise<NotificationPermission | 'unsupported'>] {
  const [perm, setPerm] = React.useState<NotificationPermission | 'unsupported'>(() => (notificationsSupported() ? Notification.permission : 'unsupported'))
  const ask = React.useCallback(async () => {
    if (!notificationsSupported()) return 'unsupported' as const
    const p = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission
    setPerm(p)
    return p
  }, [])
  return [perm, ask]
}

export function NotificationsSection() {
  const t = useT()
  const notifyDone = useUI((s) => s.notifyDone)
  const notifySound = useUI((s) => s.notifySound)
  const notifyTeam = useUI((s) => s.notifyTeam)
  const { data: settings } = useSettings()
  const badgePulse = useUI((s) => s.badgePulse)
  const setNotify = useUI((s) => s.setNotify)
  const [perm, ask] = usePermission()

  const toggleDone = async (on: boolean) => {
    setNotify({ notifyDone: on })
    if (on && perm !== 'granted') {
      const p = await ask()
      if (p === 'denied') toast.error(t('notify.blocked'), t('notify.blockedDesc'))
    }
  }
  const test = () => {
    const shown = showSystemNotification(t('notify.doneTitle'), t('notify.testBody'), undefined, 'mx-test')
    if (!shown) toast.action(t('notify.doneTitle'), t('notify.testBody'), { label: t('notify.open'), onClick: () => {} })
    if (notifySound) playChime()
  }

  return (
    <SectionStack>
      <SettingsCard
        title={t('notify.title')}
        description={t('notify.desc')}
        actions={
          <Button variant="outline" size="sm" onClick={test} disabled={!notifyDone}>
            <BellRing /> {t('notify.test')}
          </Button>
        }
      >
        <div className="divide-y">
          <SettingRow label={t('notify.done')} description={t('notify.doneDesc')} htmlFor="mx-notify-done">
            <Switch id="mx-notify-done" checked={notifyDone} onCheckedChange={(v) => void toggleDone(v)} />
          </SettingRow>
          {settings?.team_page && (
            <SettingRow label={t('team.notifySetting')} description={t('team.notifySettingDesc')} htmlFor="mx-notify-team">
              <Switch
                id="mx-notify-team"
                checked={notifyTeam}
                onCheckedChange={async (v) => {
                  setNotify({ notifyTeam: v })
                  if (v && perm === 'default') await ask()
                }}
              />
            </SettingRow>
          )}
          <SettingRow label={t('notify.sound')} description={t('notify.soundDesc')} htmlFor="mx-notify-sound">
            <Switch id="mx-notify-sound" checked={notifySound} disabled={!notifyDone && !(settings?.team_page && notifyTeam)} onCheckedChange={(v) => setNotify({ notifySound: v })} />
          </SettingRow>
        </div>
        {notifyDone && perm === 'denied' && (
          <Callout tone="warning" className="mt-4">
            {t('notify.blockedDesc')}
          </Callout>
        )}
        {notifyDone && perm === 'unsupported' && (
          <Callout tone="info" className="mt-4">
            {t('notify.unsupported')}
          </Callout>
        )}
      </SettingsCard>
      <SettingsCard title={t('notify.badgeTitle')} description={t('notify.badgeDesc')}>
        <SettingRow label={t('notify.pulse')} description={t('notify.pulseDesc')} htmlFor="mx-badge-pulse">
          <span className="flex items-center gap-3">
            <CountBadge count={1} />
            <Switch id="mx-badge-pulse" checked={badgePulse} onCheckedChange={(v) => setNotify({ badgePulse: v })} />
          </span>
        </SettingRow>
      </SettingsCard>
      <FeedSettingsCards />
    </SectionStack>
  )
}
