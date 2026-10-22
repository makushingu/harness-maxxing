import * as React from 'react'
import { ExternalLink, KeyRound } from 'lucide-react'
import { useLicense, useRemoveLicense } from '@/lib/queries'
import { useLang, useT } from '@/i18n'
import { Button, Skeleton } from '@/components/ui'
import { ENTERPRISE_URL, LICENSE_URL, LicenseKeyField, WhoNeedsAKey } from '@/features/license/LicenseKey'
import { SettingsCard, SectionStack } from './ui'

export function LicenseSection() {
  const t = useT()
  const lang = useLang()
  const { data: lic } = useLicense()
  const remove = useRemoveLicense()
  const [key, setKey] = React.useState('')
  if (!lic) return <Skeleton className="h-72 rounded-xl" />
  const kind = lic.kind === 'beta' ? t('system.licenseKind.beta') : lic.kind === 'gift' ? t('system.licenseKind.gift') : lic.kind === 'enterprise' ? t('system.licenseKind.enterprise') : t('system.licenseKind.paid')
  return (
    <SectionStack>
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
        <Button className="mt-4" size="sm" asChild>
          <a href={ENTERPRISE_URL} target="_blank" rel="noreferrer">
            {t('license.get')} <ExternalLink />
          </a>
        </Button>
      </SettingsCard>
      <SettingsCard title={t('license.yours')}>
        {lic.has_key ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm">
              <KeyRound className="mr-1.5 inline size-4 align-[-3px] text-muted-foreground" />
              {t('license.active', { key: lic.key_hint, kind })}
              {lic.email ? <span className="text-muted-foreground"> · {lic.email}</span> : null}
              {lic.expires_at ? <span className="text-muted-foreground"> · {t('license.until', { date: new Date(lic.expires_at * 1000).toLocaleDateString(lang) })}</span> : null}
            </p>
            <Button variant="outline" size="sm" loading={remove.isPending} onClick={() => remove.mutate()} title={t('license.removeDesc')}>
              {t('license.remove')}
            </Button>
          </div>
        ) : (
          <div className="grid gap-3">
            <p className="text-sm text-muted-foreground">{t('license.none')}</p>
            <LicenseKeyField value={key} onChange={setKey} withButton />
          </div>
        )}
      </SettingsCard>
    </SectionStack>
  )
}
