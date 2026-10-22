// Crons page (/crons?job=<id>): managed jobs, run now, history, editor, external crontab lines.
import * as React from 'react'
import { Link, useSearchParams } from 'react-router'
import { ArrowUpRight, CalendarClock, Clock, Copy, History, MoreHorizontal, Pencil, Play, Plus, Trash2 } from 'lucide-react'
import { Page, Section } from '@/components/shell/Page'
import { useLang, useT } from '@/i18n'
import { cn } from '@/lib/utils'
import { fmtDate, fmtDuration, fmtRelative } from '@/lib/format'
import { useCron, useCrons, useDeleteCron, usePatchCronOptimistic, useRunCronNow, useSettings, useWorkspace } from '@/lib/queries'
import type { Cron } from '@/lib/types'
import { useRegisterCommands } from '@/commands/registry'
import {
  Badge,
  Button,
  CodeBlock,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  Sensitive,
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  Skeleton,
  Spinner,
  Switch,
  Tooltip,
  confirm,
  useMask,
} from '@/components/ui'
import { CronEditor, type EditorSeed } from '@/features/crons/CronEditor'
import { KindBadge, LastRun, RunsHistory, cap, useNow } from '@/features/crons/parts'

export default function CronsPage() {
  const t = useT()
  const [params, setParams] = useSearchParams()
  const jobId = params.get('job')
  const q = useCrons()
  const { data: settings } = useSettings()
  const tz = settings?.timezone
  const now = useNow(30_000)
  const [seed, setSeed] = React.useState<EditorSeed | null>(null)
  const toggle = usePatchCronOptimistic()
  const del = useDeleteCron()
  const run = useRunCronNow({ started: t('crons.started'), already: t('crons.alreadyRunning') })

  const openJob = (id: string) =>
    setParams((p) => {
      const n = new URLSearchParams(p)
      n.set('job', id)
      return n
    })
  const closeJob = () =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p)
        n.delete('job')
        return n
      },
      { replace: true },
    )
  const remove = async (job: Cron) => {
    const ok = await confirm({ title: t('crons.deleteTitle'), description: t('crons.deleteDesc'), destructive: true, confirmText: t('common.delete') })
    if (!ok) return
    if (jobId === job.id) closeJob()
    del.mutate(job.id)
  }
  const actions = { edit: (j: Cron) => setSeed({ mode: 'edit', job: j }), duplicate: (j: Cron) => setSeed({ mode: 'duplicate', job: j }), remove, run: (j: Cron) => run.mutate(j.id) }

  useRegisterCommands('crons', [{ id: 'crons.new', title: t('crons.new'), group: t('nav.crons'), icon: Plus, perform: ({ close }) => (close(), setSeed({ mode: 'new' })) }], [t])

  const jobs = q.data?.jobs ?? []
  const external = q.data?.external ?? []
  return (
    <Page
      title={t('nav.crons')}
      description={t('crons.description')}
      actions={
        <Button onClick={() => setSeed({ mode: 'new' })} aria-label={t('crons.new')}>
          <Plus />
          <span className="max-sm:hidden">{t('crons.new')}</span>
        </Button>
      }
    >
      <div className="grid gap-8">
        {q.isError && !q.data ? (
          <EmptyState
            tone="error"
            icon={Clock}
            title={t('crons.loadError')}
            description={q.error.message}
            action={
              <Button variant="outline" onClick={() => q.refetch()}>
                {t('common.retry')}
              </Button>
            }
          />
        ) : !q.data ? (
          <div className="divide-y rounded-xl border" aria-hidden>
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex items-center gap-3 p-4">
                <div className="grid flex-1 gap-2">
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-3.5 w-72 max-w-full" />
                </div>
                <Skeleton className="h-5 w-9 rounded-full" />
              </div>
            ))}
          </div>
        ) : jobs.length === 0 ? (
          <div className="rounded-xl border">
            <EmptyState
              icon={CalendarClock}
              title={t('crons.empty.title')}
              description={t('crons.empty.desc')}
              action={
                <Button onClick={() => setSeed({ mode: 'new' })}>
                  <Plus />
                  {t('crons.new')}
                </Button>
              }
            />
          </div>
        ) : (
          <ul className="divide-y overflow-hidden rounded-xl border bg-card" data-testid="cron-list">
            {jobs.map((j) => (
              <JobRow key={j.id} job={j} tz={tz} now={now} onOpen={() => openJob(j.id)} onToggle={(v) => toggle.mutate({ id: j.id, enabled: v })} actions={actions} />
            ))}
          </ul>
        )}

        {q.data && (
          <Section title={t('crons.historyAll')} description={t('crons.historyAllDesc')}>
            <RunsHistory cronId={null} tz={tz} showName pageSize={8} />
          </Section>
        )}

        {q.data && external.length > 0 && (
          <Section title={t('crons.external')} description={t('crons.externalDesc')}>
            <ul className="divide-y rounded-xl border" data-testid="cron-external">
              {external.map((e, i) => (
                <li key={i} className="grid gap-1.5 px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-medium">{cap(e.human || e.schedule)}</span>
                    <Badge variant="outline" className="font-mono">
                      {e.schedule}
                    </Badge>
                    <Badge variant="muted">{t('crons.readOnly')}</Badge>
                  </div>
                  <code className="block min-w-0 font-mono text-[12.5px] break-all text-muted-foreground">
                    <Sensitive length={14}>{e.command}</Sensitive>
                  </code>
                </li>
              ))}
            </ul>
          </Section>
        )}
      </div>

      <JobSheet id={jobId} jobs={jobs} loading={q.isPending} tz={tz} now={now} onClose={closeJob} actions={actions} />
      <CronEditor
        seed={seed}
        onOpenChange={(o) => !o && setSeed(null)}
        onSaved={(job) => {
          setSeed(null)
          openJob(job.id)
        }}
      />
    </Page>
  )
}

