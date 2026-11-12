// Tab "Reports": the digests and weekly / monthly reviews, newest first; one is read on the right (under the list on a phone).
import * as React from 'react'
import { FileText } from 'lucide-react'
import { useT } from '@/i18n'
import { errorMessage } from '@/lib/api'
import { useBuildReport, useEnterpriseReport, useEnterpriseReports } from '@/lib/queries'
import type { Enterprise, EnterpriseReport } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button, EmptyState, Select, Skeleton, toast } from '@/components/ui'
import { Markdown } from '@/components/ui/markdown'

const KINDS: EnterpriseReport['kind'][] = ['daily', 'weekly', 'monthly']

export function Reports({ enterprise: e }: { enterprise: Enterprise }) {
  const t = useT()
  const { data, isLoading, error, refetch } = useEnterpriseReports(e.id)
  const build = useBuildReport()
  const [kind, setKind] = React.useState<EnterpriseReport['kind']>('daily')
  const [picked, setPicked] = React.useState<string | null>(null)
  const list = React.useMemo(() => [...(data || [])].sort((a, b) => (a.date === b.date ? b.name.localeCompare(a.name) : b.date.localeCompare(a.date))), [data])
  const name = picked && list.some((r) => r.name === picked) ? picked : list[0]?.name || null
  const kindLabel = (k: EnterpriseReport['kind']) => t(k === 'daily' ? 'ent.reports.daily' : k === 'weekly' ? 'ent.reports.weekly' : 'ent.reports.monthly')
  const make = () =>
    build.mutate(
      { id: e.id, kind },
      {
        onSuccess: (r) => {
          toast[r.built ? 'success' : 'info'](t(r.built ? 'ent.reports.built' : 'ent.reports.nothing'))
          if (r.report) setPicked(r.report.name)
        },
        onError: (err) => toast.error(errorMessage(err)),
      },
    )
  return (
    <div className="grid gap-4" data-testid="enterprise-reports">
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-40">
          <Select value={kind} onValueChange={(v) => setKind(v as EnterpriseReport['kind'])} options={KINDS.map((k) => ({ value: k, label: kindLabel(k) }))} aria-label={t('ent.reports.kind')} />
        </div>
        <Button variant="outline" onClick={make} loading={build.isPending} data-testid="report-build">
          <FileText /> {t('ent.reports.buildNow')}
        </Button>
      </div>
      {isLoading ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : error ? (
        <EmptyState
          tone="error"
          icon={FileText}
          title={t('ent.reports.loadError')}
          description={errorMessage(error)}
          action={
            <Button variant="outline" onClick={() => void refetch()}>
              {t('common.retry')}
            </Button>
          }
        />
      ) : list.length === 0 ? (
        <EmptyState icon={FileText} title={t('ent.reports.empty')} description={t('ent.reports.emptyDesc')} />
      ) : (
        <div className="grid items-start gap-4 md:grid-cols-[16rem_minmax(0,1fr)]">
          <ul className="grid gap-1 rounded-xl border bg-card p-1.5 max-md:max-h-56 max-md:overflow-y-auto" data-testid="report-list">
            {list.map((r) => (
              <li key={r.name}>
                <button
                  type="button"
                  onClick={() => setPicked(r.name)}
                  aria-current={r.name === name || undefined}
                  className={cn('flex min-h-9 w-full items-center justify-between gap-2 rounded-md px-2.5 text-left text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring max-md:min-h-11', r.name === name && 'bg-accent font-medium')}
                >
                  <span className="tabular-nums">{r.date}</span>
                  <span className="text-xs text-muted-foreground">{kindLabel(r.kind)}</span>
                </button>
              </li>
            ))}
          </ul>
          <ReportView id={e.id} name={name} />
        </div>
      )}
    </div>
  )
}

function ReportView({ id, name }: { id: string; name: string | null }) {
  const t = useT()
  const { data, isLoading, error } = useEnterpriseReport(id, name)
  return (
    <article className="min-w-0 rounded-xl border bg-card p-[var(--pad-card)] text-sm" data-testid="report-view">
      {isLoading ? <Skeleton className="h-40" /> : error || !data ? <p className="text-[13px] text-destructive">{errorMessage(error) || t('ent.reports.loadError')}</p> : <Markdown>{data.text}</Markdown>}
    </article>
  )
}
