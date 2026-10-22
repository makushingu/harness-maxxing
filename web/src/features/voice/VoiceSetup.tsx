// Voice settings blocks, shared by Settings → Voice and the onboarding (light version).
import * as React from 'react'
import { Link } from 'react-router'
import { Check, Cpu, Download, Mic, Square, Trash2, X } from 'lucide-react'
import { useT } from '@/i18n'
import { Badge, Button, ProgressBar, SecretInput, Select, Segmented, Spinner, Switch, confirm, toast } from '@/components/ui'
import { Callout, OptionCard, SettingRow } from '@/features/common'
import { cn } from '@/lib/utils'
import {
  VOICE_LANGUAGES,
  transcribe,
  useSaveVoiceKey,
  useVoice,
  useVoiceDeleteModel,
  useVoiceInstall,
  useVoiceSettings,
  type Transcript,
  type VoiceEngine,
  type VoiceModel,
  type VoiceStatus,
} from './api'
import { fmtClock, useRecorder } from './recorder'
import { LevelMeter, micErrorText } from './VoiceButton'

export function EngineChoice({ status, compact }: { status: VoiceStatus; compact?: boolean }) {
  const t = useT()
  const save = useVoiceSettings()
  const install = useVoiceInstall()
  const engine = status.settings.engine
  const pick = (e: VoiceEngine) => {
    save.mutate(
      { engine: e },
      {
        onSuccess: () => {
          // Local: install / download in the background right away (progress shown below).
          if (e === 'local' && (!status.local.installed || !status.local.models.find((m) => m.id === status.settings.model)?.present) && status.install.state !== 'running')
            install.mutate(undefined)
        },
      },
    )
  }
  const opts: { id: VoiceEngine; badge?: React.ReactNode }[] = [
    {
      id: 'local',
      badge: <Badge variant="muted">{t('voice.badge.private')}</Badge>,
    },
    {
      id: 'groq',
      badge: <Badge variant="muted">{t('voice.badge.fast')}</Badge>,
    },
    { id: 'openai' },
    { id: 'off' },
  ]
  return (
    <div className={cn('grid gap-2', !compact && 'sm:grid-cols-2')}>
      {opts.map((o) => (
        <OptionCard
          key={o.id}
          name="voice-engine"
          value={o.id}
          selected={engine === o.id}
          onSelect={() => pick(o.id)}
          title={t(`voice.engine.${o.id}` as 'voice.engine.local')}
          description={compact ? undefined : t(`voice.engine.${o.id}.desc` as 'voice.engine.local.desc')}
          badge={o.badge}
        />
      ))}
    </div>
  )
}

/** Local engine: install state, model choice, download progress. */
export function LocalEngine({ status }: { status: VoiceStatus }) {
  const t = useT()
  const save = useVoiceSettings()
  const install = useVoiceInstall()
  const del = useVoiceDeleteModel()
  const job = status.install
  const running = job.state === 'running'
  const model = status.settings.model
  const present = status.local.models.find((m) => m.id === model)?.present
  return (
    <div className="grid gap-4">
      <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
        <Cpu className="size-4" />{' '}
        {t('voice.server', {
          cpus: status.local.cpus,
          ram: status.local.ram_gb,
        })}
      </p>
      <div className="divide-y">
        <SettingRow label={t('voice.model')} description={t('voice.modelDesc')} htmlFor="voice-model">
          <Select
            id="voice-model"
            className="w-56"
            value={model}
            onValueChange={(v) => save.mutate({ model: v as VoiceModel })}
            options={status.local.models.map((m) => ({
              value: m.id,
              label: `${t(`voice.model.${m.id}` as 'voice.model.small')} · ${m.size_mb} MB${m.id === status.local.recommended ? ` · ${t('voice.recommended')}` : ''}${m.present ? ' ✓' : ''}`,
            }))}
          />
        </SettingRow>
      </div>
      {running ? (
        <div className="grid gap-2 rounded-lg border p-3.5" data-voice-install>
          <div className="flex items-center gap-2 text-sm font-medium">
            <Spinner className="size-4" /> {job.step === 'deps' ? t('voice.installing') : t('voice.downloading', { model: job.model || model })}
          </div>
          {job.step === 'model' && job.progress != null ? (
            <ProgressBar value={job.progress * 100} label={t('voice.downloading', { model: job.model || model })} />
          ) : (
            <ProgressBar value={15} className="animate-pulse" />
          )}
          <p className="text-[12px] text-muted-foreground">{job.step === 'model' && job.progress != null ? `${Math.round(job.progress * 100)} %` : t('voice.installHint')}</p>
        </div>
      ) : !status.local.installed || !present ? (
        <Callout
          tone={job.state === 'error' ? 'error' : 'info'}
          title={!status.local.installed ? t('voice.notInstalled') : t('voice.modelMissing', { model })}
          action={
            <Button size="sm" onClick={() => install.mutate(undefined)} loading={install.isPending}>
              <Download /> {!status.local.installed ? t('voice.install') : t('voice.download')}
            </Button>
          }
        >
          {job.state === 'error' ? job.error : !status.local.installed ? t('voice.notInstalledDesc') : t('voice.modelMissingDesc')}
        </Callout>
      ) : (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Check className="size-4 text-success" /> {t('voice.modelReady', { model })}
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto text-muted-foreground"
            loading={del.isPending}
            onClick={async () => {
              if (
                await confirm({
                  title: t('voice.deleteModel', { model }),
                  description: t('voice.deleteModelDesc'),
                  destructive: true,
                  confirmText: t('common.delete'),
                })
              )
                del.mutate(model)
            }}
          >
            <Trash2 /> {t('voice.deleteModel', { model })}
          </Button>
        </div>
      )}
    </div>
  )
}

