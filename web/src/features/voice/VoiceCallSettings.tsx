// Settings -> Voice -> Voice mode: which voice talks with the user during a call (local on this server, or a cloud
// realtime model: OpenAI or Gemini, with the keys found in the vault). The session always does the work.
import * as React from 'react'
import { Link } from 'react-router'
import { Check, Cloud, Cpu, Download } from 'lucide-react'
import { useT } from '@/i18n'
import { Badge, Button, Input, SecretInput, Segmented, Select, Spinner, toast } from '@/components/ui'
import { Callout, OptionCard, SettingRow } from '@/features/common'
import { useCallSettings, useCallStatus, useInstallLocalVoice, useSaveCallKey, type CallProvider, type CallStatus } from './call/api'

const PROVIDER_NAME: Record<CallProvider, string> = { openai: 'OpenAI Realtime', gemini: 'Gemini Live' }
const STD_KEY: Record<CallProvider, string> = { openai: 'OPENAI_API_KEY', gemini: 'GEMINI_API_KEY' }
const SPEEDS = [1, 1.15, 1.3, 1.45]
const SILENCES = [1200, 1800, 2500, 3500]

export function VoiceCallSettings() {
  const t = useT()
  const { data: st } = useCallStatus()
  const save = useCallSettings()
  if (!st) return <Spinner className="size-4" />
  const s = st.settings
  return (
    <div className="grid gap-4">
      <div className="grid gap-2 sm:grid-cols-2">
        <OptionCard
          name="vmode-mode"
          value="local"
          icon={Cpu}
          selected={s.mode === 'local'}
          onSelect={() => save.mutate({ mode: 'local' })}
          title={t('vmode.set.local')}
          badge={st.local.ready ? <Badge variant="success">{t('vmode.set.ready')}</Badge> : null}
          description={t('vmode.set.localDesc')}
        />
        <OptionCard
          name="vmode-mode"
          value="cloud"
          icon={Cloud}
          selected={s.mode === 'cloud'}
          onSelect={() => save.mutate({ mode: 'cloud' })}
          title={t('vmode.set.cloud')}
          badge={st.cloud.ready ? <Badge variant="success">{st.provider ? PROVIDER_NAME[st.provider] : t('vmode.set.ready')}</Badge> : null}
          description={t('vmode.set.cloudDesc')}
        />
      </div>
      {s.mode === 'local' ? <LocalSettings st={st} /> : <CloudSettings st={st} />}
    </div>
  )
}

function LocalSettings({ st }: { st: CallStatus }) {
  const t = useT()
  const save = useCallSettings()
  const install = useInstallLocalVoice()
  const s = st.settings
  const tts = st.local.tts
  const running = tts.install.state === 'running'
  return (
    <div className="grid gap-3">
      {st.local.reason === 'stt' && <Callout tone="warning" title={t('vmode.set.needStt')} />}
      {!tts.ready && (
        <Callout
          tone={tts.install.state === 'failed' ? 'error' : 'info'}
          title={t('vmode.set.needTts')}
          action={
            <Button size="sm" onClick={() => install.mutate(undefined)} loading={running || install.isPending}>
              <Download /> {t('vmode.set.install')}
            </Button>
          }
        >
          {tts.install.state === 'failed' ? tts.install.error : t('vmode.set.needTtsDesc')}
        </Callout>
      )}
      <div className="divide-y">
        <SettingRow label={t('vmode.set.talker')} description={t('vmode.set.talkerDesc')} htmlFor="vmode-talker">
          <Select
            id="vmode-talker"
            className="w-44"
            value={s.talker_model}
            onValueChange={(v) => save.mutate({ talker_model: v as 'haiku' | 'sonnet' })}
            options={[
              { value: 'haiku', label: t('vmode.set.haiku') },
              { value: 'sonnet', label: t('vmode.set.sonnet') },
            ]}
          />
        </SettingRow>
        <SettingRow label={t('vmode.set.silence')} description={t('vmode.set.silenceDesc')}>
          <Segmented
            size="sm"
            aria-label={t('vmode.set.silence')}
            value={String(SILENCES.reduce((a, b) => (Math.abs(b - s.silence_ms) < Math.abs(a - s.silence_ms) ? b : a)))}
            onChange={(v) => save.mutate({ silence_ms: Number(v) })}
            options={SILENCES.map((v) => ({ value: String(v), label: `${(v / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })} s` }))}
          />
        </SettingRow>
        <SettingRow label={t('vmode.set.voice')} description={t('vmode.set.localVoiceDesc')} htmlFor="vmode-lvoice">
          <Select
            id="vmode-lvoice"
            className="w-56"
            value={s.local_voice}
            onValueChange={(v) => {
              save.mutate({ local_voice: v })
              if (v !== 'auto' && !tts.voices.includes(v)) install.mutate([v])
            }}
            options={[
              { value: 'auto', label: t('vmode.set.auto') },
              ...tts.catalogue.map((v) => ({ value: v.id, label: `${v.name} (${v.lang.toUpperCase()})${tts.voices.includes(v.id) ? '' : ' ↓'}` })),
            ]}
          />
          {running && <Spinner className="size-4" />}
        </SettingRow>
        <SettingRow label={t('vmode.set.speed')} description={t('vmode.set.speedDesc')}>
          <Segmented
            size="sm"
            aria-label={t('vmode.set.speed')}
            value={String(SPEEDS.reduce((a, b) => (Math.abs(b - s.local_speed) < Math.abs(a - s.local_speed) ? b : a)))}
            onChange={(v) => save.mutate({ local_speed: Number(v) })}
            options={SPEEDS.map((v) => ({ value: String(v), label: t(`vmode.set.speed${String(v).replace('.', '')}` as 'vmode.set.speed1') }))}
          />
        </SettingRow>
      </div>
    </div>
  )
}

