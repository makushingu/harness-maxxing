// List view: tasks grouped by due date, project or topic, sortable, with an inline "complete" checkbox.
import * as React from 'react'
import { Check, MessagesSquare } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT, type TKey } from '@/i18n'
import { Checkbox, Sensitive, useContextMenu } from '@/components/ui'
import type { Task, TaskProject, TaskStatus } from '@/lib/types'
import { dueState, sorter, type SortKey } from './model'
import { DueBadge, LabelChip, PriorityIcon, ProjectChip, ProjectDot } from './parts'
import { StatusPip, TaskMenuItems } from './Board'
import { isSelectClick, useTaskSelection } from './selection'

export type GroupBy = 'due' | 'project' | 'topic'

/** Topic name of a task's topic path ("projects/acme/topics/blog" -> "blog"), '' at project level, null without one. */
export function topicName(path: string | null): string | null {
  if (!path) return null
  const m = /^projects\/[^/]+\/topics\/([^/]+)/.exec(path)
  return m ? m[1] : ''
}

/** Rows rendered per step on a big board (see `shown`). */
const RENDER_STEP = 200

/** Appends to the list of a key (a copy per task made grouping quadratic). */
function push<K>(m: Map<K, Task[]>, k: K, x: Task) {
  const a = m.get(k)
  if (a) a.push(x)
  else m.set(k, [x])
}

type Group = { key: string; title: React.ReactNode; tone?: 'danger' | 'warn'; tasks: Task[] }

const DUE_GROUPS: { key: string; label: TKey; tone?: Group['tone'] }[] = [
  { key: 'overdue', label: 'tasks.group.overdue', tone: 'danger' },
  { key: 'today', label: 'tasks.group.today', tone: 'warn' },
  { key: 'week', label: 'tasks.group.week' },
  { key: 'later', label: 'tasks.group.later' },
  { key: 'none', label: 'tasks.group.noDate' },
  { key: 'done', label: 'tasks.group.done' },
]

