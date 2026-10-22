import { useT } from '@/i18n'
import { PackCards } from '@/features/packs/PackPicker'
import { SettingsCard, SectionStack } from './ui'

/** Settings -> Projects: add a starter pack (an existing project is never overwritten: only missing files are added). */
export function ProjectsSection() {
  const t = useT()
  return (
    <SectionStack>
      <SettingsCard title={t('packs.title')} description={t('packs.desc')}>
        <PackCards />
      </SettingsCard>
    </SectionStack>
  )
}
