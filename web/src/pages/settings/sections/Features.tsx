// Settings > Features: every optional feature in one place (each also stays in its own section).
import { Link } from 'react-router'
import { useUI } from '@/stores/ui'
import { useT } from '@/i18n'
import { useSaveSettings, useSettings, useTelegram, useTelegramSettings } from '@/lib/queries'
import { Skeleton, Switch, toast } from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { telegramStage } from '@/features/telegram/TelegramSetup'
import { usePermission } from './Notifications'
import { SettingsCard, SectionStack } from './ui'

export function FeaturesSection() {
  const t = useT()
  const ui = useUI()
  const { data: s } = useSettings()
  const save = useSaveSettings()
  const { data: tg } = useTelegram()
  const saveTg = useTelegramSettings()
  const [perm, ask] = usePermission()
  const tgReady = telegramStage(tg) === 'done'

  const toggleDone = async (on: boolean) => {
    ui.setNotify({ notifyDone: on })
    if (on && perm !== 'granted') {
      const p = await ask()
      if (p === 'denied') toast.error(t('notify.blocked'), t('notify.blockedDesc'))
    }
  }

  return (
    <SectionStack>
      <SettingsCard title={t('features.browser')} description={t('features.browserDesc')}>
        <div className="divide-y">
          <SettingRow label={t('hud.enable')} description={t('hud.enableDesc')} htmlFor="ft-hud">
            <Switch id="ft-hud" checked={ui.hud} onCheckedChange={ui.setHud} />
          </SettingRow>
          {ui.hud && !('documentPictureInPicture' in window) && (
            <div className="py-3">
              <Callout tone="info">{t('hud.fallback')}</Callout>
            </div>
          )}
          <SettingRow label={t('notify.done')} description={t('notify.doneDesc')} htmlFor="ft-done">
            <Switch id="ft-done" checked={ui.notifyDone} onCheckedChange={toggleDone} />
          </SettingRow>
        </div>
      </SettingsCard>

      <SettingsCard title={t('features.server')} description={t('features.serverDesc')}>
        {!s ? (
          <Skeleton className="h-36" />
        ) : (
          <div className="divide-y">
            <SettingRow
              label={t('telegram.mirrorWeb')}
              description={
                tgReady ? (
                  t('telegram.mirrorWebDesc')
                ) : (
                  <>
                    {t('features.telegramFirst')}{' '}
                    <Link to="/settings/telegram" className="text-primary hover:underline">
                      {t('settings.telegram')}
                    </Link>
                  </>
                )
              }
              htmlFor="ft-mirror"
            >
              <Switch id="ft-mirror" disabled={!tgReady} checked={!!tg?.settings?.mirror_web} onCheckedChange={(v) => saveTg.mutate({ mirror_web: v })} />
            </SettingRow>
            <SettingRow label={t('settings.usageWidget')} description={t('settings.usageWidgetDesc')} htmlFor="ft-usage">
              <Switch id="ft-usage" checked={!!s.usage_widget} onCheckedChange={(v) => save.mutate({ usage_widget: v })} />
            </SettingRow>
            <SettingRow
              label={t('features.git')}
              description={
                <>
                  {t('features.gitDesc')}{' '}
                  <Link to="/settings/keys" className="text-primary hover:underline">
                    {t('settings.keys')}
                  </Link>
                </>
              }
              htmlFor="ft-git"
            >
              <Switch id="ft-git" checked={!!s.git_page} onCheckedChange={(v) => save.mutate({ git_page: v })} />
            </SettingRow>
            <SettingRow
              label={t('features.infra')}
              description={
                <>
                  {t('features.infraDesc')}{' '}
                  <Link to="/settings/keys" className="text-primary hover:underline">
                    {t('settings.keys')}
                  </Link>
                </>
              }
              htmlFor="ft-infra"
            >
              <Switch id="ft-infra" checked={!!s.infra_page} onCheckedChange={(v) => save.mutate({ infra_page: v })} />
            </SettingRow>
            <SettingRow label={t('features.maxxing')} description={t('features.maxxingDesc')} htmlFor="ft-maxxing">
              <Switch id="ft-maxxing" checked={!!s.maxxing_mode} onCheckedChange={(v) => save.mutate({ maxxing_mode: v })} />
            </SettingRow>
            <SettingRow label={t('settings.presentationDefault')} description={t('settings.presentationDefaultDesc')} htmlFor="ft-pres">
              <Switch id="ft-pres" checked={!!s.presentation_default} onCheckedChange={(v) => save.mutate({ presentation_default: v })} />
            </SettingRow>
          </div>
        )}
      </SettingsCard>
    </SectionStack>
  )
}
