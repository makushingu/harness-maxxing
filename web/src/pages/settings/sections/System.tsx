import * as React from 'react'
import { Play, RefreshCw, RotateCw, Square } from 'lucide-react'
import { useHealth, useLogs, useServiceAction, useServices, useSettings, useSaveSettings } from '@/lib/queries'
import { fmtRelative } from '@/lib/format'
import type { ServiceAction } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Badge, Button, FormField, Input, Select, Sensitive, Skeleton, Spinner, StatusDot, confirm, toast } from '@/components/ui'
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

export function SystemSection() {
  return (
    <SectionStack>
      <HealthCard />
      <ServicesCard />
      <AddressCard />
      <LogsCard />
    </SectionStack>
  )
}
