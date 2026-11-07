// Shared bits of the Crons page: live clock, kind badge, last-run summary, runs history.
import * as React from 'react'
import { Link } from 'react-router'
import { ArrowUpRight, Bot, ChevronRight, History, Terminal } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { fmtDate, fmtDuration, fmtRelative } from '@/lib/format'
import { useCronRuns } from '@/lib/queries'
import type { Cron, CronKind, CronLastRun, CronRun } from '@/lib/types'
import { Badge, Button, CodeBlock, EmptyState, Sensitive, Skeleton, StatusDot } from '@/components/ui'

/** Sentence case for the server's humanised schedules. */
export const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s)

/** Re-render every `ms` (relative times). */
export function useNow(ms = 30_000) {
  const [now, setNow] = React.useState(() => Date.now() / 1000)
  React.useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

/** When a job runs, in words: the server's text for a schedule, the date of a one-time job in the UI language. */
export function useJobWhen() {
  const t = useT()
  const lang = useLang()
  return (job: Cron, tz?: string) =>
    job.once_at && job.once_ts ? t('crons.onceOn', { date: fmtDate(job.once_ts, lang, tz, { dateStyle: 'medium', timeStyle: 'short' }) }) : cap(job.human)
}

/** State badge of a job: done / missed one-time job, else disabled. */
export function StateBadge({ job }: { job: Cron }) {
  const t = useT()
  if (job.once_at && job.done_at) return <Badge variant="muted">{job.missed ? t('crons.missed') : t('crons.done')}</Badge>
  if (!job.enabled) return <Badge variant="muted">{t('crons.disabled')}</Badge>
  return null
}

/** How a run was started, when it is worth saying: a catch-up, a retry, an answer with nothing to report. */
export function RunNotes({ run, className }: { run: Pick<CronRun, 'trigger' | 'attempt' | 'silent'>; className?: string }) {
  const t = useT()
  const notes = [
    run.trigger === 'catch-up' && t('crons.trigger.catchUp'),
    (run.attempt || 1) > 1 && t('crons.trigger.retry', { n: run.attempt || 1 }),
    run.silent && t('crons.silent'),
  ].filter(Boolean) as string[]
  if (!notes.length) return null
  return (
    <span className={cn('inline-flex flex-wrap gap-1', className)}>
      {notes.map((n) => (
        <Badge key={n} variant="muted" className="font-normal">
          {n}
        </Badge>
      ))}
    </span>
  )
}

export function KindBadge({ kind, className }: { kind: CronKind; className?: string }) {
  const t = useT()
  return (
    <Badge variant="muted" className={cn('gap-1', className)}>
      {kind === 'claude' ? <Bot /> : <Terminal />}
      {kind === 'claude' ? t('crons.kind.claudeShort') : t('crons.kind.shell')}
    </Badge>
  )
}

export function LastRun({ run, tz, now }: { run: CronLastRun | null; tz?: string; now: number }) {
  const t = useT()
  const lang = useLang()
  if (!run) return <span className="text-[13px] text-muted-foreground">{t('crons.neverRun')}</span>
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-[13px] max-md:flex-wrap" title={fmtDate(run.at, lang, tz)}>
      <StatusDot tone={run.ok ? 'ok' : 'error'} label={run.ok ? t('crons.ok') : t('crons.failed')} />
      <span className={cn('font-medium', run.ok ? 'text-foreground' : 'text-destructive')}>{run.ok ? t('crons.ok') : t('crons.failedCode', { code: run.code ?? '?' })}</span>
      <span className="truncate text-muted-foreground max-md:whitespace-normal max-md:break-words">
        {fmtRelative(run.at, lang, now)} · {fmtDuration(run.duration_s)}
      </span>
      <RunNotes run={{ trigger: run.trigger || undefined, attempt: run.attempt, silent: run.silent }} />
    </span>
  )
}