export function TaskList({
  tasks,
  projects,
  today,
  groupBy,
  sort,
  hideProject,
  onOpen,
  onToggleDone,
  onMoveStatus,
  onDelete,
}: {
  tasks: Task[]
  projects: TaskProject[]
  today: string
  groupBy: GroupBy
  sort: SortKey
  hideProject?: boolean
  onOpen: (id: string) => void
  onToggleDone: (task: Task, done: boolean) => void
  /** Right click on a row: the menu of a board card (Move to, Delete). */
  onMoveStatus?: (task: Task, status: TaskStatus) => void
  onDelete?: (task: Task) => void
}) {
  const t = useT()
  const projById = React.useMemo(() => new Map(projects.map((p) => [p.id, p])), [projects])
  const selected = useTaskSelection((s) => s.ids)
  const groups = React.useMemo<Group[]>(() => {
    const cmp = sorter(sort === 'order' && groupBy !== 'due' ? 'due' : sort)
    if (groupBy === 'due') {
      const m = new Map<string, Task[]>()
      for (const x of tasks) {
        const k = x.status === 'done' ? 'done' : dueState(x, today)
        push(m, k, x)
      }
      return DUE_GROUPS.filter((g) => m.has(g.key)).map((g) => ({
        key: g.key,
        title: t(g.label),
        tone: g.tone,
        tasks: m.get(g.key)!.sort(g.key === 'done' ? (a, b) => (b.done_at || 0) - (a.done_at || 0) : cmp),
      }))
    }
    if (groupBy === 'topic') {
      const m = new Map<string, Task[]>()
      for (const x of tasks) {
        const name = topicName(x.topic_path)
        const k = name === null ? '\u0000none' : name === '' ? '\u0000project' : name
        push(m, k, x)
      }
      const keys = [...m.keys()].sort((a, b) => Number(a.startsWith('\u0000')) - Number(b.startsWith('\u0000')) || (a === '\u0000none' ? 1 : 0) - (b === '\u0000none' ? 1 : 0) || a.localeCompare(b))
      const out = keys.map<Group>((k) => ({
        key: k,
        title:
          k === '\u0000none' ? (
            t('tasks.group.noTopic')
          ) : k === '\u0000project' ? (
            t('tasks.group.projectLevel')
          ) : (
            <span className="inline-flex items-center gap-2">
              <MessagesSquare className="size-3.5 text-muted-foreground" />
              <Sensitive length={6}>{k}</Sensitive>
            </span>
          ),
        tasks: m.get(k)!.sort(cmp),
      }))
      for (const g of out) g.tasks.sort((a, b) => Number(a.status === 'done') - Number(b.status === 'done'))
      return out
    }
    const m = new Map<string, Task[]>()
    for (const x of tasks) {
      const k = x.project_id && projById.has(x.project_id) ? x.project_id : ''
      push(m, k, x)
    }
    const out: Group[] = projects
      .filter((p) => m.has(p.id))
      .map((p) => ({
        key: p.id,
        title: (
          <span className="inline-flex items-center gap-2">
            <ProjectDot color={p.color} />
            <Sensitive length={6}>{p.name}</Sensitive>
          </span>
        ),
        tasks: m.get(p.id)!.sort(cmp),
      }))
    if (m.has('')) out.push({ key: '', title: t('tasks.noProject'), tasks: m.get('')!.sort(cmp) })
    // open tasks first inside each project group
    for (const g of out) g.tasks.sort((a, b) => Number(a.status === 'done') - Number(b.status === 'done'))
    return out
  }, [tasks, today, groupBy, sort, projects, projById, t])

  // A big board renders progressively, like a big folder in Files: the first rows at once, the next ones as the
  // end of the list comes near.
  const [shown, setShown] = React.useState(RENDER_STEP)
  const [shownFor, setShownFor] = React.useState({ groupBy, sort })
  if (shownFor.groupBy !== groupBy || shownFor.sort !== sort) {
    setShownFor({ groupBy, sort })
    setShown(RENDER_STEP)
  }
  const visible = React.useMemo(() => {
    let left = shown
    const out: Group[] = []
    for (const g of groups) {
      if (left <= 0) break
      out.push(g.tasks.length > left ? { ...g, tasks: g.tasks.slice(0, left) } : g)
      left -= g.tasks.length
    }
    return out
  }, [groups, shown])
  const more = groups.reduce((n, g) => n + g.tasks.length, 0) > shown
  const sentinel = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    const el = sentinel.current
    if (!more || !el) return
    const io = new IntersectionObserver((xs) => xs.some((x) => x.isIntersecting) && setShown((n) => n + RENDER_STEP), { rootMargin: '800px 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [more, shown])

  return (
    <div className="grid gap-5" data-testid="task-list">
      {visible.map((g, i) => (
        <section key={g.key} className="grid gap-2">
          <h2
            className={cn(
              'flex items-center gap-2 px-1 text-[13px] font-semibold',
              g.tone === 'danger' && 'text-destructive',
              g.tone === 'warn' && 'text-warning',
            )}
          >
            {g.title}
            <span className="text-xs font-normal text-muted-foreground tabular-nums">{groups[i].tasks.length}</span>
            <span className="ml-auto flex">
              <SelectDot
                checked={groups[i].tasks.every((x) => selected.has(x.id))}
                visible={selected.size > 0}
                label={t('tasks.bulk.selectGroup')}
                onToggle={(on) => (on ? useTaskSelection.getState().add(groups[i].tasks.map((x) => x.id)) : useTaskSelection.getState().remove(groups[i].tasks.map((x) => x.id)))}
              />
            </span>
          </h2>
          <ul className="group/list divide-y overflow-hidden rounded-xl border bg-card">
            {g.tasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                project={groupBy === 'project' || hideProject ? undefined : task.project_id ? projById.get(task.project_id) : undefined}
                today={today}
                selected={selected.has(task.id)}
                selecting={selected.size > 0}
                showTopic={groupBy !== 'topic'}
                onOpen={(e) => (isSelectClick(e) ? useTaskSelection.getState().toggle(task.id) : onOpen(task.id))}
                onToggle={(d) => onToggleDone(task, d)}
                menu={onMoveStatus && onDelete && (() => <TaskMenuItems task={task} onMoveTo={(st) => onMoveStatus(task, st)} onDelete={() => onDelete(task)} />)}
              />
            ))}
          </ul>
        </section>
      ))}
      {more && <div ref={sentinel} aria-hidden className="h-px" />}
    </div>
  )
}

