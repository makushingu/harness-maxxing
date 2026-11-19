import * as React from 'react'
import { Brush, HardDrive, Play, RefreshCw, RotateCw, Sparkles, Square } from 'lucide-react'
import { useNavigate } from 'react-router'
import { useCleanup, useCleanupScan, useHealth, useLogs, useServiceAction, useServices, useSettings, useSaveSettings } from '@/lib/queries'
import { fmtBytes, fmtRelative } from '@/lib/format'
import type { CleanupPartId, ServiceAction } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  ProgressBar, Input, Select, Sensitive, Skeleton, Spinner, StatusDot, Switch, confirm, toast } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { HealthSummary } from '@/components/shell/HealthIndicator'
import { draftUrl } from '@/features/agents/EditWithClaude'
import { SettingsCard, SectionStack } from './ui'
import { useHarnessTopic } from './harnessTopic'

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
              <div className="grid min-w-40 flex-1 grid-cols-1 gap-0.5">
                <span className="truncate text-sm font-medium">{s.label || s.name}</span>
                <span className="truncate font-mono text-xs text-muted-foreground">
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
      <Sensitive block placeholder={<div className="h-80 rounded-lg bg-muted" />}>
        <pre ref={box} className={cn('h-80 overflow-auto rounded-lg border bg-fill-1 p-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap break-all', isLoading && 'animate-shimmer')}>
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

/** CPU priorities (config `cpu_priorities`): when the processor is full, the UI first, then the sessions, then the
 *  jobs and `maxxing heavy` - weights, never caps (server/maxxing/cpu.py). */
function CpuCard() {
  const t = useT()
  const { data: s } = useSettings()
  const save = useSaveSettings()
  return (
    <SettingsCard>
      {!s ? (
        <Skeleton className="h-12" />
      ) : (
        <SettingRow label={t('system.cpuPriorities')} description={t('system.cpuPrioritiesDesc')} htmlFor="sys-cpu">
          <Switch id="sys-cpu" data-testid="cpu-priorities" checked={s.cpu_priorities !== false} onCheckedChange={(v) => save.mutate({ cpu_priorities: v })} />
        </SettingRow>
      )}
    </SettingsCard>
  )
}

/** Disk space: what Harness frees by itself (measured in the dialog, maxxing/cleanup.py), and a session in the
 *  Harness topic where Claude finds, project by project, where the rest comes from (never deletes without an OK). */
function DiskCard() {
  const t = useT()
  const navigate = useNavigate()
  const topic = useHarnessTopic()
  const { data: h } = useHealth()
  const [open, setOpen] = React.useState(false)
  const d = h?.disk
  return (
    <SettingsCard
      title={t('system.disk')}
      description={t('system.diskDesc')}
      actions={
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => setOpen(true)} data-testid="cleanup-open">
            <Brush /> {t('system.cleanup')}
          </Button>
          <Button variant="outline" size="sm" onClick={() => navigate(draftUrl(topic, t('system.cleanupPrompt')))}>
            <Sparkles /> {t('system.cleanupClaude')}
          </Button>
        </div>
      }
    >
      {!d ? (
        <Skeleton className="h-10" />
      ) : (
        <div className="grid gap-2">
          <div className="flex items-center gap-2 text-sm">
            <HardDrive className="size-4 text-muted-foreground" />
            <Sensitive length={12}>{t('system.diskUsed', { used: fmtBytes(d.total - d.free), total: fmtBytes(d.total), free: fmtBytes(d.free) })}</Sensitive>
          </div>
          <ProgressBar value={d.pct} tone={d.pct >= 90 ? 'error' : d.pct >= 80 ? 'warn' : undefined} label={t('system.disk')} />
        </div>
      )}
      <CleanupDialog open={open} onOpenChange={setOpen} />
    </SettingsCard>
  )
}

function CleanupDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const t = useT()
  const { data, isFetching } = useCleanupScan(open)
  const run = useCleanup()
  const [picked, setPicked] = React.useState<Set<CleanupPartId> | null>(null)
  React.useEffect(() => {
    if (!open) setPicked(null)
    else if (data && !picked) setPicked(new Set(data.parts.filter((p) => p.default).map((p) => p.id)))
  }, [open, data, picked])
  const parts = data?.parts.filter((p) => p.bytes > 0) ?? []
  const total = parts.filter((p) => picked?.has(p.id)).reduce((n, p) => n + p.bytes, 0)
  const toggle = (id: CleanupPartId, on: boolean) => {
    const next = new Set(picked ?? [])
    if (on) next.add(id)
    else next.delete(id)
    setPicked(next)
  }
  const free = () =>
    run.mutate([...(picked ?? [])], {
      onSuccess: (r) => {
        const failed = r.parts.filter((p) => p.error).map((p) => t(`system.cleanup.${p.id}`))
        if (failed.length) toast.error(t('system.cleanupFailed', { parts: failed.join(', ') }))
        toast.success(t('system.cleanupDone', { size: fmtBytes(r.freed) }))
        onOpenChange(false)
      },
    })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('system.cleanup')}</DialogTitle>
          <DialogDescription>{t('system.cleanupDesc')}</DialogDescription>
        </DialogHeader>
        {!data || (isFetching && !picked) ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <Spinner /> {t('system.cleanupScanning')}
          </div>
        ) : !parts.length ? (
          <p className="py-6 text-sm text-muted-foreground">{t('system.cleanupNothing')}</p>
        ) : (
          <ul className="grid gap-1">
            {parts.map((p) => (
              <li key={p.id}>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg p-2 hover:bg-fill-1" data-testid={`cleanup-${p.id}`}>
                  <Checkbox className="mt-0.5" checked={!!picked?.has(p.id)} onCheckedChange={(v) => toggle(p.id, v === true)} />
                  <span className="grid min-w-0 flex-1 gap-0.5">
                    <span className="text-sm font-medium">{t(`system.cleanup.${p.id}`)}</span>
                    <span className="text-xs text-muted-foreground">{t(`system.cleanup.${p.id}Desc`)}</span>
                  </span>
                  <span className="shrink-0 font-mono text-xs tabular-nums">{fmtBytes(p.bytes)}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={free} loading={run.isPending} disabled={!total} data-testid="cleanup-run">
            {t('system.cleanupRun', { size: fmtBytes(total) })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function SystemSection() {
  return (
    <SectionStack>
      <HealthCard />
      <DiskCard />
      <CpuCard />
      <ServicesCard />
      <AddressCard />
      <LogsCard />
    </SectionStack>
  )
}
