// Tasks page (/tasks?project=<id|all|none|overview>&task=<id>): projects bar + overview, kanban, week, calendar
// and list over <workspace>/tasks.json.
import * as React from 'react'
import { Link, useSearchParams } from 'react-router'
import { CalendarDays, CalendarRange, ChevronDown, FolderKanban, Kanban, List as ListIcon, ListChecks, Plus, RotateCw, Rows3, SearchX } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Page } from '@/components/shell/Page'
import { useLang, useT } from '@/i18n'
import { isApiError } from '@/lib/api'
import { useBulkTasks, useCreateTask, useDeleteTask, usePatchTask, useSettings, useTasks, useWorkspace } from '@/lib/queries'
import type { Task, TaskProject, TaskStatus } from '@/lib/types'
import { useHotkey } from '@/commands/shortcuts'
import { useRegisterCommands } from '@/commands/registry'
import { Button, EmptyState, Segmented, Select, Sensitive, Skeleton, confirm } from '@/components/ui'
import { Callout } from '@/features/common'
import { TaskBoard, statusColumns, type BoardColumn } from '@/features/tasks/Board'
import { TaskList, type GroupBy } from '@/features/tasks/List'
import { TaskSheet } from '@/features/tasks/TaskSheet'
import { BulkBar } from '@/features/tasks/BulkBar'
import { ProjectsDialog } from '@/features/tasks/ProjectsDialog'
import { ProjectNav, type Scope } from '@/features/tasks/ProjectNav'
import { ProjectHeader, TaskOverview } from '@/features/tasks/Overview'
import { TaskCalendar } from '@/features/tasks/Calendar'
import { weekColumns, weekDropDue } from '@/features/tasks/Week'
import { FilterBar, QuickAdd } from '@/features/tasks/Toolbar'
import { ProjectDot } from '@/features/tasks/parts'
import {
  EMPTY_FILTERS,
  activeFilterCount,
  allLabels,
  byOrder,
  matches,
  orderBetween,
  orderProjects,
  parseQuickAdd,
  projectStats,
  statsOf,
  todayISO,
  type QuickParse,
  type SortKey,
  type TaskFilters,
} from '@/features/tasks/model'

type View = 'board' | 'week' | 'calendar' | 'list'
type Prefs = { view: View; groupBy: GroupBy; sort: SortKey; showDone: boolean; lanes: boolean; scope: Scope }
const PREFS_KEY = 'mx-tasks'
const DEFAULT_PREFS: Prefs = { view: 'board', groupBy: 'due', sort: 'due', showDone: false, lanes: false, scope: 'all' }
const VIEWS: View[] = ['board', 'week', 'calendar', 'list']

function usePrefs(): [Prefs, (p: Partial<Prefs>) => void] {
  const [prefs, setPrefs] = React.useState<Prefs>(() => {
    try {
      const p = { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) || '{}') }
      return VIEWS.includes(p.view) ? p : { ...p, view: 'board' }
    } catch {
      return DEFAULT_PREFS
    }
  })
  const update = React.useCallback((p: Partial<Prefs>) => {
    setPrefs((cur) => {
      const next = { ...cur, ...p }
      try {
        localStorage.setItem(PREFS_KEY, JSON.stringify(next))
      } catch {
        /* private mode */
      }
      return next
    })
  }, [])
  return [prefs, update]
}

