import * as React from 'react'
import { Play, RefreshCw, RotateCw, Square } from 'lucide-react'
import { useHealth, useHealthHistory, useLogs, useServiceAction, useServices, useSettings, useSaveSettings } from '@/lib/queries'
import { fmtRelative } from '@/lib/format'
import type { HealthPoint, ServiceAction } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Badge, Button, FormField, Input, Segmented, Select, Sensitive, Skeleton, Spinner, StatusDot, confirm, toast } from '@/components/ui'
import { HealthSummary } from '@/components/shell/HealthIndicator'
import { SettingsCard, SectionStack } from './ui'

function HealthCard() {
  const t = useT()
  const { data: h } = useHealth()
  return (
    <SettingsCard title={t('system.health')} description={t('system.healthDesc')}>
      <div className="grid gap-6 md:grid-cols-[1fr_1fr]">
        <HealthSummary />
        {h ? (
          <dl className="grid content-start gap-3 text-sm">
            <Row label={t('system.claudeAuth')} value={h.claude_auth ? t('common.ok') : t('system.notConnected')} tone={h.claude_auth ? 'ok' : 'error'} />
            <Row label={t('system.backupAge')} value={h.backup_age_h == null ? t('system.never') : t('system.hoursAgo', { n: Math.round(h.backup_age_h) })} tone={h.backup_age_h == null || h.backup_age_h > 48 ? 'warn' : 'ok'} />
            <Row label={t('system.failedLogins')} value={<Sensitive length={2}>{h.failed_logins_1h}</Sensitive>} tone={h.failed_logins_1h >= 8 ? 'warn' : 'ok'} />
            <Row label={t('system.load')} value={<Sensitive length={8}>{h.load.map((l) => l.toFixed(2)).join(' · ')}</Sensitive>} />
          </dl>
        ) : (
          <Skeleton className="h-32" />
        )}
      </div>
    </SettingsCard>
  )
}

function Row({ label, value, tone }: { label: string; value: React.ReactNode; tone?: 'ok' | 'warn' | 'error' }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b pb-3 last:border-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="flex items-center gap-2 font-medium">
        {tone && <StatusDot tone={tone} />}
        {value}
      </dd>
    </div>
  )
}

const SELF = 'claude-maxxing'

