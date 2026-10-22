import { useT } from '@/i18n'
import { ImportWizard } from '@/features/import/ImportWizard'
import { SettingsCard, SectionStack } from './ui'

export function ImportSection() {
  const t = useT()
  return (
    <SectionStack>
      <SettingsCard title={t('import.title')} description={t('import.desc')}>
        <ImportWizard />
      </SettingsCard>
    </SectionStack>
  )
}
