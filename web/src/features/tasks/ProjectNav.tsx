// Projects bar of the Tasks page: overview, all tasks, tasks without a project, then one entry per task project.
// A column in the second-level sidebar (pages/tasks PageList; touch: the left drawer).
import * as React from 'react'
import { Eye, EyeOff, FolderKanban, Inbox, LayoutGrid, ListChecks, MoreHorizontal, Settings2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, Sensitive } from '@/components/ui'
import { usePatchTaskProject } from '@/lib/queries'
import type { TaskProject } from '@/lib/types'
import { statsOf, type ProjectStats } from './model'
import { ProjectDot } from './parts'

/** What the page shows: the overview, every task, the tasks without a project, or one task project (its id). */
export type Scope = 'overview' | 'all' | 'none' | (string & {})

type Props = {
  scope: Scope
  onScope: (s: Scope) => void
  projects: TaskProject[]
  stats: Map<string, ProjectStats>
  emojis: Map<string, string>
  onManage: () => void
}

export function ProjectNav({ scope, onScope, projects, stats, emojis, onManage }: Props) {
  const t = useT()
  const [showHidden, setShowHidden] = React.useState(false)
  const all = React.useMemo(() => [...stats.values()].reduce((n, s) => n + s.open, 0), [stats])
  const none = statsOf(stats, '')
  const hiddenCount = projects.filter((p) => p.hidden).length
  const shown = projects.filter((p) => !p.hidden || showHidden || p.id === scope)

  return (
      <nav aria-label={t('tasks.nav.label')} className="grid min-h-0 flex-1 content-start gap-0.5 overflow-y-auto p-2" data-testid="task-nav" data-tour="tasks-projects">
        <Entry active={scope === 'overview'} onClick={() => onScope('overview')} icon={<LayoutGrid className="size-4" />}>
          {t('tasks.nav.overview')}
        </Entry>
        <Entry active={scope === 'all'} onClick={() => onScope('all')} icon={<ListChecks className="size-4" />} count={all}>
          {t('tasks.nav.all')}
        </Entry>
        {(none.total > 0 || scope === 'none') && (
          <Entry active={scope === 'none'} onClick={() => onScope('none')} icon={<Inbox className="size-4" />} count={none.open}>
            {t('tasks.noProject')}
          </Entry>
        )}
        <div className="mt-3 mb-1 flex h-6 items-center justify-between px-2.5">
          <span className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('tasks.projects')}</span>
          <button
            type="button"
            onClick={onManage}
            aria-label={t('tasks.manageProjects')}
            title={t('tasks.manageProjects')}
            className="flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none pointer-coarse:-mr-2 pointer-coarse:size-10"
          >
            <Settings2 className="size-3.5" />
          </button>
        </div>
        {projects.length === 0 && (
          <button type="button" onClick={onManage} className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] text-muted-foreground hover:bg-accent hover:text-foreground">
            <FolderKanban className="size-4" />
            {t('tasks.nav.noProjects')}
          </button>
        )}
        {shown.map((p) => (
          <ProjectEntry key={p.id} project={p} emoji={p.workspace ? emojis.get(p.workspace) : undefined} stats={statsOf(stats, p.id)} active={scope === p.id} onClick={() => onScope(p.id)} />
        ))}
        {hiddenCount > 0 && (
          <button
            type="button"
            onClick={() => setShowHidden((v) => !v)}
            className="mt-1 flex h-8 items-center gap-2 rounded-md px-2.5 text-left text-xs pointer-coarse:h-10 text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            {showHidden ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
            {showHidden ? t('tasks.nav.hideHidden') : t('tasks.nav.showHidden', { count: hiddenCount })}
          </button>
        )}
      </nav>
  )
}

function Entry({ active, onClick, icon, count, children }: { active: boolean; onClick: () => void; icon: React.ReactNode; count?: number; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex h-8 min-w-0 items-center gap-2.5 rounded-md px-2.5 pointer-coarse:h-10 text-left text-[13px] transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
        active ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
      )}
    >
      <span className="flex size-4 shrink-0 items-center justify-center">{icon}</span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {count != null && count > 0 && <span className="text-xs text-muted-foreground tabular-nums">{count}</span>}
    </button>
  )
}

function ProjectEntry({ project, emoji, stats, active, onClick }: { project: TaskProject; emoji?: string; stats: ProjectStats; active: boolean; onClick: () => void }) {
  const t = useT()
  const patch = usePatchTaskProject()
  return (
    <div className={cn('group/entry relative flex items-center rounded-md', active ? 'bg-accent' : 'hover:bg-accent/60', project.hidden && 'opacity-60')}>
      <button
        type="button"
        onClick={onClick}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'flex h-8 min-w-0 flex-1 items-center gap-2.5 rounded-md pr-8 pl-2.5 pointer-coarse:h-10 pointer-coarse:pr-11 text-left text-[13px] focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
          active ? 'font-medium text-foreground' : 'text-muted-foreground hover:text-foreground',
        )}
      >
        <span className="flex size-4 shrink-0 items-center justify-center">
          {emoji ? <span className="text-[13px] leading-none">{emoji}</span> : <ProjectDot color={project.color} className="size-2.5" />}
        </span>
        <span className="min-w-0 flex-1 truncate">
          <Sensitive length={6}>{project.name}</Sensitive>
        </span>
        {stats.overdue > 0 && <span className="size-1.5 shrink-0 rounded-full bg-destructive" title={t('tasks.nav.overdue', { count: stats.overdue })} aria-label={t('tasks.nav.overdue', { count: stats.overdue })} role="img" />}
        {stats.open > 0 && <span className="text-xs text-muted-foreground tabular-nums group-hover/entry:invisible group-focus-within/entry:invisible">{stats.open}</span>}
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={t('common.more')}
            className="absolute right-1 flex size-6 items-center justify-center rounded text-muted-foreground opacity-0 group-hover/entry:opacity-100 pointer-coarse:right-0 pointer-coarse:size-10 pointer-coarse:opacity-100 hover:bg-background/60 hover:text-foreground focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none data-[state=open]:opacity-100"
          >
            <MoreHorizontal className="size-3.5" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuItem onSelect={() => patch.mutate({ id: project.id, hidden: !project.hidden })}>
            {project.hidden ? <Eye /> : <EyeOff />}
            {project.hidden ? t('tasks.projects.show') : t('tasks.projects.hide')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
