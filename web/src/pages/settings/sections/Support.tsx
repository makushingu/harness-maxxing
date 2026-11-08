// Settings -> Support (2.0.0a132, the last section): the donation link and the switch that hides the other
// donation mentions (`donation_hidden`).
import { ExternalLink, HandHeart } from 'lucide-react'
import { useSaveSettings, useSettings } from '@/lib/queries'
import { useLang, useT } from '@/i18n'
import { Button, Switch } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { donationUrl } from '@/features/donation/Donation'
import { SettingsCard, SectionStack } from './ui'

export function SupportSection() {
  const t = useT()
  const lang = useLang()
  const { data: s } = useSettings()
  const save = useSaveSettings()
  return (
    <SectionStack>
      <SettingsCard title={t('donation.title')} description={t('donation.desc')}>
        <div className="grid gap-4">
          <p className="max-w-2xl text-sm text-muted-foreground">{t('donation.body')}</p>
          <div>
            <Button size="sm" asChild>
              <a href={donationUrl(lang)} target="_blank" rel="noopener">
                <HandHeart /> {t('donation.donate')} <ExternalLink />
              </a>
            </Button>
          </div>
          {s && (
            <div className="border-t">
              <SettingRow label={t('donation.hide')} description={t('donation.hideDesc')} htmlFor="donation-hidden">
                <Switch id="donation-hidden" checked={!!s.donation_hidden} onCheckedChange={(on) => save.mutate({ donation_hidden: on })} />
              </SettingRow>
            </div>
          )}
        </div>
      </SettingsCard>

    </SectionStack>
  )
}
