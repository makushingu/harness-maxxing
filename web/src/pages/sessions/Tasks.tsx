// Background work of Claude Code (sub-agents, commands sent to the background) in the thread: the details shown
// under its Agent / Bash line, and the list of what still runs on the thread's status line (a click opens its line).
import * as React from 'react'
import { Ban, Bot, Check, ChevronRight, CircleAlert, SquareTerminal } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Popover, PopoverContent, PopoverTrigger, Sensitive, Spinner } from '@/components/ui'
import { Markdown } from '@/components/ui/markdown'
import { isShownTask, taskStatus, type Task, type TaskStatus } from './log'
import { fmtElapsed, fmtTokens } from './util'

const OPEN_EVENT = 'mx-open-task'

/** Opens (and scrolls to) the tool line that started a task, when it is in the loaded thread. */
export function openTaskLine(toolUseId: string) {
  window.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: toolUseId }))
}

/** For a tool line: `open()` when the bar asks for it. */
export function useOpenTaskLine(toolUseId: string | undefined, open: () => void, el: React.RefObject<HTMLElement | null>) {
  React.useEffect(() => {
    if (!toolUseId) return
    const on = (e: Event) => {
      if ((e as CustomEvent).detail !== toolUseId) return
      open()
      requestAnimationFrame(() => el.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }))
    }
    window.addEventListener(OPEN_EVENT, on)
    return () => window.removeEventListener(OPEN_EVENT, on)
  }, [toolUseId, open, el])
}

/** Seconds since `Date.now()`, re-rendered every second while `active`. */
function useNow(active: boolean): number {
  const [now, setNow] = React.useState(() => Date.now() / 1000)
  React.useEffect(() => {
    if (!active) return
    setNow(Date.now() / 1000)
    const id = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(id)
  }, [active])
  return now
}

function elapsed(tk: Task, status: TaskStatus, now: number): number {
  if (status === 'running') return now - tk.started
  if (tk.duration_ms) return tk.duration_ms / 1000
  return (tk.ended ?? tk.updated) - tk.started
}

export function TaskElapsed({ task, status, className }: { task: Task; status: TaskStatus; className?: string }) {
  const now = useNow(status === 'running')
  const sec = elapsed(task, status, now)
  if (status === 'interrupted' && sec < 1) return null           // no sign of it after its start: duration unknown
  return <span className={cn('shrink-0 font-mono text-[11px] text-muted-foreground tabular-nums', className)}>{fmtElapsed(sec)}</span>
}

export function TaskStatusIcon({ status }: { status: TaskStatus }) {
  if (status === 'running') return <Spinner className="size-3.5" />
  if (status === 'completed') return <Check className="size-3.5 text-success" />
  if (status === 'failed') return <CircleAlert className="size-3.5 text-destructive" />
  return <Ban className="size-3.5 text-muted-foreground" />
}

function Facts({ task, status }: { task: Task; status: TaskStatus }) {
  const t = useT()
  const sec = elapsed(task, status, useNow(status === 'running'))
  const parts = [
    t(`tasks.status.${status}`),
    [t(`tasks.kind.${task.kind || 'other'}`), task.agent_type && task.agent_type !== 'general-purpose' ? task.agent_type : '', task.background ? t('tasks.background') : '']
      .filter(Boolean)
      .join(' '),
    task.tools ? t('tasks.tools', { count: task.tools }) : '',
    task.tokens ? t('tasks.tokens', { count: fmtTokens(task.tokens) }) : '',
    sec >= 1 || status !== 'interrupted' ? fmtElapsed(sec) : '',
  ].filter(Boolean)
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
      {parts.map((p, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span aria-hidden>·</span>}
          <span className={cn(i === 0 && status === 'failed' && 'text-destructive', i === parts.length - 1 && 'tabular-nums')}>{p}</span>
        </React.Fragment>
      ))}
    </span>
  )
}

function LastAction({ task }: { task: Task }) {
  const t = useT()
  if (!task.activity) return null
  return (
    <p className="min-w-0 truncate text-xs text-muted-foreground">
      {t('tasks.last')} <Sensitive length={16}><span className="font-mono text-[12px] text-foreground/80">{task.activity}</span></Sensitive>
    </p>
  )
}

