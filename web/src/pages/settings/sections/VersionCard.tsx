// Settings -> Updates, first card: the installed version, Check / Update now (with its plan and progress), the
// automatic update switch. Was the first card of Settings -> System before 2.0.0a132.
import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { RefreshCw, Sparkles, Wrench, KeyRound, GitBranch } from 'lucide-react'
import { useWhatsNew } from '@/features/whatsnew/store'
import { applyUpdate } from '@/pwa'
import { useCheckVersion, useUpdate, useAutoUpdate, useVersion } from '@/lib/queries'
import { fmtRelative } from '@/lib/format'
import { api } from '@/lib/api'
import type { AuthState, VersionInfo } from '@/lib/types'
import { useLang, useT } from '@/i18n'
import { Badge, Button, ProgressBar, Skeleton, Spinner, Switch, confirm, toast } from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { SettingsCard } from './ui'
import { UpdatePlan, UpdateReportView } from './UpdatePlan'
import { useHarnessTopic } from './harnessTopic'

export function VersionCard() {
  const t = useT()
  const qc = useQueryClient()
  const { data: v, isLoading } = useVersion()
  const update = useUpdate()
  const autoUpdate = useAutoUpdate()
  const check = useCheckVersion()
  const lang = useLang()
  // the topic that handles updates: system/harness (system/update on workspaces installed before 2.0.0a33)
  const updateTopic = useHarnessTopic()
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