export default function TasksPage() {
  const t = useT()
  const lang = useLang()
  const [params, setParams] = useSearchParams()
  const openId = params.get('task')
  const q = useTasks()
  const ws = useWorkspace()
  const { data: settings } = useSettings()
  const tz = settings?.timezone
  const [today, setToday] = React.useState(() => todayISO(tz))
  React.useEffect(() => {
    setToday(todayISO(tz))
    const id = setInterval(() => setToday(todayISO(tz)), 60_000)
    return () => clearInterval(id)
  }, [tz])
  const [prefs, setPrefs] = usePrefs()
  const [search, setSearch] = React.useState<Omit<TaskFilters, 'project'>>(EMPTY_FILTERS)
  const [projectsOpen, setProjectsOpen] = React.useState(false)
  const quickRef = React.useRef<HTMLInputElement | null>(null)

  const create = useCreateTask()
  const patch = usePatchTask()
  const del = useDeleteTask()
  const bulk = useBulkTasks()

  const data = q.data
  const corrupt = isApiError(q.error, 'corrupt_file') ? q.error : null
  const tasks = React.useMemo(() => data?.tasks ?? [], [data])
  const wsOrder = React.useMemo(() => ws.data?.projects.map((p) => p.name) ?? [], [ws.data])
  const emojis = React.useMemo(() => new Map((ws.data?.projects ?? []).filter((p) => p.emoji).map((p) => [p.name, p.emoji])), [ws.data])
  const projects = React.useMemo(() => orderProjects(data?.projects ?? [], wsOrder), [data, wsOrder])
  const labels = React.useMemo(() => allLabels(tasks), [tasks])
  const stats = React.useMemo(() => projectStats(tasks, projects, today), [tasks, projects, today])

  // ---- scope: ?project= (id, or the name of a workspace project), else the last one picked
  const rawScope = params.get('project') ?? prefs.scope
  const scope: Scope = React.useMemo(() => {
    if (rawScope === 'overview' || rawScope === 'all' || rawScope === 'none') return rawScope
    if (!data) return rawScope
    const p = projects.find((x) => x.id === rawScope) ?? projects.find((x) => x.workspace === rawScope)
    return p ? p.id : 'all'
  }, [rawScope, projects, data])
  const setScope = React.useCallback(
    (s: Scope) => {
      setPrefs({ scope: s })
      setParams(
        (p) => {
          const n = new URLSearchParams(p)
          n.set('project', s)
          return n
        },
        { replace: true },
      )
    },
    [setParams, setPrefs],
  )
  const project = projects.find((p) => p.id === scope)
  const oneProject = !!project || scope === 'none'
  const filters: TaskFilters = React.useMemo(() => ({ ...search, project: scope === 'overview' ? 'all' : scope }), [search, scope])
  const setFilters = (f: TaskFilters) => {
    const { project: pr, ...rest } = f
    setSearch(rest)
    if (pr !== filters.project) setScope(pr)
  }
  const groupBy: GroupBy = prefs.groupBy === 'topic' && !project ? 'due' : prefs.groupBy === 'project' && oneProject ? 'due' : prefs.groupBy

  const visible = React.useMemo(() => {
    let v = tasks.filter((x) => matches(x, filters, today))
    if (prefs.view === 'list' && !prefs.showDone) v = v.filter((x) => x.status !== 'done')
    return v
  }, [tasks, filters, today, prefs.view, prefs.showDone])

  const openTask = React.useCallback(
    (id: string) =>
      setParams((p) => {
        const n = new URLSearchParams(p)
        n.set('task', id)
        return n
      }),
    [setParams],
  )
  const closeTask = React.useCallback(
    () =>
      setParams(
        (p) => {
          const n = new URLSearchParams(p)
          n.delete('task')
          return n
        },
        { replace: true },
      ),
    [setParams],
  )

  const scopeProjectId = project ? project.id : null
  const addParsed = React.useCallback(
    (p: QuickParse, extra: { status?: TaskStatus; due?: string | null; project_id?: string | null } = {}) =>
      create.mutateAsync({
        title: p.title.trim(),
        status: extra.status ?? 'todo',
        labels: p.labels,
        priority: p.priority ?? 0,
        due: p.due ?? extra.due ?? null,
        project_id: p.project_id ?? (extra.project_id !== undefined ? extra.project_id : scopeProjectId),
      }),
    [create, scopeProjectId],
  )

  const endOf = (status: TaskStatus, done = status === 'done') => {
    const col = tasks.filter((x) => x.status === status).sort(byOrder)
    return done ? orderBetween(undefined, col[0]?.order) : orderBetween(col.at(-1)?.order, undefined)
  }
  const moveStatus = (task: Task, status: TaskStatus) => patch.mutate({ id: task.id, status, order: endOf(status) })
  const toggleDone = (task: Task, done: boolean) => moveStatus(task, done ? 'done' : 'todo')
  const dropStatus = (task: Task, column: string, prev?: Task, next?: Task, extra: { project_id?: string | null } = {}) =>
    patch.mutate({ id: task.id, status: column as TaskStatus, order: orderBetween(prev?.order, next?.order), ...extra })
  const dropWeek = (task: Task, column: string) => {
    const due = weekDropDue(column)
    if (due !== undefined && due !== task.due) patch.mutate({ id: task.id, due })
  }
  const remove = async (task: Task) => {
    const ok = await confirm({ title: t('tasks.deleteTitle'), description: t('tasks.deleteDesc'), destructive: true, confirmText: t('common.delete') })
    if (ok) del.mutate(task.id)
  }

  useHotkey('n', () => quickRef.current?.focus(), { enabled: !openId && !projectsOpen })
  useRegisterCommands(
    'tasks',
    [
      { id: 'tasks.new', title: t('tasks.cmd.new'), group: t('nav.tasks'), icon: Plus, perform: ({ close }) => (close(), setTimeout(() => quickRef.current?.focus(), 50)) },
      { id: 'tasks.projects', title: t('tasks.manageProjects'), group: t('nav.tasks'), icon: FolderKanban, perform: ({ close }) => (close(), setProjectsOpen(true)) },
      { id: 'tasks.overview', title: t('tasks.cmd.overview'), group: t('nav.tasks'), icon: FolderKanban, perform: ({ close }) => (close(), setScope('overview')) },
      ...VIEWS.filter((v) => v !== prefs.view).map((v) => ({
        id: `tasks.view.${v}`,
        title: t(`tasks.cmd.${v}` as 'tasks.cmd.board'),
        group: t('nav.tasks'),
        icon: VIEW_ICON[v],
        perform: ({ close }: { close: () => void }) => (close(), setPrefs({ view: v })),
      })),
    ],
    [t, prefs.view, setScope],
  )

  const viewExtras = (
    <div className="flex flex-wrap items-center gap-2">
      {prefs.view === 'board' && scope === 'all' && (
        <Button variant={prefs.lanes ? 'secondary' : 'ghost'} aria-pressed={prefs.lanes} onClick={() => setPrefs({ lanes: !prefs.lanes })} title={t('tasks.lanesHint')}>
          <Rows3 />
          {t('tasks.lanes')}
        </Button>
      )}
      {prefs.view === 'list' && (
        <>
          <Select
            value={groupBy}
            onValueChange={(v) => setPrefs({ groupBy: v as GroupBy })}
            aria-label={t('tasks.groupBy')}
            className="w-auto min-w-36"
            options={[
              { value: 'due', label: t('tasks.groupBy.due') },
              ...(oneProject ? [] : [{ value: 'project', label: t('tasks.groupBy.project') }]),
              ...(project ? [{ value: 'topic', label: t('tasks.groupBy.topic') }] : []),
            ]}
          />
          <Select
            value={prefs.sort}
            onValueChange={(v) => setPrefs({ sort: v as SortKey })}
            aria-label={t('tasks.sortBy')}
            className="w-auto min-w-36"
            options={(['due', 'priority', 'created', 'updated', 'title'] as SortKey[]).map((k) => ({ value: k, label: t(`tasks.sort.${k}` as 'tasks.sort.due') }))}
          />
          <Button variant={prefs.showDone ? 'secondary' : 'ghost'} aria-pressed={prefs.showDone} onClick={() => setPrefs({ showDone: !prefs.showDone })}>
            {t('tasks.showDone')}
          </Button>
        </>
      )}
    </div>
  )

  const boardCommon = {
    projects,
    today,
    hideProject: oneProject,
    onOpen: openTask,
    onMoveStatus: moveStatus,
    onDelete: remove,
  }
  const filtering = activeFilterCount({ ...filters, project: 'all' }) > 0 || !!filters.q

  const body = () => {
    if (prefs.view === 'board' && scope === 'all' && prefs.lanes)
      return <Lanes tasks={visible} projects={projects} onAdd={(pid, status, text) => addParsed(parseQuickAdd(text, projects, today), { status, project_id: pid })} common={boardCommon} onDropStatus={dropStatus} onBulk={(ids, status) => bulk.mutate({ ids, patch: { status } })} />
    if (prefs.view === 'board')
      return (
        <TaskBoard
          {...boardCommon}
          columns={statusColumns(visible, t, (status, text) => addParsed(parseQuickAdd(text, projects, today), { status }))}
          onDrop={(task, col, prev, next) => dropStatus(task, col, prev, next)}
          onBulkDrop={(ids, status) => bulk.mutate({ ids, patch: { status: status as TaskStatus } })}
        />
      )
    if (prefs.view === 'week')
      return (
        <TaskBoard
          {...boardCommon}
          layout="scroll"
          testId="task-week"
          columns={weekColumns(visible, today, lang, t, (due, text) => addParsed(parseQuickAdd(text, projects, today), { due }))}
          onDrop={dropWeek}
          onBulkDrop={(ids, col) => {
            const due = weekDropDue(col)
            if (due !== undefined) bulk.mutate({ ids, patch: { due } })
          }}
        />
      )
    if (prefs.view === 'calendar')
      return (
        <TaskCalendar
          tasks={visible}
          projects={projects}
          today={today}
          hideProject={oneProject}
          onOpen={openTask}
          onSetDue={(task, due) => patch.mutate({ id: task.id, due })}
          onToggleDone={toggleDone}
          onAdd={(due, text) => addParsed(parseQuickAdd(text, projects, today), { due })}
        />
      )
    return <TaskList tasks={visible} projects={projects} today={today} groupBy={groupBy} sort={prefs.sort} hideProject={oneProject} onOpen={openTask} onToggleDone={toggleDone} />
  }

  const viewSwitch =
    scope !== 'overview' ? (
      <Segmented<View>
        value={prefs.view}
        onChange={(v) => setPrefs({ view: v })}
        aria-label={t('tasks.view')}
        options={VIEWS.map((v) => {
          const Icon = VIEW_ICON[v]
          return { value: v, label: <span className="max-lg:sr-only">{t(`tasks.view.${v}` as 'tasks.view.board')}</span>, icon: <Icon /> }
        })}
      />
    ) : null

  return (
    <Page
      title={t('nav.tasks')}
      description={t('tasks.description')}
      width="full"
      // below 400 px the switch leaves the header, or the title shrinks to "Tâc…"
      actions={viewSwitch && <div className="max-[399px]:hidden">{viewSwitch}</div>}
    >
      <div className="mx-auto grid max-w-[1800px] gap-4 md:grid-cols-[13rem_minmax(0,1fr)] md:gap-6">
        {viewSwitch && <div className="min-[400px]:hidden">{viewSwitch}</div>}
        {data ? <ProjectNav scope={scope} onScope={setScope} projects={projects} stats={stats} emojis={emojis} onManage={() => setProjectsOpen(true)} /> : <div className="max-md:hidden" />}
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-4">
          {corrupt && (
            <Callout
              tone="error"
              title={t('tasks.corrupt.title')}
              action={
                <Button variant="outline" size="sm" onClick={() => q.refetch()} loading={q.isFetching}>
                  <RotateCw />
                  {t('common.retry')}
                </Button>
              }
            >
              <p>{t('tasks.corrupt.desc')}</p>
              <p className="mt-1.5 font-mono text-xs break-words text-foreground/80">{corrupt.message}</p>
              <p className="mt-1.5">
                {t('tasks.corrupt.fix')}{' '}
                <TasksFileLink />
              </p>
            </Callout>
          )}
          {q.isError && !corrupt && (
            <EmptyState
              tone="error"
              icon={ListChecks}
              title={t('tasks.loadError')}
              description={q.error instanceof Error ? q.error.message : undefined}
              action={
                <Button variant="outline" onClick={() => q.refetch()}>
                  {t('common.retry')}
                </Button>
              }
            />
          )}
          {!q.isError || data ? (
            !data ? (
              <BoardSkeleton />
            ) : scope === 'overview' ? (
              <>
                <QuickAdd projects={projects} today={today} inputRef={quickRef} onAdd={(p) => addParsed(p)} />
                {tasks.length === 0 ? <NoTasks onNew={() => quickRef.current?.focus()} /> : <TaskOverview projects={projects} stats={stats} emojis={emojis} today={today} onPick={setScope} />}
              </>
            ) : (
              <>
                {oneProject && <ProjectHeader project={project} emoji={project?.workspace ? emojis.get(project.workspace) : undefined} stats={statsOf(stats, project ? project.id : '')} onManage={() => setProjectsOpen(true)} />}
                <QuickAdd projects={projects} today={today} inputRef={quickRef} onAdd={(p) => addParsed(p)} />
                <FilterBar filters={filters} onChange={setFilters} projects={projects} labels={labels} extra={viewExtras} withProject={false} />
                {tasks.length === 0 ? (
                  <NoTasks onNew={() => quickRef.current?.focus()} />
                ) : visible.length === 0 && prefs.view !== 'calendar' && (prefs.view === 'list' || filtering) ? (
                  <EmptyState
                    compact
                    icon={SearchX}
                    title={!filtering ? t('tasks.allDone') : t('tasks.noMatch')}
                    description={!filtering ? t('tasks.allDoneDesc') : t('tasks.noMatchDesc')}
                    action={
                      filtering ? (
                        <Button variant="outline" onClick={() => setSearch(EMPTY_FILTERS)}>
                          {t('tasks.clearFilters')}
                        </Button>
                      ) : undefined
                    }
                  />
                ) : (
                  body()
                )}
                {tasks.length > 0 && <p className="pb-14 text-center text-xs text-muted-foreground">{t('tasks.footerHint')}</p>}
              </>
            )
          ) : null}
        </div>
      </div>
      {data && <BulkBar tasks={tasks} visible={visible} projects={projects} labels={labels} today={today} />}
      <TaskSheet id={openId} tasks={data?.tasks} projects={projects} loading={q.isPending} onClose={closeTask} onManageProjects={() => setProjectsOpen(true)} />
      <ProjectsDialog open={projectsOpen} onOpenChange={setProjectsOpen} projects={projects} tasks={tasks} />
    </Page>
  )
}