function ServicesCard() {
  const t = useT()
  const lang = useLang()
  const { data, isLoading } = useServices()
  const action = useServiceAction()
  const run = async (name: string, label: string, a: ServiceAction) => {
    if (a !== 'start') {
      const self = name === SELF
      const ok = await confirm({
        title: t(a === 'stop' ? 'system.stopTitle' : 'system.restartTitle', { name: label }),
        description: self ? t('system.selfRestart') : t('system.serviceConfirm'),
        destructive: a === 'stop',
        confirmText: t(a === 'stop' ? 'system.stop' : 'system.restart'),
      })
      if (!ok) return
    }
    action.mutate({ name, action: a }, { onSuccess: () => toast.success(t('system.actionDone', { name: label })) })
  }
  return (
    <SettingsCard title={t('system.services')} description={t('system.servicesDesc')} className="[&>div:last-child]:p-0 [&>div:last-child]:pt-4">
      {isLoading || !data ? (
        <div className="grid gap-2 p-4">
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : (
        <ul className="divide-y border-t">
          {data.map((s) => (
            <li key={s.name} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <StatusDot tone={s.active ? 'ok' : s.enabled ? 'error' : 'idle'} pulse={!s.active && s.enabled} />
              <div className="grid min-w-0 flex-1 gap-0.5">
                <span className="text-sm font-medium">{s.label || s.name}</span>
                <span className="font-mono text-xs text-muted-foreground">
                  {s.name} · {s.state || (s.active ? 'active' : 'inactive')}
                  {s.since ? ` · ${fmtRelative(s.since, lang)}` : ''}
                </span>
              </div>
              {!s.enabled && <Badge variant="muted">{t('system.disabled')}</Badge>}
              <div className="flex gap-1">
                {s.active ? (
                  <>
                    <Button variant="outline" size="sm" onClick={() => run(s.name, s.label || s.name, 'restart')} disabled={action.isPending}>
                      <RotateCw /> {t('system.restart')}
                    </Button>
                    {s.name !== SELF && (
                      <Button variant="ghost" size="sm" onClick={() => run(s.name, s.label || s.name, 'stop')} disabled={action.isPending} className="text-destructive hover:text-destructive">
                        <Square /> {t('system.stop')}
                      </Button>
                    )}
                  </>
                ) : (
                  <Button variant="outline" size="sm" onClick={() => run(s.name, s.label || s.name, 'start')} disabled={action.isPending}>
                    <Play /> {t('system.start')}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </SettingsCard>
  )
}

function LogsCard() {
  const t = useT()
  const { data: services } = useServices()
  const [unit, setUnit] = React.useState(SELF)
  const [lines, setLines] = React.useState(200)
  const { data, isFetching, refetch, isLoading } = useLogs(unit, lines)
  const box = React.useRef<HTMLPreElement>(null)
  React.useLayoutEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight
  }, [data])
  const units = services?.map((s) => ({ value: s.name, label: s.label || s.name })) || [{ value: SELF, label: SELF }]
  return (
    <SettingsCard
      title={t('system.logs')}
      actions={
        <div className="flex flex-wrap gap-2">
          <Select value={unit} onValueChange={setUnit} options={units} className="h-8 w-48" aria-label={t('system.unit')} />
          <Select value={String(lines)} onValueChange={(v) => setLines(Number(v))} options={[100, 200, 500, 1000].map((n) => ({ value: String(n), label: t('system.lines', { n }) }))} className="h-8 w-32" aria-label={t('system.linesLabel')} />
          <Button variant="outline" size="icon-sm" onClick={() => refetch()} aria-label={t('common.refresh')}>
            {isFetching ? <Spinner /> : <RefreshCw />}
          </Button>
        </div>
      }
    >
      <Sensitive block placeholder={<div className="h-80 rounded-lg bg-muted/60" />}>
        <pre ref={box} className={cn('h-80 overflow-auto rounded-lg border bg-muted/30 p-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap break-all', isLoading && 'animate-shimmer')}>
          {data?.lines.length ? data.lines.join('\n') : isLoading ? '' : t('system.noLogs')}
        </pre>
      </Sensitive>
    </SettingsCard>
  )
}

/** The address of this Harness and the root of the file viewer (was in Settings -> General before 2.0.0a132). */
function AddressCard() {
  const t = useT()
  const { data: s } = useSettings()
  const save = useSaveSettings()
  const [server, setServer] = React.useState<{ public_url: string; files_root: string } | null>(null)
  React.useEffect(() => {
    if (s && !server) setServer({ public_url: s.public_url || '', files_root: s.files_root || '' })
  }, [s, server])
  return (
    <SettingsCard title={t('system.address')} description={t('settings.serverDesc')}>
      {!s || !server ? (
        <Skeleton className="h-44" />
      ) : (
        <form
          className="grid max-w-lg gap-5"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate({ public_url: server.public_url.trim(), files_root: server.files_root.trim() }, { onSuccess: () => toast.success(t('common.saved')) })
          }}
        >
          <FormField label={t('settings.publicUrl')} hint={t('settings.publicUrlHint')}>
            <Input value={server.public_url} onChange={(e) => setServer({ ...server, public_url: e.target.value })} placeholder="https://ui.example.com" inputMode="url" />
          </FormField>
          <FormField label={t('settings.filesRoot')} hint={t('settings.filesRootHint')}>
            <Input value={server.files_root} onChange={(e) => setServer({ ...server, files_root: e.target.value })} className="font-mono" spellCheck={false} />
          </FormField>
          <div>
            <Button type="submit" loading={save.isPending} disabled={server.public_url === s.public_url && server.files_root === s.files_root}>
              {t('common.save')}
            </Button>
          </div>
        </form>
      )}
    </SettingsCard>
  )
}

type HistoryKey = 'cpu' | 'mem' | 'disk'

/** One line chart of a percentage (0-100 %), gaps kept where the server was off; the summary is also its label. */
function UsageChart({ points, k, name, range, step }: { points: HealthPoint[]; k: HistoryKey; name: string; range: string; step: number }) {
  const t = useT()
  const lang = useLang()
  const W = 600
  const H = 72
  const vals = points.map((p) => p[k]).filter((v): v is number => v != null)
  const now = vals.at(-1)
  const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null
  const peaks = k === 'cpu' ? points.map((p) => p.cpu_max ?? p.cpu).filter((v): v is number => v != null) : vals
  const peak = peaks.length ? Math.max(...peaks) : null
  const pct = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? '–' : lang === 'en' ? `${Math.round(v)}%` : `${Math.round(v)} %`)
  const t0 = points[0]?.t ?? 0
  const span = Math.max((points.at(-1)?.t ?? 0) - t0, step)
  // a new segment after a gap longer than two steps (the server or Harness was off); a lone point is a dot
  const segments: string[][] = []
  let cur: string[] = []
  points.forEach((p, i) => {
    const v = p[k]
    if (v == null || (i > 0 && p.t - points[i - 1].t > 2 * step)) {
      if (cur.length) segments.push(cur)
      cur = []
    }
    if (v != null) cur.push(`${(((p.t - t0) / span) * W).toFixed(1)},${(H - 2 - (Math.min(v, 100) / 100) * (H - 4)).toFixed(1)}`)
  })
  if (cur.length) segments.push(cur)
  const label = t('system.history.chart', { name, range, now: pct(now), avg: pct(avg), max: pct(peak) })
  return (
    <div className="grid gap-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
        <span className="font-medium">{name}</span>
        <span className="text-xs text-muted-foreground tabular-nums">{t('system.history.stats', { now: pct(now), avg: pct(avg), max: pct(peak) })}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label} className="h-[72px] w-full overflow-visible">
        {[0, 50, 100].map((g) => (
          <line key={g} x1={0} x2={W} y1={H - 2 - (g / 100) * (H - 4)} y2={H - 2 - (g / 100) * (H - 4)} className="stroke-border" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        ))}
        {segments.map((s, i) =>
          s.length > 1 ? (
            <polyline key={i} points={s.join(' ')} fill="none" className="stroke-primary" strokeWidth={1.75} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          ) : (
            // zero-length line with round caps: a dot that keeps its size whatever the chart's stretch
            <line key={i} x1={s[0].split(',')[0]} y1={s[0].split(',')[1]} x2={s[0].split(',')[0]} y2={s[0].split(',')[1]} className="stroke-primary" strokeWidth={4} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          ),
        )}
      </svg>
    </div>
  )
}

function HistoryCard() {
  const t = useT()
  const lang = useLang()
  const [range, setRange] = React.useState<'24h' | '7d'>('24h')
  const { data, isLoading } = useHealthHistory(range)
  const points = data?.points ?? []
  const time = (s: number) => new Date(s * 1000).toLocaleString(lang, range === '24h' ? { hour: '2-digit', minute: '2-digit' } : { weekday: 'short', hour: '2-digit' })
  return (
    <SettingsCard
      title={t('system.history')}
      description={t('system.historyDesc')}
      actions={
        <Segmented<'24h' | '7d'>
          size="sm"
          value={range}
          onChange={setRange}
          aria-label={t('system.history.range')}
          options={[
            { value: '24h', label: t('system.history.24h') },
            { value: '7d', label: t('system.history.7d') },
          ]}
        />
      }
    >
      {isLoading ? (
        <Skeleton className="h-48" />
      ) : points.length < 2 ? (
        <p className="text-sm text-muted-foreground">{t('system.history.empty')}</p>
      ) : (
        <div className="grid gap-5">
          {(['cpu', 'mem', 'disk'] as const).map((k) => (
            <UsageChart key={k} points={points} k={k} step={data!.step} range={t(`system.history.${range}`)}
              name={t(k === 'cpu' ? 'health.cpu' : k === 'mem' ? 'health.memory' : 'health.disk')} />
          ))}
          <div className="flex justify-between text-xs text-muted-foreground tabular-nums">
            <span>{time(points[0].t)}</span>
            <span>{time(points.at(-1)!.t)}</span>
          </div>
        </div>
      )}
    </SettingsCard>
  )
}

export function SystemSection() {
  return (
    <SectionStack>
      <HealthCard />
      <HistoryCard />
      <ServicesCard />
      <AddressCard />
      <LogsCard />
    </SectionStack>
  )
}
