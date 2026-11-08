// Settings -> Import: bring in what was elsewhere - the memory of another agent (Hermes, OpenClaw, Claude Code, a zip),
// and the ways to the other imports (a memory backup on a new server, an agent file .md).
import { Link } from 'react-router'
import { ArrowRight } from 'lucide-react'
import { useT } from '@/i18n'
import { useSettings } from '@/lib/queries'
import { ImportWizard } from '@/features/import/ImportWizard'
import { SettingRow } from '@/features/common'
import { Button } from '@/components/ui'
import { SettingsCard, SectionStack } from './ui'

export function ImportSection() {
  const t = useT()
  const { data: s } = useSettings()
  return (
    <SectionStack>
      <SettingsCard title={t('import.title')} description={t('import.desc')}>
        <ImportWizard />
      </SettingsCard>
      <SettingsCard title={t('import.more')}>
        <div className="divide-y">
          <SettingRow label={t('import.restore')} description={t('import.restoreDesc')}>
            <Button variant="outline" size="sm" asChild>
              <Link to="/settings/backup">{t('settings.backup')} <ArrowRight /></Link>
            </Button>
          </SettingRow>
          {!!s?.agents_page && (
            <SettingRow label={t('import.agentFile')} description={t('import.agentDesc')}>
              <Button variant="outline" size="sm" asChild>
                <Link to="/agents">{t('nav.agents')} <ArrowRight /></Link>
              </Button>
            </SettingRow>
          )}
        </div>
      </SettingsCard>
    </SectionStack>
  )
}
