// The Devices switch (off by default): at the top of Settings -> Devices and in Settings -> Features (with a link to
// Settings -> Devices).
import { Link } from 'react-router'
import { MonitorSmartphone } from 'lucide-react'
import { useT } from '@/i18n'
import { useSaveSettings, useSettings } from '@/lib/queries'
import { Button, Switch } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { SettingsCard } from '@/pages/settings/sections/ui'

const DEVICES_SETTINGS = '/settings/devices'

export function DevicesFeature({ link }: { link?: boolean }) {
  const t = useT()
  const { data: s } = useSettings()
  const save = useSaveSettings()
  const on = !!s?.devices_feature
  return (
    <SettingsCard title={t('devices.feature.title')} description={t('devices.feature.desc')}>
      <div className="divide-y" data-testid="devices-feature" data-tour="devices-feature">
        <SettingRow label={t('devices.feature.enable')} description={t('devices.feature.enableDesc')} htmlFor="ft-devices">
          <Switch id="ft-devices" checked={on} onCheckedChange={(v) => save.mutate({ devices_feature: v })} />
        </SettingRow>
        {on && link && (
          <div className="flex flex-wrap items-center gap-2 py-3">
            <Button size="sm" variant="outline" asChild>
              <Link to={DEVICES_SETTINGS} data-testid="devices-open-page">
                <MonitorSmartphone /> {t('devices.openPage')}
              </Link>
            </Button>
            <span className="text-[12px] text-muted-foreground">{t('devices.openPageHint')}</span>
          </div>
        )}
      </div>
    </SettingsCard>
  )
}