const VIEW_ICON = { board: Kanban, week: CalendarRange, calendar: CalendarDays, list: ListIcon } as const

function NoTasks({ onNew }: { onNew: () => void }) {
  const t = useT()
  return (
    <EmptyState
      icon={ListChecks}
      title={t('tasks.empty.title')}
      description={t('tasks.empty.desc')}
      action={
        <Button onClick={onNew}>
          <Plus />
          {t('tasks.cmd.new')}
        </Button>
      }
    />
  )
}

type BoardCommon = {
  projects: TaskProject[]
  today: string
  hideProject: boolean
  onOpen: (id: string) => void
  onMoveStatus: (task: Task, status: TaskStatus) => void
  onDelete: (task: Task) => void
}

/** Kanban with one lane per project (all tasks): a card moves between statuses inside its lane. */
function Lanes({
  tasks,
  projects,
  common,
  onAdd,
  onDropStatus,
  onBulk,
}: {
  tasks: Task[]
  projects: TaskProject[]
  common: BoardCommon
  onAdd: (projectId: string | null, status: TaskStatus, text: string) => Promise<unknown>
  onDropStatus: (task: Task, column: string, prev?: Task, next?: Task) => void
  onBulk: (ids: string[], status: TaskStatus) => void
}) {
  const t = useT()
  const [closed, setClosed] = React.useState<Set<string>>(() => new Set())
  const known = new Set(projects.map((p) => p.id))
  const lanes: { id: string; project?: TaskProject; tasks: Task[] }[] = projects
    .map((p) => ({ id: p.id, project: p, tasks: tasks.filter((x) => x.project_id === p.id) }))
    .filter((l) => l.tasks.length > 0)
  const rest = tasks.filter((x) => !x.project_id || !known.has(x.project_id))
  if (rest.length) lanes.push({ id: '', tasks: rest })
  return (
    <div className="grid gap-4" data-testid="task-lanes">
      {lanes.map((lane) => {
        const isClosed = closed.has(lane.id)
        const open = lane.tasks.filter((x) => x.status !== 'done').length
        return (
          <section key={lane.id} className="grid gap-2" aria-label={lane.project?.name ?? t('tasks.noProject')}>
            <button
              type="button"
              aria-expanded={!isClosed}
              onClick={() =>
                setClosed((s) => {
                  const n = new Set(s)
                  if (n.has(lane.id)) n.delete(lane.id)
                  else n.add(lane.id)
                  return n
                })
              }
              className="flex h-8 w-fit items-center gap-2 rounded-md px-1.5 text-[13px] font-semibold hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <ChevronDown className={cn('size-4 text-muted-foreground transition-transform', isClosed && '-rotate-90')} />
              {lane.project && <ProjectDot color={lane.project.color} />}
              {lane.project ? <Sensitive length={6}>{lane.project.name}</Sensitive> : t('tasks.noProject')}
              <span className="text-xs font-normal text-muted-foreground tabular-nums">{open}</span>
            </button>
            {!isClosed && (
              <TaskBoard
                {...common}
                hideProject
                testId={`task-lane-${lane.id || 'none'}`}
                columns={statusColumns(lane.tasks, t, (status, text) => onAdd(lane.id || null, status, text)).map((c): BoardColumn => ({ ...c, page: c.id === 'done' ? 3 : 6 }))}
                onDrop={(task, col, prev, next) => onDropStatus(task, col, prev, next)}
                onBulkDrop={(ids, status) => onBulk(ids, status as TaskStatus)}
              />
            )}
          </section>
        )
      })}
    </div>
  )
}

function TasksFileLink() {
  const t = useT()
  const { data } = useWorkspace()
  if (!data) return null
  const path = `${data.root.replace(/\/$/, '')}/tasks.json`
  return (
    <Link to={`/files?path=${encodeURIComponent(path)}`} className="font-medium text-primary underline-offset-4 hover:underline">
      {t('tasks.corrupt.open')}
    </Link>
  )
}

function BoardSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-3" aria-hidden>
      {[3, 2, 2].map((n, i) => (
        <div key={i} className="grid content-start gap-2 rounded-xl border bg-muted/25 p-2 max-md:hidden first:max-md:grid">
          <Skeleton className="m-1 h-5 w-24" />
          {Array.from({ length: n }, (_, j) => (
            <Skeleton key={j} className="h-[68px] rounded-lg" />
          ))}
        </div>
      ))}
    </div>
  )
}