/** Inside an opened Agent / Bash line: where the task is, what it did last, then its report. */
export function TaskDetails({ task, status }: { task: Task; status: TaskStatus }) {
  const t = useT()
  const report = task.summary && task.summary !== task.description ? task.summary : ''
  return (
    <div className="grid gap-1.5 rounded-md border bg-card px-2.5 py-2">
      <Facts task={task} status={status} />
      {status === 'running' && <LastAction task={task} />}
      {status === 'interrupted' && <p className="text-xs text-muted-foreground">{t('tasks.interruptedHint')}</p>}
      {report && (
        <div className="grid gap-1">
          <span className="text-xs font-medium text-muted-foreground">{t('tasks.report')}</span>
          <Sensitive block>
            <div className="max-h-80 overflow-auto rounded-md bg-muted px-2.5 py-2 text-[13px]">
              <Markdown>{report}</Markdown>
            </div>
          </Sensitive>
        </div>
      )}
    </div>
  )
}

/** The sub-agents and background commands of the status line at the end of the thread (`RunningRow`): "8 subagents
 *  running" when nothing else is pending, or "· 8 subagents" after the current tool. A click lists them, a click on
 *  one opens its line in the thread. Built from the loaded log, so it is back as it was after a reload. */
export function TasksRunning({ tasks, lead }: { tasks: Task[]; lead: boolean }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  React.useEffect(() => {
    if (!tasks.length) setOpen(false)
  }, [tasks.length])
  if (!tasks.length) return null
  const agentsOnly = tasks.every((tk) => tk.kind === 'agent')
  const label = lead
    ? t(agentsOnly ? 'tasks.bar' : 'tasks.barAny', { count: tasks.length })
    : t(agentsOnly ? 'tasks.short' : 'tasks.shortAny', { count: tasks.length })
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="tasks-running"
          className={cn(
            'flex min-w-0 items-center gap-1 rounded-md px-1.5 -mx-1.5 py-0.5 hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none pointer-coarse:py-2',
            !lead && 'shrink-0',
          )}
        >
          {!lead && <span aria-hidden>·</span>}
          <span className="truncate">{label}</span>
          <ChevronRight className={cn('size-3.5 shrink-0 transition-transform', open && '-rotate-90')} />
        </button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="w-[min(28rem,calc(100vw-16px))] p-1.5">
        <p className="px-2 pt-1 pb-1.5 text-xs font-medium text-muted-foreground">{t('tasks.title')}</p>
        <ul className="grid gap-0.5">
          {tasks.map((tk) => (
            <li key={tk.id}>
              <button
                type="button"
                onClick={() => {
                  setOpen(false)
                  if (tk.tool_use_id) openTaskLine(tk.tool_use_id)
                }}
                className="grid w-full grid-cols-[minmax(0,1fr)] content-center gap-0.5 rounded-md px-2 py-1.5 text-left pointer-coarse:min-h-10 hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
              >
                <TaskLine task={tk} />
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  )
}

/** The tasks still running, oldest first (`RunningRow`). */
export function runningTasks(tasks: Record<string, Task>): Task[] {
  return Object.values(tasks)
    .filter((tk) => isShownTask(tk) && taskStatus(tk, true) === 'running')
    .sort((a, b) => a.started - b.started)
}

/** One running task as the bar's list shows it: icon, what it is, running time, its last action, tools and tokens
 *  (also the sidebar's session preview card). */
export function TaskLine({ task: tk }: { task: Task }) {
  const t = useT()
  const Icon = tk.kind === 'agent' ? Bot : SquareTerminal
  return (
    <>
      <span className="flex min-w-0 items-center gap-2 text-[13px]">
        <Icon className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate font-medium">
          <Sensitive length={14}>{tk.description || t(`tasks.kind.${tk.kind || 'other'}`)}</Sensitive>
        </span>
        <TaskElapsed task={tk} status="running" />
      </span>
      <span className="pl-5.5">
        <LastAction task={tk} />
        {!!(tk.tools || tk.tokens) && (
          <span className="block text-[11px] text-muted-foreground">
            {[tk.tools ? t('tasks.tools', { count: tk.tools }) : '', tk.tokens ? t('tasks.tokens', { count: fmtTokens(tk.tokens) }) : ''].filter(Boolean).join(' · ')}
          </span>
        )}
      </span>
    </>
  )
}
