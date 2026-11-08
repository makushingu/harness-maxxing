// Settings -> About (2.0.0a132, was License + Support): the version and the useful links, the optional
// Enterprise key, the donation link and the switch that hides the other donation mentions (`donation_hidden`).
import * as React from 'react'
import { Link } from 'react-router'
import { BookOpen, ExternalLink, GitBranch, HandHeart, History, KeyRound } from 'lucide-react'
import { useLicense, useRemoveLicense, useSaveSettings, useSettings, useVersion } from '@/lib/queries'
import { useLang, useT } from '@/i18n'
import { Button, Skeleton, Switch } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { ENTERPRISE_URL, LICENSE_URL, LicenseKeyField, WhoNeedsAKey } from '@/features/license/LicenseKey'
import { donationUrl } from '@/features/donation/Donation'
import { SettingsCard, SectionStack } from './ui'

const REPO_URL = 'https://github.com/makushingu/harness-maxxing'

export function AboutSection() {
  const t = useT()
  const lang = useLang()
  const { data: v } = useVersion()
  const { data: lic } = useLicense()
  const { data: s } = useSettings()
  const save = useSaveSettings()
  const remove = useRemoveLicense()
  const [key, setKey] = React.useState('')
  const kind = lic?.kind === 'beta' ? t('system.licenseKind.beta') : lic?.kind === 'gift' ? t('system.licenseKind.gift') : lic?.kind === 'enterprise' ? t('system.licenseKind.enterprise') : t('system.licenseKind.paid')
  return (
    <SectionStack>
      <SettingsCard title="Harness Maxxing" description={t('about.desc')}>
        <div className="grid gap-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            {v ? <span className="text-2xl font-semibold tracking-tight tabular-nums">v{v.version}</span> : <Skeleton className="h-8 w-32" />}
            <Link to="/settings/system" className="text-sm text-primary hover:underline">{t('about.checkUpdates')}</Link>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link to="/settings/updates"><History /> {t('settings.updates')}</Link>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link to="/docs"><BookOpen /> {t('nav.docs')}</Link>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a href={REPO_URL} target="_blank" rel="noreferrer"><GitBranch /> GitHub <ExternalLink /></a>
            </Button>
          </div>
        </div>
      </SettingsCard>

      <SettingsCard
        title={t('license.title')}
        description={t('license.desc')}
        actions={
          <Button variant="outline" size="sm" asChild>
            <a href={LICENSE_URL} target="_blank" rel="noreferrer">
              {t('license.read')} <ExternalLink />
            </a>
          </Button>
        }
      >
        <WhoNeedsAKey />
        <div className="mt-5 border-t pt-4">
          {!lic ? (
            <Skeleton className="h-10" />
          ) : lic.has_key ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="min-w-0 text-sm">
                <KeyRound className="mr-1.5 inline size-4 align-[-3px] text-muted-foreground" />
                {t('license.active', { key: lic.key_hint, kind })}
                {lic.email ? <span className="text-muted-foreground [overflow-wrap:anywhere]"> · {lic.email}</span> : null}
                {lic.expires_at ? <span className="text-muted-foreground"> · {t('license.until', { date: new Date(lic.expires_at * 1000).toLocaleDateString(lang) })}</span> : null}
              </p>
              <Button variant="outline" size="sm" loading={remove.isPending} onClick={() => remove.mutate()} title={t('license.removeDesc')}>
                {t('license.remove')}
              </Button>
            </div>
          ) : (
            <div className="grid gap-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-muted-foreground">{t('license.none')}</p>
                <Button variant="ghost" size="sm" asChild>
                  <a href={ENTERPRISE_URL} target="_blank" rel="noreferrer">
                    {t('license.get')} <ExternalLink />
                  </a>
                </Button>
              </div>
              <LicenseKeyField value={key} onChange={setKey} withButton />
            </div>
          )}
        </div>
      </SettingsCard>

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
