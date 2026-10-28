import * as React from 'react'
import { History, Plus, RotateCcw, Trash2, X } from 'lucide-react'
import { useBackup, useBackupForget, useBackupHistory, useBackupRestore, useBackupSettings, useCronPreview } from '@/lib/queries'
import { fmtDate, fmtRelative } from '@/lib/format'
import { useLang, useT } from '@/i18n'
import { useSettings } from '@/lib/queries'
import { Badge, Button, EmptyState, FormField, Input, Sensitive, Skeleton, StatusDot, confirm, toast } from '@/components/ui'
import { BackupSetup, BackupWhy } from '@/features/backup/BackupSetup'
import { SettingsCard, SectionStack } from './ui'

function useDebounced<T>(v: T, ms = 350) {
  const [d, setD] = React.useState(v)
  React.useEffect(() => {
    const id = setTimeout(() => setD(v), ms)
    return () => clearTimeout(id)
  }, [v, ms])
  return d
}

function ScheduleAndInclude() {
  const t = useT()
  const { data: b } = useBackup()
  const save = useBackupSettings()
  const [schedule, setSchedule] = React.useState<string | null>(null)
  const [include, setInclude] = React.useState<string[] | null>(null)
  const [draft, setDraft] = React.useState('')
  React.useEffect(() => {
    if (b && schedule === null) setSchedule(b.schedule)
    if (b && include === null) setInclude(b.include)
  }, [b, schedule, include])
  const ds = useDebounced(schedule || '')
  const preview = useCronPreview(ds)
  if (!b || schedule === null || include === null) return <Skeleton className="h-60" />
  const dirty = schedule !== b.schedule || JSON.stringify(include) !== JSON.stringify(b.include)
  const add = () => {
    const g = draft.trim()
    if (g && !include.includes(g)) setInclude([...include, g])
    setDraft('')
  }
  return (
    <form
      className="grid gap-6"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate({ schedule, include }, { onSuccess: () => toast.success(t('common.saved')) })
      }}
    >
      <FormField
        label={t('backup.schedule')}
        error={preview.data && !preview.data.valid ? preview.data.error || t('backup.scheduleInvalid') : undefined}
        hint={preview.data?.valid ? preview.data.human : t('backup.scheduleHint')}
      >
        <Input value={schedule} onChange={(e) => setSchedule(e.target.value)} className="max-w-xs font-mono" spellCheck={false} />
      </FormField>
      <div className="grid gap-3">
        <div className="grid gap-1">
          <span className="text-sm font-medium">{t('backup.include')}</span>
          <span className="text-[13px] text-muted-foreground">{t('backup.includeHint')}</span>
        </div>
        <ul className="flex flex-wrap gap-2">
          {(b.always || []).map((g) => (
            <li key={`a:${g}`}>
              <Badge variant="muted" className="h-7 px-2.5 font-mono text-xs" title={t('backup.always')}>
                {g}
              </Badge>
            </li>
          ))}
          {include.map((g) => (
            <li key={g}>
              <Badge variant="outline" className="h-7 gap-1.5 pr-1 pl-2.5 font-mono text-xs">
                {g}
                <button type="button" onClick={() => setInclude(include.filter((x) => x !== g))} aria-label={`${t('common.remove')} ${g}`} className="relative rounded p-0.5 before:absolute before:-inset-2.5 before:content-[''] hover:bg-accent pointer-coarse:before:-inset-3">
                  <X className="size-3" />
                </button>
              </Badge>
            </li>
          ))}
        </ul>
        <div className="flex max-w-md gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="projects/*/notes/**/*.md"
            className="font-mono"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                add()
              }
            }}
            aria-label={t('backup.addGlob')}
          />
          <Button variant="outline" onClick={add} disabled={!draft.trim()}>
            <Plus /> {t('common.add')}
          </Button>
        </div>
      </div>
      <div>
        <Button type="submit" disabled={!dirty || (preview.data && !preview.data.valid)} loading={save.isPending}>
          {t('common.save')}
        </Button>
      </div>
    </form>
  )
}

function HistoryList() {
  const t = useT()
  const lang = useLang()
  const { data: settings } = useSettings()
  const { data, isLoading } = useBackupHistory()
  const restore = useBackupRestore()
  if (isLoading) return <Skeleton className="h-48" />
  if (!data?.length) return <EmptyState compact icon={History} title={t('backup.noHistory')} description={t('backup.noHistoryDesc')} />
  return (
    <ul className="divide-y rounded-lg border">
      {data.slice(0, 30).map((r, i) => (
        <li key={`${r.at}-${i}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm">
          <StatusDot tone={r.ok ? 'ok' : 'error'} label={r.ok ? t('common.ok') : t('common.failed')} />
          <span className="font-medium tabular-nums" title={fmtDate(r.at, lang, settings?.timezone)}>
            {fmtRelative(r.at, lang)}
          </span>
          {r.ok ? (
            <span className="text-muted-foreground">
              {t('backup.filesCount', { count: r.files })}
              {r.changed != null && ` · ${t('backup.changedCount', { count: r.changed })}`}
            </span>
          ) : (
            <span className="min-w-0 flex-1 truncate text-destructive">{r.error || r.code}</span>
          )}
          <span className="flex-1" />
          {r.commit && (
            <code className="rounded bg-muted px-1.5 font-mono text-xs">
              <Sensitive length={7}>{r.commit.slice(0, 7)}</Sensitive>
            </code>
          )}
          {r.ok && r.commit && (
            <Button
              variant="ghost"
              size="sm"
              disabled={restore.isPending}
              onClick={async () => {
                const ok = await confirm({
                  title: t('backup.restoreTitle'),
                  description: t('backup.restoreDesc'),
                  destructive: true,
                  confirmText: t('backup.restore'),
                  typeToConfirm: 'restore',
                })
                if (ok) restore.mutate(r.commit!, { onSuccess: (res) => toast.success(t('backup.restored', { count: res.files ?? res.restored?.length ?? 0 })) })
              }}
            >
              <RotateCcw /> {t('backup.restore')}
            </Button>
          )}
        </li>
      ))}
    </ul>
  )
}

export function BackupSection() {
  const t = useT()
  const { data: b } = useBackup()
  const forget = useBackupForget()
  return (
    <SectionStack>
      {!b?.configured && <BackupWhy />}
      <SettingsCard title={t('backup.repository')} description={t('backup.repositoryDesc')}>
        <BackupSetup />
      </SettingsCard>
      {b?.configured && (
        <>
          <SettingsCard title={t('backup.settings')}>
            <ScheduleAndInclude />
          </SettingsCard>
          <SettingsCard title={t('backup.history')} description={t('backup.historyDesc')}>
            <HistoryList />
          </SettingsCard>
          <SettingsCard danger title={t('backup.forget')} description={t('backup.forgetDesc')}>
            <Button
              variant="destructive"
              loading={forget.isPending}
              onClick={async () => {
                if (await confirm({ title: t('backup.forgetConfirm'), description: t('backup.forgetDesc'), destructive: true, confirmText: t('backup.forget') })) forget.mutate()
              }}
            >
              <Trash2 /> {t('backup.forget')}
            </Button>
          </SettingsCard>
        </>
      )}
    </SectionStack>
  )
}
