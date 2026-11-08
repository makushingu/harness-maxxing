// Settings -> General: language and time zone, the app on this computer / phone, the guided tour and the tutorial.
// (Appearance has its own section since 2.0.0a132; the server address moved to System, the presentation mode to Security.)
import * as React from 'react'
import { CheckCircle2, Compass, Download, GraduationCap } from 'lucide-react'
import { useSaveSettings, useSettings } from '@/lib/queries'
import { useUI } from '@/stores/ui'
import { useT } from '@/i18n'
import type { Language } from '@/lib/types'
import { Button, Skeleton, toast } from '@/components/ui'
import { QRCode } from '@/components/ui/qr-code'
import { RegionFields } from '@/features/general/RegionFields'
import { SettingRow } from '@/features/common'
import { SettingsCard, SectionStack } from './ui'
import { useNavigate } from 'react-router'
import { startTour, useTutorialHref } from '@/tour/store'
import { installApp, isStandalone, useInstallMode, usePWA } from '@/pwa'
import { InstallGuide, InstallSteps } from '@/pwa/InstallSteps'

function HelpCard() {
  const t = useT()
  const navigate = useNavigate()
  const tutorial = useTutorialHref()
  return (
    <SettingsCard title={t('help.settingsTitle')} description={t('help.settingsDesc')}>
      <div className="divide-y">
        <SettingRow label={t('help.tour')} description={t('help.tourDesc')}>
          <Button variant="outline" size="sm" onClick={startTour}>
            <Compass /> {t('help.tour')}
          </Button>
        </SettingRow>
        {tutorial && (
          <SettingRow label={t('help.tutorial')} description={t('help.tutorialDesc')}>
            <Button variant="outline" size="sm" onClick={() => navigate(tutorial!)}>
              <GraduationCap /> {t('help.tutorial')}
            </Button>
          </SettingRow>
        )}
      </div>
    </SettingsCard>
  )
}

/** Settings -> General -> App: install on this computer (one click when the browser offers it, else its steps),
 *  and how to add it to a phone's home screen (with a QR code to open this address there). */
function AppCard() {
  const t = useT()
  const install = useInstallMode()
  const installed = usePWA((s) => s.installed) || isStandalone()
  const [guide, setGuide] = React.useState(false)
  return (
    <SettingsCard title={t('pwa.card.title')} description={t('pwa.installDesc')}>
      <div className="divide-y">
        <SettingRow label={t('pwa.card.here')} description={installed ? t('pwa.card.installed') : t('pwa.card.hereDesc')}>
          {installed ? (
            <span className="inline-flex items-center gap-1.5 text-sm font-medium text-success"><CheckCircle2 className="size-4" /> {t('pwa.card.done')}</span>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => void installApp()} data-testid="install-app">
                <Download /> {t('pwa.install')}
              </Button>
              {install === 'prompt' && (
                <Button variant="ghost" size="sm" onClick={() => setGuide((g) => !g)}>
                  {t('pwa.card.how')}
                </Button>
              )}
            </div>
          )}
        </SettingRow>
        {guide && (
          <div className="py-4">
            <InstallGuide />
          </div>
        )}
        <div className="grid gap-4 py-4">
          <div className="grid gap-1">
            <div className="text-sm font-medium">{t('pwa.card.phone')}</div>
            <p className="text-[13px] text-muted-foreground">{t('pwa.card.phoneDesc')}</p>
          </div>
          <div className="grid gap-4 md:grid-cols-[auto_1fr_1fr]">
            <div className="flex flex-col items-center gap-2 max-md:hidden">
              <QRCode value={window.location.origin} className="size-36 p-1" label={t('pwa.card.qr')} />
              <span className="max-w-36 text-center text-xs text-muted-foreground">{t('pwa.card.qr')}</span>
            </div>
            <div className="grid content-start gap-2">
              <div className="text-[13px] font-medium">{t('pwa.p.ios')}</div>
              <InstallSteps platform="ios" compact />
            </div>
            <div className="grid content-start gap-2">
              <div className="text-[13px] font-medium">{t('pwa.p.android')}</div>
              <InstallSteps platform="android" compact />
            </div>
          </div>
        </div>
      </div>
    </SettingsCard>
  )
}

export function GeneralSection() {
  const t = useT()
  const { data: s } = useSettings()
  const save = useSaveSettings()
  const setLanguage = useUI((x) => x.setLanguage)
  return (
    <SectionStack>
      <SettingsCard title={t('settings.region')} description={t('settings.regionDesc')}>
        {!s ? (
          <Skeleton className="h-36" />
        ) : (
          <div className="max-w-lg">
            <RegionFields
              language={s.language}
              timezone={s.timezone}
              onLanguage={(l: Language) => {
                setLanguage(l)
                save.mutate({ language: l })
              }}
              onTimezone={(tz) => save.mutate({ timezone: tz }, { onSuccess: () => toast.success(t('common.saved')) })}
            />
          </div>
        )}
      </SettingsCard>
      <AppCard />
      <HelpCard />
    </SectionStack>
  )
}
