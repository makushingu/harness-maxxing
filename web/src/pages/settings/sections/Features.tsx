// Settings > Features (2.0.0a132): the optional pages (one row each, in their sidebar order), then the options of
// the sessions. A "This browser" mark tells the few switches kept in this browser only from those saved on the server.
import { useUI } from '@/stores/ui'
import { useT } from '@/i18n'
import { useSaveSettings, useSettings } from '@/lib/queries'
import { Skeleton, Switch, toast } from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { BrowserBadge, FeaturePages } from '@/features/settings/FeaturePages'
import { useSessionsUI } from '@/pages/sessions/store'
import { usePermission } from './Notifications'
import { SettingsCard, SectionStack } from './ui'

export function FeaturesSection() {
  const t = useT()
  const ui = useUI()
  const { data: s } = useSettings()
  const save = useSaveSettings()
  const tabs = useSessionsUI((x) => x.tabs)
  const [perm, ask] = usePermission()

  const toggleDone = async (on: boolean) => {
    ui.setNotify({ notifyDone: on })
    if (on && perm !== 'granted') {
      const p = await ask()
      if (p === 'denied') toast.error(t('notify.blocked'), t('notify.blockedDesc'))
    }
  }

  return (
    <SectionStack>
      <SettingsCard title={t('features.pages')} description={t('features.pagesDesc')}>
        <FeaturePages />
      </SettingsCard>

      <SettingsCard title={t('features.sessions')} description={t('features.sessionsDesc')}>
        {!s ? (
          <Skeleton className="h-36" />
        ) : (
          <div className="divide-y">
            <SettingRow label={t('features.maxxing')} description={t('features.maxxingDesc')} htmlFor="ft-maxxing">
              <Switch id="ft-maxxing" checked={!!s.maxxing_mode} onCheckedChange={(v) => save.mutate({ maxxing_mode: v })} />
            </SettingRow>
            <SettingRow label={<>{t('features.tabs')}<BrowserBadge /></>} description={t('features.tabsDesc')} htmlFor="ft-tabs">
              <Switch id="ft-tabs" checked={tabs} onCheckedChange={(v) => useSessionsUI.getState().setTabs(v)} />
            </SettingRow>
            <SettingRow label={<>{t('notify.done')}<BrowserBadge /></>} description={t('notify.doneDesc')} htmlFor="ft-done">
              <Switch id="ft-done" checked={ui.notifyDone} onCheckedChange={toggleDone} />
            </SettingRow>
            <SettingRow label={<>{t('hud.enable')}<BrowserBadge /></>} description={t('hud.enableDesc')} htmlFor="ft-hud">
              <Switch id="ft-hud" checked={ui.hud} onCheckedChange={ui.setHud} />
            </SettingRow>
            {ui.hud && !('documentPictureInPicture' in window) && (
              <div className="py-3">
                <Callout tone="info">{t('hud.fallback')}</Callout>
              </div>
            )}
          </div>
        )}
      </SettingsCard>
    </SectionStack>
  )
}
