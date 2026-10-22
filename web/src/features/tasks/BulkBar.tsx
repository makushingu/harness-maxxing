// Floating bar shown while tasks are selected: one change applied to all of them (POST /api/tasks/bulk).
import * as React from 'react'
import { CalendarDays, CheckSquare, CircleDot, Flag, FolderKanban, Tag, Trash2, X } from 'lucide-react'
import { useT } from '@/i18n'
import { useBulkTasks } from '@/lib/queries'
import type { Task, TaskBulkBody, TaskPriority, TaskProject } from '@/lib/types'
import { useHotkey } from '@/commands/shortcuts'
import {
  Button,
  confirm,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Input,
  Sensitive,
  toast,
} from '@/components/ui'
import { STATUSES, STATUS_KEY, PRIORITIES, PRIORITY_KEY, addDays } from './model'
import { PriorityIcon, ProjectDot } from './parts'
import { StatusPip } from './Board'
import { useTaskSelection } from './selection'

export function BulkBar({ tasks, visible, projects, labels, today }: { tasks: Task[]; visible: Task[]; projects: TaskProject[]; labels: string[]; today: string }) {
  const t = useT()
  const ids = useTaskSelection((s) => s.ids)
  const { add, clear } = useTaskSelection.getState()
  const bulk = useBulkTasks()
  const [newLabel, setNewLabel] = React.useState('')

  // Forget ids that are no longer visible (deleted elsewhere, hidden by a filter) - a bulk action must never
  // touch a task the user cannot see - and the whole selection when leaving the page.
  React.useEffect(() => {
    const known = new Set(visible.map((x) => x.id))
    const gone = [...ids].filter((id) => !known.has(id))
    if (gone.length) useTaskSelection.getState().remove(gone)
  }, [visible, ids])
  React.useEffect(() => () => useTaskSelection.getState().clear(), [])
  useHotkey('escape', () => clear(), { enabled: ids.size > 0 })
  // Ctrl/⌘+A selects every visible task while a selection is in progress (never inside a text field).
  const visibleRef = React.useRef(visible)
  visibleRef.current = visible
  React.useEffect(() => {
    if (!ids.size) return
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== 'a' || el?.closest('input, textarea, [contenteditable="true"]')) return
      e.preventDefault()
      useTaskSelection.getState().add(visibleRef.current.map((x) => x.id))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ids.size])

  if (!ids.size) return null
  const sel = [...ids]
  const selected = tasks.filter((x) => ids.has(x.id))
  const apply = (body: Omit<TaskBulkBody, 'ids'>, done?: string) =>
    bulk.mutate({ ids: sel, ...body }, { onSuccess: (r) => toast.success(done || t('tasks.bulk.updated', { count: r.updated })) })
  const remove = async () => {
    const ok = await confirm({ title: t('tasks.bulk.deleteTitle', { count: sel.length }), description: t('tasks.deleteDesc'), destructive: true, confirmText: t('common.delete') })
    if (ok) bulk.mutate({ ids: sel, delete: true }, { onSuccess: (r) => (toast.success(t('tasks.bulk.deleted', { count: r.deleted })), clear()) })
  }
  const addLabel = (l: string) => {
    const label = l.trim()
    if (label) apply({ labels_add: [label] })
    setNewLabel('')
  }
  const used = new Set(selected.flatMap((x) => x.labels))

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-[calc(1rem+var(--safe-bottom))] z-40 flex justify-center px-3">
      <div role="toolbar" aria-label={t('tasks.bulk.label')} className="mx-rise pointer-events-auto flex max-w-full items-center gap-1 overflow-x-auto rounded-xl border bg-popover p-1.5 shadow-pop">
        <span className="px-2 text-sm font-medium whitespace-nowrap tabular-nums">{t('tasks.bulk.count', { count: sel.length })}</span>
        <Button variant="ghost" size="sm" onClick={() => add(visible.map((x) => x.id))} disabled={visible.every((x) => ids.has(x.id))}>
          <CheckSquare /> <span className="max-md:hidden">{t('tasks.bulk.selectAll')}</span>
        </Button>
        <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm">
              <CircleDot /> <span className="max-sm:hidden">{t('tasks.bulk.status')}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="start">
            {STATUSES.map((s) => (
              <DropdownMenuItem key={s} onSelect={() => apply({ patch: { status: s } })}>
                <StatusPip status={s} /> {t(STATUS_KEY[s])}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm">
              <Flag /> <span className="max-sm:hidden">{t('tasks.bulk.priority')}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="start">
            {PRIORITIES.map((p) => (
              <DropdownMenuItem key={p} onSelect={() => apply({ patch: { priority: p as TaskPriority } })}>
                <PriorityIcon p={p} className="size-4" /> {t(PRIORITY_KEY[p])}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm">
              <CalendarDays /> <span className="max-sm:hidden">{t('tasks.bulk.due')}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="start">
            <DropdownMenuItem onSelect={() => apply({ patch: { due: today } })}>{t('tasks.bulk.dueToday')}</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => apply({ patch: { due: addDays(today, 1) } })}>{t('tasks.bulk.dueTomorrow')}</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => apply({ patch: { due: addDays(today, 7) } })}>{t('tasks.bulk.dueWeek')}</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => apply({ patch: { due: null } })}>{t('tasks.bulk.dueNone')}</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm">
              <FolderKanban /> <span className="max-sm:hidden">{t('tasks.bulk.project')}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="start" className="max-h-72 overflow-y-auto">
            <DropdownMenuItem onSelect={() => apply({ patch: { project_id: null } })}>{t('tasks.noProject')}</DropdownMenuItem>
            {projects.length > 0 && <DropdownMenuSeparator />}
            {projects.map((p) => (
              <DropdownMenuItem key={p.id} onSelect={() => apply({ patch: { project_id: p.id } })}>
                <ProjectDot color={p.color} /> <Sensitive length={6}>{p.name}</Sensitive>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm">
              <Tag /> <span className="max-sm:hidden">{t('tasks.bulk.labels')}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="start" className="max-h-80 w-60 overflow-y-auto">
            {labels.length > 0 && <DropdownMenuLabel>{t('tasks.bulk.addLabel')}</DropdownMenuLabel>}
            {labels.map((l) => (
              <DropdownMenuItem key={`a:${l}`} onSelect={() => apply({ labels_add: [l] })}>
                <Tag /> {l}
              </DropdownMenuItem>
            ))}
            <form
              className="p-1"
              onSubmit={(e) => {
                e.preventDefault()
                addLabel(newLabel)
              }}
            >
              <Input value={newLabel} onChange={(e) => setNewLabel(e.target.value)} onKeyDown={(e) => e.stopPropagation()} placeholder={t('tasks.bulk.newLabel')} className="h-8" maxLength={40} />
            </form>
            {used.size > 0 && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>{t('tasks.bulk.removeLabel')}</DropdownMenuLabel>
                {[...used].map((l) => (
                  <DropdownMenuItem key={`r:${l}`} onSelect={() => apply({ labels_remove: [l] })}>
                    <X /> {l}
                  </DropdownMenuItem>
                ))}
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />
        <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => void remove()} aria-label={t('common.delete')}>
          <Trash2 />
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={clear} aria-label={t('tasks.bulk.clear')}>
          <X />
        </Button>
      </div>
    </div>
  )
}
