// Schedule editor: presets (every N minutes, hourly, daily, weekdays, weekly, monthly) + raw expression,
// with a live server preview (human text + next 5 runs in the configured time zone).
import * as React from 'react'
import { AlertCircle, CalendarClock } from 'lucide-react'
import { useLang, useT, type TKey } from '@/i18n'
import { fmtDate, fmtRelative } from '@/lib/format'
import { useCronPreview, useSettings } from '@/lib/queries'
import { Input, Label, Select, Skeleton } from '@/components/ui'
import { cap } from './parts'
import { PRESET_KINDS, fromPreset, hhmm, toPreset, weekdayNames, type Preset, type PresetKind } from './schedule'

export function useDebounced<T>(v: T, ms = 300) {
  const [d, setD] = React.useState(v)
  React.useEffect(() => {
    const id = setTimeout(() => setD(v), ms)
    return () => clearTimeout(id)
  }, [v, ms])
  return d
}

const KIND_KEY: Record<PresetKind, TKey> = {
  minutes: 'crons.preset.minutes',
  hours: 'crons.preset.hours',
  hourly: 'crons.preset.hourly',
  daily: 'crons.preset.daily',
  weekdays: 'crons.preset.weekdays',
  weekly: 'crons.preset.weekly',
  monthly: 'crons.preset.monthly',
  custom: 'crons.preset.custom',
}
const MINUTE_STEPS = [1, 2, 3, 5, 10, 15, 20, 30]
const HOUR_STEPS = [1, 2, 3, 4, 6, 8, 12]

