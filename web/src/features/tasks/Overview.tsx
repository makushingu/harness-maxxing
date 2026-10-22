// Overview of the Tasks page: one card per project (open tasks, progress, overdue, next due date), and the
// project header shown above the views when one project is picked.
import { Link } from 'react-router'
import { AlertTriangle, CalendarDays, Flame, MessagesSquare, Settings2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Button, Sensitive } from '@/components/ui'
import type { TaskProject } from '@/lib/types'
import { fmtDue, statsOf, type ProjectStats } from './model'
import { ProjectDot } from './parts'

type Props = {
  projects: TaskProject[]
  stats: Map<string, ProjectStats>
  emojis: Map<string, string>
  today: string
  onPick: (id: string) => void
}

export function TaskOverview({ projects, stats, emojis, today, onPick }: Props) {
  const t = useT()
  const none = statsOf(stats, '')
  const withTasks = projects.filter((p) => !p.hidden && statsOf(stats, p.id).total > 0)
  const empty = projects.filter((p) => !p.hidden && statsOf(stats, p.id).total === 0)
  // projects that need attention first: overdue, then due today, then the most open tasks
  const sorted = [...withTasks].sort((a, b) => {
    const sa = statsOf(stats, a.id)
    const sb = statsOf(stats, b.id)
    return Number(sb.overdue > 0) - Number(sa.overdue > 0) || Number(sb.today > 0) - Number(sa.today > 0) || sb.open - sa.open
  })
  return (
    <div className="grid gap-5" data-testid="task-overview">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {sorted.map((p) => (
          <ProjectCard key={p.id} name={p.name} color={p.color} emoji={p.workspace ? emojis.get(p.workspace) : undefined} stats={statsOf(stats, p.id)} today={today} onClick={() => onPick(p.id)} />
        ))}
        {none.total > 0 && <ProjectCard name={t('tasks.noProject')} stats={none} today={today} onClick={() => onPick('none')} />}
      </div>
      {empty.length > 0 && (
        <div className="grid gap-2">
          <h2 className="px-1 text-[13px] font-semibold text-muted-foreground">{t('tasks.overview.empty', { count: empty.length })}</h2>
          <div className="flex flex-wrap gap-1.5">
            {empty.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => onPick(p.id)}
                className="inline-flex h-8 items-center gap-1.5 rounded-full border bg-card px-3 text-[13px] text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <ProjectDot color={p.color} className="size-2" />
                <Sensitive length={5}>{p.name}</Sensitive>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ProjectCard({ name, color, emoji, stats, today, onClick }: { name: string; color?: string; emoji?: string; stats: ProjectStats; today: string; onClick: () => void }) {
  const t = useT()
  const lang = useLang()
  const pct = stats.total ? Math.round((stats.done / stats.total) * 100) : 0
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'grid gap-3 rounded-xl border bg-card p-4 text-left shadow-xs transition-[border-color,box-shadow] hover:border-foreground/20 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
        stats.overdue > 0 && 'border-destructive/30',
      )}
    >
      <div className="flex min-w-0 items-center gap-2">
        {emoji ? <span className="text-base leading-none">{emoji}</span> : <ProjectDot color={color} className="size-2.5" />}
        <span className="min-w-0 flex-1 truncate text-sm font-semibold">
          <Sensitive length={6}>{name}</Sensitive>
        </span>
        <span className="text-xs text-muted-foreground tabular-nums">{t('tasks.overview.open', { count: stats.open })}</span>
      </div>
      <div className="grid gap-1.5">
        <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={t('tasks.overview.progress')}>
          <div className="h-full rounded-full bg-success/70" style={{ width: `${pct}%` }} />
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>{t('tasks.overview.done', { done: stats.done, total: stats.total })}</span>
          {stats.doing > 0 && <span>{t('tasks.overview.doing', { count: stats.doing })}</span>}
          {stats.overdue > 0 && (
            <span className="inline-flex items-center gap-1 font-medium text-destructive">
              <AlertTriangle className="size-3" />
              {t('tasks.overview.overdue', { count: stats.overdue })}
            </span>
          )}
          {stats.urgent > 0 && (
            <span className="inline-flex items-center gap-1 text-destructive">
              <Flame className="size-3" />
              {t('tasks.overview.urgent', { count: stats.urgent })}
            </span>
          )}
        </div>
      </div>
      <div className="flex min-h-5 min-w-0 items-center gap-1.5 text-xs">
        {stats.next ? (
          <>
            <CalendarDays className={cn('size-3.5 shrink-0', stats.next.due! < today ? 'text-destructive' : 'text-muted-foreground')} />
            <span className={cn('shrink-0 font-medium', stats.next.due! < today && 'text-destructive')}>{fmtDue(stats.next.due!, today, lang, t)}</span>
            <span className="min-w-0 truncate text-muted-foreground">
              <Sensitive length={10}>{stats.next.title}</Sensitive>
            </span>
          </>
        ) : (
          <span className="text-muted-foreground">{stats.open ? t('tasks.overview.noDue') : t('tasks.overview.allDone')}</span>
        )}
      </div>
    </button>
  )
}

/** Header above the views when one project is picked: name, counts, progress, link to its sessions. */
export function ProjectHeader({ project, emoji, stats, onManage }: { project?: TaskProject; emoji?: string; stats: ProjectStats; onManage: () => void }) {
  const t = useT()
  const pct = stats.total ? Math.round((stats.done / stats.total) * 100) : 0
  return (
    <div className="grid min-w-0 gap-1.5 md:flex md:items-center md:gap-4" data-testid="task-project-header">
      <div className="flex min-w-0 items-center gap-2.5 md:contents">
        <div className="flex min-w-0 flex-1 items-center gap-2.5 md:flex-none">
          {project ? emoji ? <span className="text-lg leading-none">{emoji}</span> : <ProjectDot color={project.color} className="size-3" /> : null}
          <h2 className="min-w-0 truncate text-lg font-semibold">{project ? <Sensitive length={6}>{project.name}</Sensitive> : t('tasks.noProject')}</h2>
        </div>
        {project && (
          <div className="flex shrink-0 items-center gap-1.5 md:order-last">
            {project.workspace && (
              <Button asChild variant="outline" size="sm">
                <Link to={`/sessions?path=${encodeURIComponent(`projects/${project.workspace}`)}`}>
                  <MessagesSquare />
                  {t('tasks.header.sessions')}
                </Link>
              </Button>
            )}
            <Button variant="ghost" size="icon-sm" onClick={onManage} aria-label={t('tasks.manageProjects')} title={t('tasks.manageProjects')}>
              <Settings2 />
            </Button>
          </div>
        )}
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground md:flex-1">
        <span className="tabular-nums">{t('tasks.overview.open', { count: stats.open })}</span>
        {stats.overdue > 0 && <span className="font-medium text-destructive tabular-nums">{t('tasks.overview.overdue', { count: stats.overdue })}</span>}
        <span className="flex items-center gap-2">
          <span className="h-1.5 w-20 overflow-hidden rounded-full bg-muted" aria-hidden>
            <span className="block h-full rounded-full bg-success/70" style={{ width: `${pct}%` }} />
          </span>
          <span className="whitespace-nowrap tabular-nums">{t('tasks.overview.done', { done: stats.done, total: stats.total })}</span>
        </span>
      </div>
    </div>
  )
}