type Actions = { edit: (j: Cron) => void; duplicate: (j: Cron) => void; remove: (j: Cron) => void; run: (j: Cron) => void }

function NextRun({ job, tz, now }: { job: Cron; tz?: string; now: number }) {
  const t = useT()
  const lang = useLang()
  if (!job.enabled) return <span>{t('crons.paused')}</span>
  if (!job.next_run) return <span>{t('crons.noNextRun')}</span>
  return (
    <span title={fmtDate(job.next_run, lang, tz)}>
      {t('crons.next')} {fmtRelative(job.next_run, lang, now)} <span className="max-md:hidden">· {fmtDate(job.next_run, lang, tz, { dateStyle: 'medium', timeStyle: 'short' })}</span>
    </span>
  )
}

function JobMenu({ job, actions }: { job: Cron; actions: Actions }) {
  const t = useT()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={t('common.more')} onClick={(e) => e.stopPropagation()}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
        <DropdownMenuItem onSelect={() => actions.edit(job)}>
          <Pencil />
          {t('common.edit')}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => actions.duplicate(job)}>
          <Copy />
          {t('crons.duplicate')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive onSelect={() => actions.remove(job)}>
          <Trash2 />
          {t('common.delete')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function RunButton({ job, actions, withLabel }: { job: Cron; actions: Actions; withLabel?: boolean }) {
  const t = useT()
  const btn = (
    <Button
      variant={withLabel ? 'secondary' : 'ghost'}
      size={withLabel ? 'default' : 'icon-sm'}
      aria-label={t('crons.runNow')}
      onClick={(e) => {
        e.stopPropagation()
        actions.run(job)
      }}
      disabled={job.running}
    >
      {job.running ? <Spinner className="size-4" /> : <Play />}
      {withLabel && (job.running ? t('crons.running') : t('crons.runNow'))}
    </Button>
  )
  return withLabel ? btn : <Tooltip content={job.running ? t('crons.running') : t('crons.runNow')}>{btn}</Tooltip>
}

function JobRow({ job, tz, now, onOpen, onToggle, actions }: { job: Cron; tz?: string; now: number; onOpen: () => void; onToggle: (v: boolean) => void; actions: Actions }) {
  const t = useT()
  return (
    <li className={cn('flex items-center gap-3 px-4 py-3 transition-colors hover:bg-accent/40', !job.enabled && 'opacity-70')} data-job-id={job.id}>
      <button type="button" onClick={onOpen} className="grid min-w-0 flex-1 gap-1 rounded text-left outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium">
            <Sensitive length={8}>{job.name}</Sensitive>
          </span>
          <KindBadge kind={job.kind} />
          {job.running && (
            <Badge variant="default" className="gap-1.5">
              <Spinner className="size-3" />
              {t('crons.running')}
            </Badge>
          )}
          {!job.enabled && <Badge variant="muted">{t('crons.disabled')}</Badge>}
        </span>
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px] text-muted-foreground">
          <span className="font-medium text-foreground/80">{cap(job.human)}</span>
          <span aria-hidden className="max-sm:hidden">·</span>
          <NextRun job={job} tz={tz} now={now} />
        </span>
        <LastRun run={job.last_run} tz={tz} now={now} />
      </button>
      <div className="flex shrink-0 items-center gap-1">
        <Switch checked={job.enabled} onCheckedChange={onToggle} aria-label={job.enabled ? t('crons.disable') : t('crons.enable')} className="mr-2" />
        <RunButton job={job} actions={actions} />
        <JobMenu job={job} actions={actions} />
      </div>
    </li>
  )
}

function JobSheet({
  id,
  jobs,
  loading,
  tz,
  now,
  onClose,
  actions,
}: {
  id: string | null
  jobs: Cron[]
  loading: boolean
  tz?: string
  now: number
  onClose: () => void
  actions: Actions
}) {
  const t = useT()
  const lang = useLang()
  const mask = useMask()
  const listed = id ? jobs.find((j) => j.id === id) : undefined
  const one = useCron(id && !listed && !loading ? id : null)
  const job = listed || one.data
  const { data: ws } = useWorkspace()
  const topicLabel = React.useMemo(() => {
    if (!job || job.kind !== 'claude') return ''
    if (!job.topic_path) return t('crons.workspaceRoot')
    for (const p of ws?.projects || []) {
      if (p.path === job.topic_path) return p.name
      for (const tp of p.topics) if (tp.path === job.topic_path) return `${p.name} / ${tp.name}`
    }
    return job.topic_path
  }, [job, ws, t])
  return (
    <Sheet open={!!id} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="md:w-[600px]">
        {!job ? (
          loading || one.isPending ? (
            <div className="grid gap-4 p-5">
              <SheetTitle className="sr-only">{t('crons.job')}</SheetTitle>
              <SheetDescription className="sr-only">{t('crons.job')}</SheetDescription>
              <Skeleton className="h-6 w-1/2" />
              <Skeleton className="h-32" />
            </div>
          ) : (
            <>
              <SheetTitle className="sr-only">{t('crons.notFound')}</SheetTitle>
              <SheetDescription className="sr-only">{t('crons.notFound')}</SheetDescription>
              <EmptyState icon={Clock} title={t('crons.notFound')} description={t('crons.notFoundDesc')} />
            </>
          )
        ) : (
          <>
            <SheetHeader className="gap-2 pr-12 max-md:pr-5">
              <div className="flex flex-wrap items-center gap-2">
                <KindBadge kind={job.kind} />
                {job.running && (
                  <Badge variant="default" className="gap-1.5">
                    <Spinner className="size-3" />
                    {t('crons.running')}
                  </Badge>
                )}
                {!job.enabled && <Badge variant="muted">{t('crons.disabled')}</Badge>}
              </div>
              <SheetTitle className="text-lg">
                <Sensitive length={10}>{job.name}</Sensitive>
              </SheetTitle>
              <SheetDescription>
                {cap(job.human)} · <code className="font-mono text-xs">{job.schedule}</code>
              </SheetDescription>
              <div className="flex flex-wrap gap-2 pt-1">
                <RunButton job={job} actions={actions} withLabel />
                <Button variant="outline" onClick={() => actions.edit(job)}>
                  <Pencil />
                  {t('common.edit')}
                </Button>
                <JobMenu job={job} actions={actions} />
              </div>
            </SheetHeader>
            <SheetBody className="grid content-start gap-6">
              <dl className="grid grid-cols-[minmax(96px,auto)_1fr] gap-x-4 gap-y-2.5 text-sm">
                <dt className="text-muted-foreground">{t('crons.nextRun')}</dt>
                <dd className="min-w-0 tabular-nums">
                  <NextRun job={job} tz={tz} now={now} />
                </dd>
                <dt className="text-muted-foreground">{t('crons.lastRun')}</dt>
                <dd className="min-w-0">
                  <LastRun run={job.last_run} tz={tz} now={now} />
                </dd>
                {job.kind === 'claude' && (
                  <>
                    <dt className="text-muted-foreground">{t('crons.field.topic')}</dt>
                    <dd className="min-w-0">
                      <Link to={`/sessions?path=${encodeURIComponent(job.topic_path)}`} className="inline-flex items-center gap-1 font-medium text-primary underline-offset-4 hover:underline">
                        <span className="truncate">{mask(topicLabel, 8)}</span>
                        <ArrowUpRight className="size-3.5 shrink-0" />
                      </Link>
                    </dd>
                    <dt className="text-muted-foreground">{t('crons.field.model')}</dt>
                    <dd>{job.model || t('crons.modelDefault')}</dd>
                    <dt className="text-muted-foreground">{t('crons.field.reuse')}</dt>
                    <dd>{job.reuse_session ? t('crons.reuseOn') : t('crons.reuseOff')}</dd>
                  </>
                )}
                <dt className="text-muted-foreground">{t('crons.field.notify')}</dt>
                <dd>{t(`crons.notify.${job.notify}` as 'crons.notify.never')}</dd>
                <dt className="text-muted-foreground">{t('crons.field.timeout')}</dt>
                <dd className="tabular-nums">{fmtDuration(job.timeout_s)}</dd>
              </dl>
              <div className="grid gap-2">
                <h3 className="text-sm font-medium">{job.kind === 'claude' ? t('crons.field.prompt') : t('crons.field.command')}</h3>
                <Sensitive block className="h-16">
                  {job.kind === 'claude' ? (
                    <div className="rounded-lg border bg-muted/30 px-3 py-2.5 text-sm break-words whitespace-pre-wrap">{job.prompt}</div>
                  ) : (
                    <CodeBlock code={job.command} className="[&_pre]:break-all [&_pre]:whitespace-pre-wrap" />
                  )}
                </Sensitive>
              </div>
              <div className="grid gap-2">
                <h3 className="flex items-center gap-2 text-sm font-medium">
                  <History className="size-4 text-muted-foreground" />
                  {t('crons.history')}
                </h3>
                <RunsHistory cronId={job.id} tz={tz} />
              </div>
              <p className="text-xs text-muted-foreground">
                {t('crons.timesIn', { tz: tz || 'UTC' })} · {fmtDate(now, lang, tz)}
              </p>
            </SheetBody>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
