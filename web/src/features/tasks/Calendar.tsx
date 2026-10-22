// Calendar view: a month of tasks at their due date. A day shows its first tasks, the picked day lists them all
// below the grid (with an add field). Desktop: drag a task onto another day to move its due date.
import * as React from 'react'
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Button, Checkbox, Input, Sensitive } from '@/components/ui'
import type { Task, TaskProject } from '@/lib/types'
import { addDays, byOrder, fmtDue, projectColor, weekStart } from './model'
import { LabelChip, PriorityIcon, ProjectChip } from './parts'

type Props = {
  tasks: Task[]
  projects: TaskProject[]
  today: string
  hideProject?: boolean
  onOpen: (id: string) => void
  onSetDue: (task: Task, due: string) => void
  onToggleDone: (task: Task, done: boolean) => void
  onAdd: (due: string, text: string) => Promise<unknown>
}

const PER_DAY = 3
const cmp = (a: Task, b: Task) => Number(a.status === 'done') - Number(b.status === 'done') || b.priority - a.priority || byOrder(a, b)

export function TaskCalendar({ tasks, projects, today, hideProject, onOpen, onSetDue, onToggleDone, onAdd }: Props) {
  const t = useT()
  const lang = useLang()
  const [month, setMonth] = React.useState(() => today.slice(0, 7))
  const [picked, setPicked] = React.useState(today)
  const [over, setOver] = React.useState<string | null>(null)
  const projById = React.useMemo(() => new Map(projects.map((p) => [p.id, p])), [projects])
  const byDay = React.useMemo(() => {
    const m = new Map<string, Task[]>()
    for (const x of tasks) if (x.due) m.set(x.due, [...(m.get(x.due) || []), x])
    for (const l of m.values()) l.sort(cmp)
    return m
  }, [tasks])
  const undated = tasks.filter((x) => !x.due && x.status !== 'done').length

  const first = `${month}-01`
  const start = weekStart(first)
  const days = Array.from({ length: 42 }, (_, i) => addDays(start, i))
  const weeks = days[35].slice(0, 7) === month ? 6 : 5
  const monthLabel = new Intl.DateTimeFormat(lang, { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${first}T12:00:00Z`))
  const weekday = new Intl.DateTimeFormat(lang, { weekday: 'short', timeZone: 'UTC' })
  const shift = (n: number) => {
    const d = new Date(`${first}T12:00:00Z`)
    d.setUTCMonth(d.getUTCMonth() + n)
    setMonth(d.toISOString().slice(0, 7))
  }
  const pickedTasks = byDay.get(picked) ?? []

  return (
    <div className="grid gap-4" data-testid="task-calendar">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="min-w-40 text-base font-semibold first-letter:uppercase">{monthLabel}</h2>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon-sm" onClick={() => shift(-1)} aria-label={t('tasks.cal.prev')}>
            <ChevronLeft />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setMonth(today.slice(0, 7))
              setPicked(today)
            }}
          >
            {t('tasks.due.today')}
          </Button>
          <Button variant="outline" size="icon-sm" onClick={() => shift(1)} aria-label={t('tasks.cal.next')}>
            <ChevronRight />
          </Button>
        </div>
        {undated > 0 && <span className="ml-auto text-xs text-muted-foreground">{t('tasks.cal.undated', { count: undated })}</span>}
      </div>

      <div className="overflow-hidden rounded-xl border bg-card">
        <div className="grid grid-cols-7 border-b bg-muted/30">
          {days.slice(0, 7).map((d) => (
            <div key={d} className="px-2 py-1.5 text-center text-[11px] font-medium text-muted-foreground uppercase md:text-left">
              {weekday.format(new Date(`${d}T12:00:00Z`))}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7">
          {days.slice(0, weeks * 7).map((d, i) => {
            const list = byDay.get(d) ?? []
            const inMonth = d.slice(0, 7) === month
            const isToday = d === today
            const openCount = list.filter((x) => x.status !== 'done').length
            const late = d < today && openCount > 0
            return (
              <div
                key={d}
                role="button"
                tabIndex={0}
                aria-label={`${fmtDue(d, today, lang, t)} · ${list.length}`}
                aria-pressed={picked === d}
                onClick={() => setPicked(d)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setPicked(d)
                  }
                }}
                onDragOver={(e) => {
                  if (!e.dataTransfer.types.includes('application/x-mx-task')) return
                  e.preventDefault()
                  setOver(d)
                }}
                onDragLeave={() => setOver((o) => (o === d ? null : o))}
                onDrop={(e) => {
                  const id = e.dataTransfer.getData('application/x-mx-task')
                  setOver(null)
                  const task = tasks.find((x) => x.id === id)
                  if (task && task.due !== d) onSetDue(task, d)
                }}
                className={cn(
                  'flex min-h-14 min-w-0 cursor-pointer flex-col gap-1 border-r border-b p-1 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset md:min-h-28 md:p-1.5',
                  (i + 1) % 7 === 0 && 'border-r-0',
                  !inMonth && 'bg-muted/20',
                  picked === d && 'bg-primary/5',
                  over === d && 'bg-primary/10 ring-2 ring-primary/40 ring-inset',
                )}
              >
                <span
                  className={cn(
                    'flex size-6 items-center justify-center self-center rounded-full text-xs tabular-nums md:self-start',
                    !inMonth && 'text-muted-foreground/60',
                    isToday && 'bg-primary font-semibold text-primary-foreground',
                    late && !isToday && 'text-destructive',
                  )}
                >
                  {Number(d.slice(8))}
                </span>
                {/* mobile: dots; desktop: the first tasks */}
                {list.length > 0 && (
                  <span className="flex flex-wrap justify-center gap-0.5 md:hidden" aria-hidden>
                    {list.slice(0, 4).map((x) => (
                      <span key={x.id} className={cn('size-1.5 rounded-full', x.status === 'done' && 'opacity-40')} style={{ backgroundColor: projectColor(x.project_id ? projById.get(x.project_id)?.color : null) }} />
                    ))}
                  </span>
                )}
                <div className="grid min-w-0 gap-0.5 max-md:hidden">
                  {list.slice(0, PER_DAY).map((x) => (
                    <button
                      key={x.id}
                      type="button"
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData('application/x-mx-task', x.id)
                        e.dataTransfer.effectAllowed = 'move'
                      }}
                      onClick={(e) => {
                        e.stopPropagation()
                        onOpen(x.id)
                      }}
                      title={x.title}
                      className={cn(
                        'flex min-w-0 items-center gap-1 truncate rounded border-l-2 bg-muted/50 px-1.5 py-0.5 text-left text-[11px] leading-4 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                        x.status === 'done' && 'text-muted-foreground line-through opacity-70',
                        x.due! < today && x.status !== 'done' && 'text-destructive',
                      )}
                      style={{ borderLeftColor: projectColor(x.project_id ? projById.get(x.project_id)?.color : null) }}
                    >
                      {x.priority === 3 && <PriorityIcon p={3} className="size-3 shrink-0" />}
                      <span className="truncate">
                        <Sensitive length={8}>{x.title}</Sensitive>
                      </span>
                    </button>
                  ))}
                  {list.length > PER_DAY && <span className="px-1.5 text-[11px] text-muted-foreground">{t('tasks.cal.more', { count: list.length - PER_DAY })}</span>}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <DayPanel
        day={picked}
        today={today}
        tasks={pickedTasks}
        projById={projById}
        hideProject={hideProject}
        onOpen={onOpen}
        onToggleDone={onToggleDone}
        onAdd={(text) => onAdd(picked, text)}
      />
    </div>
  )
}

function DayPanel({
  day,
  today,
  tasks,
  projById,
  hideProject,
  onOpen,
  onToggleDone,
  onAdd,
}: {
  day: string
  today: string
  tasks: Task[]
  projById: Map<string, TaskProject>
  hideProject?: boolean
  onOpen: (id: string) => void
  onToggleDone: (task: Task, done: boolean) => void
  onAdd: (text: string) => Promise<unknown>
}) {
  const t = useT()
  const lang = useLang()
  const [text, setText] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const title = fmtDue(day, today, lang, t)
  const full = new Intl.DateTimeFormat(lang, { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(`${day}T12:00:00Z`))
  return (
    <section className="grid gap-2" aria-label={full} data-testid="task-calendar-day">
      <h3 className="flex items-baseline gap-2 px-1 text-[13px] font-semibold">
        <span className="first-letter:uppercase">{title}</span>
        {title.toLowerCase() !== full.toLowerCase() && <span className="text-xs font-normal text-muted-foreground">{full}</span>}
        <span className="text-xs font-normal text-muted-foreground tabular-nums">{tasks.length}</span>
      </h3>
      <ul className="divide-y overflow-hidden rounded-xl border bg-card">
        {tasks.map((x) => {
          const done = x.status === 'done'
          const project = !hideProject && x.project_id ? projById.get(x.project_id) : undefined
          return (
            <li key={x.id} className="flex items-start gap-3 px-3 py-2.5 hover:bg-accent/40">
              <span className="flex h-5 items-center">
                <Checkbox checked={done} onCheckedChange={(v) => onToggleDone(x, v === true)} aria-label={done ? t('tasks.markOpen') : t('tasks.markDone')} />
              </span>
              <button type="button" onClick={() => onOpen(x.id)} className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 rounded text-left outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <span className={cn('min-w-0 flex-1 basis-48 text-sm leading-5 break-words', done && 'text-muted-foreground line-through decoration-muted-foreground/40')}>
                  <Sensitive length={10}>{x.title}</Sensitive>
                </span>
                <span className="flex flex-wrap items-center gap-2">
                  {x.labels.slice(0, 3).map((l) => (
                    <LabelChip key={l} label={l} />
                  ))}
                  {project && <ProjectChip project={project} className="max-w-40" />}
                  {x.priority > 0 && <PriorityIcon p={x.priority} className="size-3.5" />}
                </span>
              </button>
            </li>
          )
        })}
        <li>
          <form
            className="relative"
            onSubmit={async (e) => {
              e.preventDefault()
              if (!text.trim() || busy) return
              setBusy(true)
              try {
                await onAdd(text)
                setText('')
              } finally {
                setBusy(false)
              }
            }}
          >
            <Plus className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={text}
              disabled={busy}
              onChange={(e) => setText(e.target.value)}
              placeholder={t('tasks.cal.addOn', { day: title })}
              aria-label={t('tasks.cal.addOn', { day: title })}
              className="h-10 rounded-none border-0 pl-9 shadow-none focus-visible:ring-0 dark:bg-transparent"
            />
          </form>
        </li>
      </ul>
    </section>
  )
}