export function SchedulePicker({ value, onChange, error }: { value: string; onChange: (expr: string) => void; error?: string }) {
  const t = useT()
  const lang = useLang()
  const [preset, setPreset] = React.useState<Preset>(() => toPreset(value))
  const days = React.useMemo(() => weekdayNames(lang), [lang])
  const id = React.useId()

  const update = (patch: Partial<Preset>) => {
    const np = { ...preset, ...patch }
    setPreset(np)
    const e = fromPreset(np)
    if (e) onChange(e)
  }
  const time = (
    <Input
      type="time"
      aria-label={t('crons.at')}
      value={hhmm(preset.hour, preset.minute)}
      onChange={(e) => {
        const [h, m] = e.target.value.split(':').map(Number)
        if (Number.isFinite(h) && Number.isFinite(m)) update({ hour: h, minute: m })
      }}
      className="w-36"
      required
    />
  )
  const minuteInput = (
    <Input
      type="number"
      min={0}
      max={59}
      aria-label={t('crons.atMinute')}
      value={preset.minute}
      onChange={(e) => {
        const n = Math.max(0, Math.min(59, Math.round(Number(e.target.value) || 0)))
        update({ minute: n })
      }}
      className="w-20 tabular-nums"
    />
  )

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={preset.kind}
          onValueChange={(k) => update({ kind: k as PresetKind })}
          aria-label={t('crons.frequency')}
          className="w-auto min-w-44"
          options={PRESET_KINDS.map((k) => ({ value: k, label: t(KIND_KEY[k]) }))}
        />
        {preset.kind === 'minutes' && (
          <Select
            value={String(preset.every)}
            onValueChange={(v) => update({ every: Number(v) })}
            aria-label={t('crons.interval')}
            className="w-auto min-w-36"
            options={[...new Set([...MINUTE_STEPS, preset.every])].sort((a, b) => a - b).map((n) => ({ value: String(n), label: t('crons.everyNMin', { count: n }) }))}
          />
        )}
        {preset.kind === 'hours' && (
          <>
            <Select
              value={String(preset.every)}
              onValueChange={(v) => update({ every: Number(v) })}
              aria-label={t('crons.interval')}
              className="w-auto min-w-36"
              options={[...new Set([...HOUR_STEPS, preset.every])].sort((a, b) => a - b).map((n) => ({ value: String(n), label: t('crons.everyNHours', { count: n }) }))}
            />
            <span className="text-sm text-muted-foreground">{t('crons.atMinuteLabel')}</span>
            {minuteInput}
          </>
        )}
        {preset.kind === 'hourly' && (
          <>
            <span className="text-sm text-muted-foreground">{t('crons.atMinuteLabel')}</span>
            {minuteInput}
          </>
        )}
        {(preset.kind === 'daily' || preset.kind === 'weekdays') && (
          <>
            <span className="text-sm text-muted-foreground">{t('crons.atLabel')}</span>
            {time}
          </>
        )}
        {preset.kind === 'weekly' && (
          <>
            <Select
              value={String(preset.weekday)}
              onValueChange={(v) => update({ weekday: Number(v) })}
              aria-label={t('crons.weekday')}
              className="w-auto min-w-36"
              options={[1, 2, 3, 4, 5, 6, 0].map((d) => ({ value: String(d), label: days[d] }))}
            />
            <span className="text-sm text-muted-foreground">{t('crons.atLabel')}</span>
            {time}
          </>
        )}
        {preset.kind === 'monthly' && (
          <>
            <Select
              value={String(preset.day)}
              onValueChange={(v) => update({ day: Number(v) })}
              aria-label={t('crons.dayOfMonth')}
              className="w-auto min-w-28"
              options={Array.from({ length: 31 }, (_, i) => ({ value: String(i + 1), label: t('crons.dayN', { n: i + 1 }) }))}
            />
            <span className="text-sm text-muted-foreground">{t('crons.atLabel')}</span>
            {time}
          </>
        )}
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-raw`} className="text-[13px] font-normal text-muted-foreground">
          {t('crons.expression')}
        </Label>
        <Input
          id={`${id}-raw`}
          value={value}
          onChange={(e) => {
            onChange(e.target.value)
            setPreset((cur) => toPreset(e.target.value, cur))
          }}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          aria-invalid={!!error || undefined}
          className="max-w-xs font-mono"
          data-testid="cron-expression"
        />
      </div>
      <SchedulePreview schedule={value} />
    </div>
  )
}

/** Human text + next runs. Height is reserved so the dialog does not jump while typing. */
export function SchedulePreview({ schedule }: { schedule: string }) {
  const t = useT()
  const lang = useLang()
  const { data: settings } = useSettings()
  const tz = settings?.timezone
  const debounced = useDebounced(schedule.trim(), 300)
  const q = useCronPreview(debounced)
  const p = debounced ? q.data : undefined
  return (
    <div className="min-h-[164px] rounded-lg border bg-muted/30 p-3 text-sm" aria-live="polite" data-testid="cron-preview">
      {!debounced ? (
        <p className="text-muted-foreground">{t('crons.previewEmpty')}</p>
      ) : !p ? (
        <div className="grid gap-2">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-3.5 w-64" />
          <Skeleton className="h-3.5 w-60" />
        </div>
      ) : !p.valid ? (
        <p className="flex items-start gap-2 text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{p.error || t('crons.invalidSchedule')}</span>
        </p>
      ) : (
        <div className="grid gap-2">
          <p className="flex items-center gap-2 font-medium first-letter:uppercase">
            <CalendarClock className="size-4 shrink-0 text-muted-foreground" />
            <span>{cap(p.human)}</span>
          </p>
          {p.next.length > 0 ? (
            <div className="grid gap-1">
              <span className="text-xs text-muted-foreground">{t('crons.nextRuns', { tz: tz || 'UTC' })}</span>
              <ol className="grid gap-0.5 text-[13px] tabular-nums">
                {p.next.map((at) => (
                  <li key={at} className="flex flex-wrap gap-x-2">
                    <span>{fmtDate(at, lang, tz, { dateStyle: 'full', timeStyle: 'short' })}</span>
                    <span className="text-muted-foreground">{fmtRelative(at, lang)}</span>
                  </li>
                ))}
              </ol>
            </div>
          ) : (
            <p className="text-[13px] text-muted-foreground">{t('crons.noNextRun')}</p>
          )}
        </div>
      )}
    </div>
  )
}
