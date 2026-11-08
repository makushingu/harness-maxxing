// Settings -> Templates (2.0.0a132, was Projects / Starter pack): add a ready-made project. An existing project is never
// overwritten: only missing files are added. Projects and topics themselves are managed from the sidebar.
import { useT } from '@/i18n'
import { PackCards } from '@/features/packs/PackPicker'
import { SettingsCard, SectionStack } from './ui'

export function TemplatesSection() {
  const t = useT()
  return (
    <SectionStack>
      <SettingsCard title={t('packs.title')} description={t('packs.desc')}>
        <PackCards />
      </SettingsCard>
    </SectionStack>
  )
}
