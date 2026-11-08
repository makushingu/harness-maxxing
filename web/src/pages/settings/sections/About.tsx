// Settings -> About (2.0.0a132, was License): the version and the useful links, then the optional Enterprise key.
import * as React from 'react'
import { Link } from 'react-router'
import { BookOpen, ExternalLink, GitBranch, KeyRound, Users } from 'lucide-react'
import { useLicense, useRemoveLicense, useVersion } from '@/lib/queries'
import { useLang, useT } from '@/i18n'
import { Button, Skeleton } from '@/components/ui'
import { ENTERPRISE_URL, LICENSE_URL, LicenseKeyField, WhoNeedsAKey } from '@/features/license/LicenseKey'
import { SettingsCard, SectionStack } from './ui'

const REPO_URL = 'https://github.com/makushingu/harness-maxxing'
export const COMMUNITY_URL = 'https://harness-maxxing.com/community'

export function AboutSection() {
  const t = useT()
  const lang = useLang()
  const { data: v } = useVersion()
  const { data: lic } = useLicense()
  const remove = useRemoveLicense()
  const [key, setKey] = React.useState('')
  const kind = lic?.kind === 'beta' ? t('system.licenseKind.beta') : lic?.kind === 'gift' ? t('system.licenseKind.gift') : lic?.kind === 'enterprise' ? t('system.licenseKind.enterprise') : t('system.licenseKind.paid')
  return (
    <SectionStack>
      <SettingsCard title="Harness Maxxing" description={t('about.desc')}>
        <div className="grid gap-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            {v ? <span className="text-sm font-medium tabular-nums">{t('about.version', { version: v.version })}</span> : <Skeleton className="h-5 w-32" />}
            <Link to="/settings/updates" className="text-sm text-primary hover:underline">{t('about.checkUpdates')}</Link>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link to="/docs"><BookOpen /> {t('nav.docs')}</Link>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a href={REPO_URL} target="_blank" rel="noreferrer"><GitBranch /> GitHub <ExternalLink /></a>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a href={COMMUNITY_URL} target="_blank" rel="noreferrer"><Users /> {t('about.community')} <ExternalLink /></a>
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

    </SectionStack>
  )
}
