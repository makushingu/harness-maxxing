import * as React from 'react'
import { useLocation } from 'react-router'
import { useT } from '@/i18n'
import { PackCards } from '@/features/packs/PackPicker'
import { ImportWizard } from '@/features/import/ImportWizard'
import { SettingsCard, SectionStack } from './ui'

/** Settings -> Projects: add a starter pack (an existing project is never overwritten: only missing files are added),
 *  or bring the memory of another agent (was Settings -> Import; /settings/import lands on #import). */
export function ProjectsSection() {
  const t = useT()
  const { hash } = useLocation()
  const importRef = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    if (hash === '#import') importRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }, [hash])
  return (
    <SectionStack>
      <SettingsCard title={t('packs.title')} description={t('packs.desc')}>
        <PackCards />
      </SettingsCard>
      <div id="import" ref={importRef} className="scroll-mt-[calc(var(--header-h)+1.5rem)]">
        <SettingsCard title={t('import.title')} description={t('import.desc')}>
          <ImportWizard />
        </SettingsCard>
      </div>
    </SectionStack>
  )
}
