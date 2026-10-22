// Task projects (name + colour) management.
import * as React from 'react'
import { Eye, EyeOff, FolderKanban, Link2, Plus, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { useCreateTaskProject, useDeleteTaskProject, usePatchTaskProject } from '@/lib/queries'
import type { Task, TaskProject } from '@/lib/types'
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  EmptyState,
  Input,
  Popover,
  PopoverContent,
  PopoverTrigger,
  confirm,
  useMask,
  usePresentation,
} from '@/components/ui'
import { PROJECT_COLORS, projectColor } from './model'

export function ProjectsDialog({ open, onOpenChange, projects, tasks }: { open: boolean; onOpenChange: (o: boolean) => void; projects: TaskProject[]; tasks: Task[] }) {
  const t = useT()
  const create = useCreateTaskProject()
  const [name, setName] = React.useState('')
  const [color, setColor] = React.useState<string>(() => PROJECT_COLORS[projects.length % PROJECT_COLORS.length])
  const counts = React.useMemo(() => {
    const m = new Map<string, number>()
    for (const x of tasks) if (x.project_id && x.status !== 'done') m.set(x.project_id, (m.get(x.project_id) || 0) + 1)
    return m
  }, [tasks])

  const add = (e: React.FormEvent) => {
    e.preventDefault()
    const n = name.trim()
    if (!n) return
    create.mutate(
      { name: n, color },
      {
        onSuccess: () => {
          setName('')
          setColor(PROJECT_COLORS[(projects.length + 1) % PROJECT_COLORS.length])
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="md:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('tasks.projects.title')}</DialogTitle>
          <DialogDescription>{t('tasks.projects.desc')}</DialogDescription>
        </DialogHeader>
        {projects.length === 0 ? (
          <EmptyState compact icon={FolderKanban} title={t('tasks.projects.empty')} description={t('tasks.projects.emptyDesc')} />
        ) : (
          <ul className="divide-y rounded-lg border" data-testid="task-projects">
            {projects.map((p) => (
              <ProjectRow key={p.id} project={p} open={counts.get(p.id) || 0} />
            ))}
          </ul>
        )}
        <form onSubmit={add} className="flex items-center gap-2">
          <ColorPicker value={color} onChange={setColor} />
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('tasks.projects.newPlaceholder')} maxLength={80} aria-label={t('tasks.projects.name')} />
          <Button type="submit" disabled={!name.trim()} loading={create.isPending}>
            <Plus />
            <span className="max-sm:hidden">{t('common.add')}</span>
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function ProjectRow({ project, open }: { project: TaskProject; open: number }) {
  const t = useT()
  const mask = useMask()
  const presentation = usePresentation()
  const patch = usePatchTaskProject()
  const del = useDeleteTaskProject()
  const [name, setName] = React.useState(project.name)
  React.useEffect(() => setName(project.name), [project.name])
  const commit = () => {
    const n = name.trim()
    if (!n) return setName(project.name)
    if (n !== project.name) patch.mutate({ id: project.id, name: n })
  }
  return (
    <li className="flex items-center gap-2 px-2 py-1.5">
      <ColorPicker value={project.color} onChange={(c) => patch.mutate({ id: project.id, color: c })} />
      <Input
        value={presentation ? mask(name) : name}
        readOnly={presentation}
        onChange={(e) => setName(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()}
        aria-label={t('tasks.projects.name')}
        maxLength={80}
        className="border-transparent bg-transparent shadow-none hover:border-input dark:bg-transparent"
      />
      <span className="shrink-0 text-xs text-muted-foreground tabular-nums" title={t('tasks.projects.openCount')}>
        {open}
      </span>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={project.hidden ? t('tasks.projects.show') : t('tasks.projects.hide')}
        title={project.hidden ? t('tasks.projects.show') : t('tasks.projects.hide')}
        aria-pressed={!!project.hidden}
        className={cn('shrink-0', project.hidden ? 'text-muted-foreground/60' : 'text-muted-foreground')}
        onClick={() => patch.mutate({ id: project.id, hidden: !project.hidden })}
      >
        {project.hidden ? <EyeOff /> : <Eye />}
      </Button>
      {project.workspace ? (
        <span
          className="flex size-8 shrink-0 items-center justify-center text-muted-foreground"
          title={t('tasks.projects.linked', { name: project.workspace })}
          aria-label={t('tasks.projects.linked', { name: project.workspace })}
          role="img"
        >
          <Link2 className="size-4" />
        </span>
      ) : (
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={t('common.delete')}
        className="shrink-0 text-muted-foreground hover:text-destructive"
        onClick={async () => {
          const ok = await confirm({
            title: t('tasks.projects.deleteTitle'),
            description: t('tasks.projects.deleteDesc'),
            destructive: true,
            confirmText: t('common.delete'),
          })
          if (ok) del.mutate(project.id)
        }}
      >
        <Trash2 />
      </Button>
      )}
    </li>
  )
}

export function ColorPicker({ value, onChange }: { value: string; onChange: (c: string) => void }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t('tasks.projects.color')}
          className="flex size-9 shrink-0 items-center justify-center rounded-md border border-input hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none max-md:size-11"
        >
          <span className="size-4 rounded-full" style={{ backgroundColor: projectColor(value) }} />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-2" align="start">
        <div role="radiogroup" aria-label={t('tasks.projects.color')} className="grid grid-cols-4 gap-1.5">
          {PROJECT_COLORS.map((c) => (
            <button
              key={c}
              type="button"
              role="radio"
              aria-checked={value === c}
              aria-label={c}
              title={c}
              onClick={() => {
                onChange(c)
                setOpen(false)
              }}
              className={cn(
                'flex size-8 items-center justify-center rounded-md hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none max-md:size-10',
                value === c && 'bg-accent ring-1 ring-border',
              )}
            >
              <span className="size-4 rounded-full" style={{ backgroundColor: projectColor(c) }} />
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}
