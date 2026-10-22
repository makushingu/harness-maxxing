import { useT } from '@/i18n'
import { Skeleton } from '@/components/ui'
import { Callout } from '@/features/common'
import { useVoice } from '@/features/voice/api'
import { ApiEngine, EngineChoice, LocalEngine, RecordTest, VoiceOptions } from '@/features/voice/VoiceSetup'
import { SettingsCard, SectionStack } from './ui'

export function VoiceSection() {
  const t = useT()
  const { data: s } = useVoice()
  if (!s) return <Skeleton className="h-72 rounded-xl" />
  const engine = s.settings.engine
  return (
    <SectionStack>
      <SettingsCard title={t('voice.engine')} description={t('voice.engineDesc')}>
        <EngineChoice status={s} />
        {!s.ffmpeg && engine !== 'off' && (
          <Callout tone="error" className="mt-4" title={t('voice.noFfmpeg')}>
            <code>apt-get install -y ffmpeg</code>
          </Callout>
        )}
      </SettingsCard>
      {engine === 'local' && (
        <SettingsCard title={t('voice.engine.local')} description={t('voice.localDesc')}>
          <LocalEngine status={s} />
        </SettingsCard>
      )}
      {(engine === 'groq' || engine === 'openai') && (
        <SettingsCard title={t(`voice.engine.${engine}`)} description={t('voice.apiDesc')}>
          <ApiEngine status={s} engine={engine} />
        </SettingsCard>
      )}
      {engine !== 'off' && (
        <>
          <SettingsCard title={t('voice.options')}>
            <VoiceOptions status={s} />
          </SettingsCard>
          <SettingsCard title={t('voice.test')} description={t('voice.testDesc')}>
            <RecordTest status={s} />
          </SettingsCard>
        </>
      )}
    </SectionStack>
  )
}
