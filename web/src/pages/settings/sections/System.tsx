import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { Play, RefreshCw, RotateCw, Sparkles, Square, Wrench, KeyRound, GitBranch } from 'lucide-react'
import { useWhatsNew } from '@/features/whatsnew/store'
import { applyUpdate } from '@/pwa'
import { useCheckVersion, useHealth, useLogs, useServiceAction, useServices, useUpdate, useAutoUpdate, useVersion, useWorkspace } from '@/lib/queries'
import { fmtRelative } from '@/lib/format'
import { api } from '@/lib/api'
import type { AuthState, ServiceAction, VersionInfo } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Badge, Button, ProgressBar, Select, Sensitive, Skeleton, Spinner, StatusDot, Switch, confirm, toast } from '@/components/ui'
import { HealthSummary } from '@/components/shell/HealthIndicator'
import { Callout, SettingRow } from '@/features/common'
import { SettingsCard, SectionStack } from './ui'
import { UpdatePlan, UpdateReportView } from './UpdatePlan'

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
          <Select value={unit} onValueChange={setUnit} options={units} className="h-8 w-40" aria-label={t('system.unit')} />
          <Select value={String(lines)} onValueChange={(v) => setLines(Number(v))} options={[100, 200, 500, 1000].map((n) => ({ value: String(n), label: t('system.lines', { n }) }))} className="h-8 w-28" aria-label={t('system.linesLabel')} />
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

