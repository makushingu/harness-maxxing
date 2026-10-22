// Settings -> Support: Harness Maxxing is free, donations fund its development (a link to the website, nothing
// else) + the switch that hides the other donation mentions of the app (setting `donation_hidden`).
import { ExternalLink, HandHeart } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { useSaveSettings, useSettings } from '@/lib/queries'
import { Button, Skeleton, Switch } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { donationUrl } from '@/features/donation/Donation'
import { SettingsCard, SectionStack } from './ui'

export function SupportSection() {
  const t = useT()
  const lang = useLang()
  const { data: s } = useSettings()
  const save = useSaveSettings()
  if (!s) return <Skeleton className="h-56 rounded-xl" />
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
        </div>
      </SettingsCard>
      <SettingsCard>
        <SettingRow label={t('donation.hide')} description={t('donation.hideDesc')} htmlFor="donation-hidden">
          <Switch id="donation-hidden" checked={!!s.donation_hidden} onCheckedChange={(v) => save.mutate({ donation_hidden: v })} />
        </SettingRow>
      </SettingsCard>
    </SectionStack>
  )
}