/** Run history of one job (or all jobs when cronId is null). */
export function RunsHistory({ cronId, tz, showName, pageSize = 20 }: { cronId: string | null; tz?: string; showName?: boolean; pageSize?: number }) {
  const t = useT()
  const [limit, setLimit] = React.useState(pageSize)
  const q = useCronRuns(cronId, limit)
  if (q.isPending)
    return (
      <div className="grid gap-2" aria-hidden>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-12" />
        ))}
      </div>
    )
  if (q.isError)
    return (
      <EmptyState
        compact
        tone="error"
        icon={History}
        title={t('crons.runsError')}
        action={
          <Button variant="outline" size="sm" onClick={() => q.refetch()}>
            {t('common.retry')}
          </Button>
        }
      />
    )
  const runs = q.data
  if (!runs.length) return <EmptyState compact icon={History} title={t('crons.noRuns')} description={t('crons.noRunsDesc')} />
  return (
    <div className="grid gap-2">
      <ul className="divide-y rounded-lg border" data-testid="cron-runs">
        {runs.map((r, i) => (
          <RunRow key={r.id} run={r} tz={tz} showName={showName} defaultOpen={i === 0} />
        ))}
      </ul>
      {runs.length >= limit && (
        <Button variant="ghost" size="sm" onClick={() => setLimit((n) => n + 30)} loading={q.isFetching}>
          {t('crons.olderRuns')}
        </Button>
      )}
    </div>
  )
}

function RunRow({ run, tz, showName, defaultOpen }: { run: CronRun; tz?: string; showName?: boolean; defaultOpen?: boolean }) {
  const t = useT()
  const lang = useLang()
  const [open, setOpen] = React.useState(!!defaultOpen && !!run.output_tail)
  const hasOut = !!run.output_tail
  return (
    <li className="grid">
      <button
        type="button"
        onClick={() => hasOut && setOpen((o) => !o)}
        aria-expanded={hasOut ? open : undefined}
        className={cn('flex min-h-11 items-center gap-2.5 px-3 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset', hasOut && 'hover:bg-accent/40')}
      >
        <StatusDot tone={run.ok ? 'ok' : 'error'} label={run.ok ? t('crons.ok') : t('crons.failed')} />
        <span className="grid min-w-0 flex-1 gap-0.5">
          <span className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
            <span className={cn('font-medium', !run.ok && 'text-destructive')}>{run.ok ? t('crons.ok') : t('crons.failedCode', { code: run.code })}</span>
            {showName && (
              <span className="truncate">
                <Sensitive length={6}>{run.name}</Sensitive>
              </span>
            )}
            <span className="text-muted-foreground tabular-nums">{fmtDate(run.at, lang, tz)}</span>
            <RunNotes run={run} />
          </span>
          <span className="text-xs text-muted-foreground tabular-nums">
            {fmtRelative(run.at, lang)} · {fmtDuration(run.duration_s)}
            {run.retry_at ? ` · ${t('crons.retryAt', { when: fmtRelative(run.retry_at, lang) })}` : ''}
          </span>
        </span>
        {hasOut && <ChevronRight className={cn('size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')} />}
      </button>
      {(open || run.session_id) && (
        <div className="grid gap-2 px-3 pb-3">
          {open && hasOut && (
            <Sensitive block className="h-16">
              <CodeBlock code={run.output_tail} className="max-h-72 overflow-y-auto [&_pre]:break-words [&_pre]:whitespace-pre-wrap" />
            </Sensitive>
          )}
          {run.session_id && (
            <Link to={`/sessions?session=${encodeURIComponent(run.session_id)}`} className="inline-flex w-fit items-center gap-1 text-[13px] font-medium text-primary underline-offset-4 hover:underline pointer-coarse:-my-2.5 pointer-coarse:min-h-10">
              {t('crons.openSession')}
              <ArrowUpRight className="size-3.5" />
            </Link>
          )}
        </div>
      )}
    </li>
  )
}