/** Groq / OpenAI: API key (stored in the Keys vault). */
export function ApiEngine({ status, engine }: { status: VoiceStatus; engine: 'groq' | 'openai' }) {
  const t = useT()
  const [value, setValue] = React.useState('')
  const saveKey = useSaveVoiceKey()
  const name = status.key_names[engine]
  const has = status.keys[engine]
  return (
    <div className="grid gap-3">
      <p className="text-[13px] text-muted-foreground">{t(`voice.${engine}.how` as 'voice.groq.how')}</p>
      {has && (
        <p className="flex items-center gap-2 text-sm">
          <Check className="size-4 text-success" /> {t('voice.keyFound', { name })}
        </p>
      )}
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (value.trim())
            saveKey.mutate(
              { name, value: value.trim() },
              {
                onSuccess: () => (setValue(''), toast.success(t('voice.keySaved', { name }))),
              },
            )
        }}
      >
        <SecretInput
          className="min-w-0 flex-1 basis-60"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={has ? t('voice.keyReplace', { name }) : name}
          aria-label={name}
        />
        <Button type="submit" variant={has ? 'outline' : 'default'} disabled={!value.trim()} loading={saveKey.isPending}>
          {t('common.save')}
        </Button>
      </form>
      <p className="text-[12px] text-muted-foreground">
        {t('voice.keyVault')}{' '}
        <Link to="/settings/keys" className="font-medium text-primary hover:underline">
          {t('settings.keys')}
        </Link>
      </p>
    </div>
  )
}

export function VoiceOptions({ status }: { status: VoiceStatus }) {
  const t = useT()
  const save = useVoiceSettings()
  const s = status.settings
  return (
    <div className="divide-y">
      <SettingRow label={t('voice.language')} description={t('voice.languageDesc')} htmlFor="voice-lang">
        <Select
          id="voice-lang"
          className="w-56"
          value={s.language}
          onValueChange={(v) => save.mutate({ language: v })}
          options={[{ value: 'auto', label: t('voice.languageAuto') }, ...VOICE_LANGUAGES.map((l) => ({ value: l.id, label: l.label }))]}
        />
      </SettingRow>
      <SettingRow label={t('voice.direct')} description={t('voice.directDesc')} htmlFor="voice-direct">
        <Switch id="voice-direct" checked={s.direct !== false} onCheckedChange={(v) => save.mutate({ direct: v })} />
      </SettingRow>
      {s.direct === false && (
        <SettingRow label={t('voice.autoSend')} description={t('voice.autoSendDesc')} htmlFor="voice-auto">
          <Switch id="voice-auto" checked={s.auto_send} onCheckedChange={(v) => save.mutate({ auto_send: v })} />
        </SettingRow>
      )}
    </div>
  )
}

