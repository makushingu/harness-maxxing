// List view: tasks grouped by due date, project or topic, sortable, with an inline "complete" checkbox.
import * as React from 'react'
import { Check, MessagesSquare } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT, type TKey } from '@/i18n'
import { Checkbox, Sensitive } from '@/components/ui'
import type { Task, TaskProject } from '@/lib/types'
import { dueState, sorter, type SortKey } from './model'
import { DueBadge, LabelChip, PriorityIcon, ProjectChip, ProjectDot } from './parts'
import { StatusPip } from './Board'
import { isSelectClick, useTaskSelection } from './selection'

export type GroupBy = 'due' | 'project' | 'topic'

/** Topic name of a task's topic path ("projects/acme/topics/blog" -> "blog"), '' at project level, null without one. */
export function topicName(path: string | null): string | null {
  if (!path) return null
  const m = /^projects\/[^/]+\/topics\/([^/]+)/.exec(path)
  return m ? m[1] : ''
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
}: {
  tasks: Task[]
  projects: TaskProject[]
  today: string
  groupBy: GroupBy
  sort: SortKey
  hideProject?: boolean
  onOpen: (id: string) => void
  onToggleDone: (task: Task, done: boolean) => void
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
        m.set(k, [...(m.get(k) || []), x])
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
        m.set(k, [...(m.get(k) || []), x])
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
      m.set(k, [...(m.get(k) || []), x])
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

  return (
    <div className="grid gap-5" data-testid="task-list">
      {groups.map((g) => (
        <section key={g.key} className="grid gap-2">
          <h2
            className={cn(
              'flex items-center gap-2 px-1 text-[13px] font-semibold',
              g.tone === 'danger' && 'text-destructive',
              g.tone === 'warn' && 'text-warning',
            )}
          >
            {g.title}
            <span className="text-xs font-normal text-muted-foreground tabular-nums">{g.tasks.length}</span>
            <span className="ml-auto flex">
              <SelectDot
                checked={g.tasks.every((x) => selected.has(x.id))}
                visible={selected.size > 0}
                label={t('tasks.bulk.selectGroup')}
                onToggle={(on) => (on ? useTaskSelection.getState().add(g.tasks.map((x) => x.id)) : useTaskSelection.getState().remove(g.tasks.map((x) => x.id)))}
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
              />
            ))}
          </ul>
        </section>
      ))}
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
}: {
  task: Task
  project?: TaskProject
  showTopic: boolean
  today: string
  selected: boolean
  selecting: boolean
  onOpen: (e: React.MouseEvent) => void
  onToggle: (done: boolean) => void
}) {
  const t = useT()
  const done = task.status === 'done'
  return (
    <li className={cn('group flex min-h-[var(--row-h,40px)] items-start gap-3 px-3 py-2.5 transition-colors hover:bg-accent/40 max-md:py-3', selected && 'bg-primary/5')}>
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
        className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 rounded text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