function SelectDot({ checked, visible, label, onToggle, className }: { checked: boolean; visible: boolean; label: string; onToggle: (on: boolean) => void; className?: string }) {
  // On touch the button is the 40 px hit area and the dot is drawn inside it; negative margins keep the layout.
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      title={label}
      onClick={(e) => {
        e.stopPropagation()
        onToggle(!checked)
      }}
      className={cn('group/dot flex size-5 shrink-0 items-center justify-center rounded-full outline-none pointer-coarse:-m-2.5 pointer-coarse:size-10', className)}
    >
      <span
        className={cn(
          'flex size-5 shrink-0 items-center justify-center rounded-full border transition-opacity group-focus-visible/dot:opacity-100 group-focus-visible/dot:ring-2 group-focus-visible/dot:ring-ring',
          checked ? 'border-primary bg-primary text-primary-foreground' : 'border-muted-foreground/40 bg-card',
          !checked && !visible && 'opacity-0 group-hover:opacity-100 max-md:opacity-100 pointer-coarse:opacity-100',
        )}
      >
        {checked && <Check className="size-3" strokeWidth={3} />}
      </span>
    </button>
  )
}

function TaskRow({
  task,
  project,
  today,
  selected,
  selecting,
  showTopic,
  onOpen,
  onToggle,
  menu,
}: {
  task: Task
  project?: TaskProject
  showTopic: boolean
  today: string
  selected: boolean
  selecting: boolean
  onOpen: (e: React.MouseEvent) => void
  onToggle: (done: boolean) => void
  menu?: () => React.ReactNode
}) {
  const t = useT()
  const done = task.status === 'done'
  const ctx = useContextMenu({ disabled: !menu })
  return (
    <li {...ctx.props} className={cn('group flex min-h-[var(--row-h,40px)] items-start gap-3 px-3 py-2.5 transition-colors hover:bg-muted max-md:py-3', selected && 'bg-primary/5')}>
      {/* on touch, 10 px more so its hit area stops where the done box's begins */}
      <span className="flex h-5 items-center pointer-coarse:mr-2.5">
        <SelectDot checked={selected} visible={selecting} label={task.title} onToggle={() => useTaskSelection.getState().toggle(task.id)} />
      </span>
      <span className="flex h-5 items-center">
        <Checkbox checked={done} onCheckedChange={(v) => onToggle(v === true)} aria-label={done ? t('tasks.markOpen') : t('tasks.markDone')} />
      </span>
      <button
        type="button"
        onClick={(e) => onOpen(e)}
        className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 rounded text-left outline-none pointer-coarse:-my-2.5 pointer-coarse:py-2.5 focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className={cn('min-w-0 flex-1 basis-56 text-sm leading-5 break-words', done && 'text-muted-foreground line-through decoration-muted-foreground/40')}>
          <Sensitive length={10}>{task.title}</Sensitive>
        </span>
        <span className="flex min-w-0 flex-wrap items-center gap-2">
          {task.status === 'doing' && (
            <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
              <StatusPip status="doing" />
              {t('tasks.status.doing')}
            </span>
          )}
          {task.labels.slice(0, 3).map((l) => (
            <LabelChip key={l} label={l} />
          ))}
          {task.topic_path && showTopic && <TopicChip path={task.topic_path} />}
          {project && <ProjectChip project={project} className="max-w-40" />}
          <DueBadge task={task} today={today} />
          {task.priority > 0 && <PriorityIcon p={task.priority} className="size-3.5" />}
        </span>
      </button>
      {ctx.open && menu && ctx.menu(menu())}
    </li>
  )
}

/** Topic of a task: its name (or the project-level icon), linked nowhere: the drawer has the link. */
export function TopicChip({ path }: { path: string }) {
  const t = useT()
  const name = topicName(path)
  return (
    <span className="inline-flex max-w-32 min-w-0 items-center gap-1 text-[11px] text-muted-foreground" title={path} aria-label={t('tasks.hasTopic')}>
      <MessagesSquare className="size-3.5 shrink-0" />
      {name && (
        <span className="truncate">
          <Sensitive length={5}>{name}</Sensitive>
        </span>
      )}
    </span>
  )
}