/** Record a few seconds and show the transcript + timings. */
export function RecordTest({ status }: { status: VoiceStatus }) {
  const t = useT()
  const [busy, setBusy] = React.useState(false)
  const [res, setRes] = React.useState<Transcript | null>(null)
  const [err, setErr] = React.useState<string | null>(null)
  const stopRef = React.useRef<() => void>(() => {})
  const rec = useRecorder({ maxSeconds: 60, onLimit: () => stopRef.current() })
  const stop = async () => {
    const blob = await rec.stop()
    if (!blob) return
    setBusy(true)
    try {
      setRes(await transcribe(blob))
    } catch (e) {
      setErr(micErrorText(t, e))
    } finally {
      setBusy(false)
    }
  }
  stopRef.current = () => void stop()
  const start = async () => {
    setRes(null)
    setErr(null)
    try {
      await rec.start()
    } catch (e) {
      setErr(micErrorText(t, e))
    }
  }
  const recording = rec.state !== 'idle'
  return (
    <div className="grid gap-3" data-voice-test>
      <div className="flex flex-wrap items-center gap-3">
        {recording ? (
          <>
            <Button variant="destructive" onClick={() => void stop()} disabled={rec.state === 'starting'}>
              <Square className="fill-current" /> {t('voice.stopTest')}
            </Button>
            <Button variant="ghost" size="icon" aria-label={t('voice.cancel')} onClick={rec.cancel}>
              <X />
            </Button>
            <span className="text-sm font-medium tabular-nums">{fmtClock(rec.elapsed)}</span>
            <LevelMeter level={rec.level} />
          </>
        ) : (
          <Button onClick={() => void start()} disabled={!status.ready || busy} loading={busy}>
            <Mic /> {busy ? t('voice.transcribing') : t('voice.startTest')}
          </Button>
        )}
        {!status.ready && !recording && <span className="text-[13px] text-muted-foreground">{t('voice.testNeedsEngine')}</span>}
      </div>
      {err && <Callout tone="error">{err}</Callout>}
      {res && (
        <div className="grid gap-2 rounded-lg border bg-muted/30 p-3.5" data-voice-result>
          <p className="text-sm whitespace-pre-wrap">{res.text || <span className="text-muted-foreground">{t('voice.noSpeech')}</span>}</p>
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted-foreground tabular-nums">
            <span>{t('voice.stat.audio', { s: res.duration_s.toFixed(1) })}</span>
            <span>{t('voice.stat.time', { s: (res.ms / 1000).toFixed(1) })}</span>
            {res.language && <span>{t('voice.stat.lang', { lang: res.language })}</span>}
            <span>
              {res.engine}
              {res.model ? ` · ${res.model}` : ''}
            </span>
          </p>
        </div>
      )}
    </div>
  )
}

/** Onboarding: one-line engine picker + status (everything else lives in Settings → Voice). */
export function VoiceQuickSetup() {
  const t = useT()
  const { data: s } = useVoice()
  const save = useVoiceSettings()
  const install = useVoiceInstall()
  if (!s) return null
  const pick = (e: VoiceEngine) =>
    save.mutate(
      { engine: e },
      {
        onSuccess: () =>
          e === 'local' && s.install.state !== 'running' && (!s.local.installed || !s.local.models.find((m) => m.id === s.settings.model)?.present) && install.mutate(undefined),
      },
    )
  return (
    <div className="grid gap-3 rounded-lg border p-4" data-voice-quick>
      <div className="grid gap-1">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Mic className="size-4" /> {t('voice.onb.title')} <Badge variant="muted">{t('voice.optional')}</Badge>
        </h3>
        <p className="text-[13px] text-muted-foreground">{t('voice.onb.desc')}</p>
      </div>
      <Segmented
        value={s.settings.engine}
        onChange={pick}
        aria-label={t('voice.engine')}
        options={(['off', 'local', 'groq', 'openai'] as VoiceEngine[]).map((e) => ({
          value: e,
          label: t(`voice.engine.${e}` as 'voice.engine.local'),
        }))}
      />
      <p className="text-[12px] text-muted-foreground">
        {s.install.state === 'running'
          ? `${s.install.step === 'deps' ? t('voice.installing') : t('voice.downloading', { model: s.install.model || s.settings.model })}${s.install.progress != null ? ` ${Math.round(s.install.progress * 100)} %` : ''}`
          : s.settings.engine === 'off'
            ? t('voice.onb.offHint')
            : s.ready
              ? t('voice.onb.ready')
              : s.reason === 'no_key'
                ? t('voice.onb.needKey', {
                    name: s.key_names[s.settings.engine as 'groq' | 'openai'],
                  })
                : t('voice.notReadyHint')}{' '}
        <Link to="/settings/voice" className="font-medium text-primary hover:underline">
          {t('voice.onb.more')}
        </Link>
      </p>
    </div>
  )
}
