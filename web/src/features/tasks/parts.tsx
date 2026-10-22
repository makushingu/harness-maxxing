// Small presentational pieces shared by the board, the list and the drawer.
import * as React from 'react'
import { CalendarDays } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Sensitive } from '@/components/ui'
import type { Task, TaskPriority, TaskProject } from '@/lib/types'
import { PRIORITY_CLS, PRIORITY_KEY, dueState, fmtDue, projectColor } from './model'


/** Three signal bars, the first `p` filled (0 = all dimmed). */
export function PriorityIcon({ p, className }: { p: TaskPriority; className?: string }) {
  const t = useT()
  return (
    <svg viewBox="0 0 16 16" className={cn('size-4 shrink-0', PRIORITY_CLS[p], className)} aria-label={t(PRIORITY_KEY[p])} role="img">
      {[0, 1, 2].map((i) => (
        <rect key={i} x={2 + i * 4.5} y={10 - i * 3.5} width={3} height={4 + i * 3.5} rx={1} fill="currentColor" opacity={i < p ? 1 : 0.25} />
      ))}
    </svg>
  )
}

export function ProjectDot({ color, className }: { color?: string | null; className?: string }) {
  return <span aria-hidden className={cn('inline-block size-2.5 shrink-0 rounded-full', className)} style={{ backgroundColor: projectColor(color) }} />
}

export function ProjectChip({ project, className }: { project: TaskProject; className?: string }) {
  return (
    <span className={cn('inline-flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground', className)}>
      <ProjectDot color={project.color} className="size-2" />
      <span className="truncate">
        <Sensitive length={5}>{project.name}</Sensitive>
      </span>
    </span>
  )
}

export function DueBadge({ task, today, className }: { task: Task; today: string; className?: string }) {
  const t = useT()
  const lang = useLang()
  if (!task.due) return null
  const st = dueState(task, today)
  const done = task.status === 'done'
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium tabular-nums',
        done ? 'text-muted-foreground' : st === 'overdue' ? 'bg-destructive/12 text-destructive' : st === 'today' ? 'bg-warning/12 text-warning' : 'text-muted-foreground',
        className,
      )}
      title={task.due}
    >
      <CalendarDays className="size-3" />
      {st === 'overdue' && !done && <span className="sr-only">{t('tasks.due.overdue')}: </span>}
      <Sensitive length={4}>{fmtDue(task.due, today, lang, t)}</Sensitive>
    </span>
  )
}

export function LabelChip({ label, className, children }: { label: string; className?: string; children?: React.ReactNode }) {
  return (
    <span className={cn('inline-flex h-5 max-w-40 shrink-0 items-center gap-1 rounded-full border bg-muted/50 px-2 text-[11px] font-medium text-muted-foreground', className)}>
      <span className="truncate">
        <Sensitive length={4}>{label}</Sensitive>
      </span>
      {children}
    </span>
  )
}