function VersionCard() {
  const t = useT()
  const qc = useQueryClient()
  const { data: v, isLoading } = useVersion()
  const update = useUpdate()
  const autoUpdate = useAutoUpdate()
  const check = useCheckVersion()
  const lang = useLang()
  // the topic that handles updates: system/harness (system/update on workspaces installed before 2.0.0a33)
  const { data: ws } = useWorkspace()
  const hasOld = ws?.projects.some((p) => p.topics.some((tp) => tp.path === 'projects/system/topics/update'))
  const hasNew = ws?.projects.some((p) => p.topics.some((tp) => tp.path === 'projects/system/topics/harness'))
  const updateTopic = hasOld && !hasNew ? 'projects/system/topics/update' : 'projects/system/topics/harness'
  const [phase, setPhase] = React.useState<'idle' | 'running' | 'restarting' | 'done' | 'blocked'>('idle')
  const start = React.useRef(0)
  const [elapsed, setElapsed] = React.useState(0)

  React.useEffect(() => {
    if (phase !== 'running' && phase !== 'restarting') return
    const startVersion = v?.commit
    let wentDown = false
    const id = setInterval(async () => {
      setElapsed(Math.round((Date.now() - start.current) / 1000))
      try {
        const st = await api.get<AuthState>('/api/auth/state', undefined, { noAuthRedirect: true })
        if (wentDown || st.version) {
          const nv = await api.get<VersionInfo>('/api/system/version', undefined, { noAuthRedirect: true }).catch(() => null)
          if (nv?.pending && nv.pending.at * 1000 >= start.current - 5000) {
            setPhase('blocked') // customizations conflict / rolled back: the old version keeps running
            qc.invalidateQueries()
          } else if (nv && (nv.commit !== startVersion || wentDown)) {
            setPhase('done')
            qc.invalidateQueries()
            applyUpdate() // load the new version straight away (the success message stays if it cannot)
          }
        }
      } catch {
        wentDown = true
        setPhase('restarting')
      }
    }, 3000)
    return () => clearInterval(id)
  }, [phase, v?.commit, qc])

  if (isLoading || !v) return <Skeleton className="h-36 rounded-xl" />
  const upToDate = v.behind === 0
  return (
    <SettingsCard
      title={t('system.version')}
      actions={
        <Button variant="outline" size="sm" onClick={() => useWhatsNew.getState().show(null)}>
          <Sparkles /> {t('whatsnew.title')}
        </Button>
      }
    >
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-2xl font-semibold tracking-tight tabular-nums">v{v.version}</span>
          <code className="rounded bg-muted px-1.5 font-mono text-xs">{v.commit?.slice(0, 7)}</code>
          {v.behind == null ? (
            <Badge variant="muted">{t('system.unknownLatest')}</Badge>
          ) : upToDate ? (
            <Badge variant="success">{t('system.upToDate')}</Badge>
          ) : (
            <Badge variant="warning">{t('system.behind', { n: v.behind })}</Badge>
          )}
          <Button
            variant="ghost"
            size="sm"
            loading={check.isPending || !!v.checking}
            onClick={() => check.mutate(undefined, { onError: () => toast.error(t('system.checkFailed')) })}
            aria-label={t('system.check')}
          >
            <RefreshCw /> {t('system.check')}
          </Button>
          {v.checked_at ? (
            <span className="text-xs text-muted-foreground">{t('system.checkedAt', { when: fmtRelative(v.checked_at, lang) })}</span>
          ) : null}
        </div>
        {v.behind == null && v.checked_at && !v.checking && !check.isPending ? (
          <p className="text-[13px] text-muted-foreground">{t('system.unknownLatestDesc')}</p>
        ) : null}
        {v.license?.enabled && (
          <p className="text-[13px] text-muted-foreground">
            <KeyRound className="mr-1.5 inline size-3.5 align-[-2px]" />
            {t('system.license', { key: v.license.key_hint, kind: t(v.license.kind === 'beta' ? 'system.licenseKind.beta' : v.license.kind === 'gift' ? 'system.licenseKind.gift' : v.license.kind === 'enterprise' ? 'system.licenseKind.enterprise' : 'system.licenseKind.paid'), email: v.license.email || '' })}
            {' · '}
            {v.license.updates_until
              ? t(v.license.updates_until * 1000 < Date.now() ? 'system.licenseUpdatesEnded' : 'system.licenseUpdatesUntil', { date: new Date(v.license.updates_until * 1000).toLocaleDateString(lang) })
              : t('system.licenseUpdatesForever')}
            {v.license.message ? <span className="block">{v.license.message}</span> : null}
            {v.license.move_error ? <span className="block">{t('system.licenseMoving', { error: v.license.move_error })}</span> : null}
          </p>
        )}
        {!v.license?.enabled && !!v.license?.moved_to_git && (
          <p className="text-[13px] text-muted-foreground">
            <GitBranch className="mr-1.5 inline size-3.5 align-[-2px]" />
            {t('system.movedToGit', { key: v.license.key_hint, date: new Date(v.license.moved_to_git * 1000).toLocaleDateString(lang) })}
          </p>
        )}
        {!!v.custom?.count && (
          <p className="text-[13px] text-muted-foreground" title={v.custom.titles.join('\n')}>
            <Wrench className="mr-1.5 inline size-3.5 align-[-2px]" />
            {t('system.customs', { count: v.custom.count })}
          </p>
        )}
        {(v.pending || v.custom?.rebase) && phase !== 'running' && phase !== 'restarting' && (
          <Callout
            tone="warning"
            title={v.pending?.reason === 'conflict' || v.custom?.rebase ? t('system.pendingConflict', { version: v.pending?.target_version || '' }) : t('system.pendingRolledBack', { version: v.pending?.target_version || '' })}
            action={
              <Button size="sm" variant="outline" asChild>
                <Link to={`/sessions?path=${encodeURIComponent(updateTopic)}&new=1`}>{t('system.askClaude')}</Link>
              </Button>
            }
          >
            {v.pending?.reason === 'conflict' || v.custom?.rebase ? t('system.pendingConflictDesc') : t('system.pendingRolledBackDesc')}
          </Callout>
        )}
        {phase === 'idle' && <UpdateReportView v={v} />}
        {phase === 'idle' && !upToDate && v.behind != null && !v.pending && !v.custom?.rebase && (
          <UpdatePlan
            v={v}
            updating={update.isPending}
            onUpdate={async () => {
              const ok = await confirm({ title: t('system.updateTitle'), description: t('system.updateDesc'), confirmText: t('system.update') })
              if (!ok) return
              update.mutate(undefined, {
                onSuccess: () => {
                  start.current = Date.now()
                  setPhase('running')
                },
              })
            }}
          />
        )}
        {(phase === 'running' || phase === 'restarting') && (
          <div className="grid gap-2" aria-live="polite">
            <div className="flex items-center gap-2 text-sm">
              <Spinner /> {phase === 'running' ? t('system.updating') : t('system.restarting')} <span className="text-muted-foreground tabular-nums">{elapsed}s</span>
            </div>
            <ProgressBar value={phase === 'running' ? 40 : 80} />
          </div>
        )}
        {phase === 'done' && (
          <Callout
            tone="success"
            title={t('system.updated')}
            action={
              <Button size="sm" onClick={() => window.location.reload()}>
                {t('error.reload')}
              </Button>
            }
          >
            {t('system.updatedDesc')}
          </Callout>
        )}
        <SettingRow label={t('system.autoUpdate')} description={t('system.autoUpdateHint')} htmlFor="mx-auto-update" className="py-4 first:pt-4 last:pb-4">
          <Switch id="mx-auto-update" checked={v.auto_update?.enabled ?? false} onCheckedChange={(on) => autoUpdate.mutate(on)} />
        </SettingRow>
      </div>
    </SettingsCard>
  )
}

export function SystemSection() {
  return (
    <SectionStack>
      <VersionCard />
      <HealthCard />
      <ServicesCard />
      <LogsCard />
    </SectionStack>
  )
}
