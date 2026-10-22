import { useT } from '@/i18n'
import { ClaudeConnect } from '@/features/claude/ClaudeConnect'
import { ClaudeDefaults } from '@/features/claude/ClaudeDefaults'
import { SettingsCard, SectionStack } from './ui'

export function ClaudeSection() {
  const t = useT()
  return (
    <SectionStack>
      <SettingsCard title={t('claude.connection')} description={t('claude.connectionDesc')}>
        <ClaudeConnect />
      </SettingsCard>
      <SettingsCard title={t('claude.defaults')} description={t('claude.defaultsDesc')}>
        <ClaudeDefaults />
      </SettingsCard>
    </SectionStack>
  )
}
