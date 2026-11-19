import { useT } from '@/i18n'
import { Skeleton, Switch } from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { useVoice, useVoiceSettings } from '@/features/voice/api'
import { ApiEngine, EngineChoice, LocalEngine, RecordTest, VoiceOptions } from '@/features/voice/VoiceSetup'
import { VoiceCallSettings } from '@/features/voice/VoiceCallSettings'
import { SettingsCard, SectionStack } from './ui'

export function VoiceSection() {
  const t = useT()
  const { data: s } = useVoice()
  const save = useVoiceSettings()
  if (!s) return <Skeleton className="h-72 rounded-xl" />
  const engine = s.settings.engine
  return (
    <SectionStack>
      <SettingsCard title={t('vmode.btn.card')} description={t('vmode.btn.cardDesc')}>
        <div className="grid gap-4">
          <SettingRow label={t('vmode.btn.mic')} description={t('vmode.btn.micDesc')} htmlFor="mx-voice-mic">
            <Switch id="mx-voice-mic" checked={s.settings.mic !== false} onCheckedChange={(v) => save.mutate({ mic: v })} />
          </SettingRow>
          <SettingRow label={t('vmode.btn.call')} description={t('vmode.btn.callDesc')} htmlFor="mx-voice-call">
            <Switch id="mx-voice-call" checked={s.settings.call !== false} onCheckedChange={(v) => save.mutate({ call: v })} />
          </SettingRow>
        </div>
      </SettingsCard>
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
      <SettingsCard title={t('vmode.card')} description={t('vmode.cardDesc')}>
        <VoiceCallSettings />
      </SettingsCard>
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