function CloudSettings({ st }: { st: CallStatus }) {
  const t = useT()
  const save = useCallSettings()
  const s = st.settings
  const chosen = s.provider
  const both = st.keys.openai.found.length > 0 && st.keys.gemini.found.length > 0
  const shown: CallProvider | null = chosen || st.provider
  return (
    <div className="grid gap-3">
      {st.cloud.reason === 'choose' && <Callout tone="warning" title={t('vmode.set.chooseProvider')} />}
      <div className="grid gap-2 sm:grid-cols-2">
        {(['openai', 'gemini'] as const).map((p) => (
          <OptionCard
            key={p}
            name="vmode-provider"
            value={p}
            selected={shown === p && (!!chosen || !both)}
            onSelect={() => save.mutate({ provider: p })}
            title={PROVIDER_NAME[p]}
            badge={st.keys[p].found.length ? <Badge variant="success">{t('vmode.set.keyFound')}</Badge> : <Badge variant="muted">{t('vmode.set.noKey')}</Badge>}
            description={t(`vmode.set.${p}Desc` as 'vmode.set.openaiDesc')}
          />
        ))}
      </div>
      {shown && (chosen || !both) && <ProviderSettings st={st} p={shown} />}
    </div>
  )
}

function ProviderSettings({ st, p }: { st: CallStatus; p: CallProvider }) {
  const t = useT()
  const save = useCallSettings()
  const saveKey = useSaveCallKey()
  const [value, setValue] = React.useState('')
  const s = st.settings
  const k = st.keys[p]
  const model = p === 'openai' ? s.openai_model : s.gemini_model
  const [m, setM] = React.useState(model)
  React.useEffect(() => setM(model), [model])
  return (
    <div className="divide-y">
      <SettingRow label={t('vmode.set.key')} description={k.found.length > 1 ? t('vmode.set.keyChoose') : t('vmode.set.keyDesc')} htmlFor="vmode-key">
        {k.found.length > 0 ? (
          <>
            <Select
              id="vmode-key"
              className="w-64"
              value={k.using || undefined}
              placeholder={t('vmode.set.keyPick')}
              onValueChange={(v) => save.mutate(p === 'openai' ? { openai_key: v } : { gemini_key: v })}
              options={k.found.map((n) => ({ value: n, label: n }))}
            />
            {k.using && <Check className="size-4 text-success" />}
          </>
        ) : (
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (value.trim())
                saveKey.mutate(
                  { name: STD_KEY[p], value: value.trim() },
                  { onSuccess: () => (setValue(''), toast.success(t('voice.keySaved', { name: STD_KEY[p] }))) },
                )
            }}
          >
            <SecretInput className="w-64" value={value} onChange={(e) => setValue(e.target.value)} placeholder={STD_KEY[p]} aria-label={STD_KEY[p]} />
            <Button type="submit" disabled={!value.trim()} loading={saveKey.isPending}>
              {t('common.save')}
            </Button>
          </form>
        )}
      </SettingRow>
      <SettingRow label={t('vmode.set.voice')} htmlFor="vmode-cvoice">
        <Select
          id="vmode-cvoice"
          className="w-44"
          value={p === 'openai' ? s.openai_voice : s.gemini_voice}
          onValueChange={(v) => save.mutate(p === 'openai' ? { openai_voice: v } : { gemini_voice: v })}
          options={st.voices[p].map((v) => ({ value: v, label: v }))}
        />
      </SettingRow>
      <SettingRow label={t('vmode.set.model')} description={t('vmode.set.modelDesc')} htmlFor="vmode-model">
        <Input
          id="vmode-model"
          className="w-56"
          value={m}
          onChange={(e) => setM(e.target.value)}
          onBlur={() => m.trim() && m !== model && save.mutate(p === 'openai' ? { openai_model: m.trim() } : { gemini_model: m.trim() })}
        />
      </SettingRow>
      <p className="pt-3 text-[12px] text-muted-foreground">
        {t('vmode.set.privacy')}{' '}
        <Link to="/settings/keys" className="font-medium text-primary hover:underline">
          {t('settings.keys')}
        </Link>
      </p>
    </div>
  )
}
