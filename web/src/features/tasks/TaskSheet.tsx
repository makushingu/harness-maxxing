// Task drawer (Sheet): every field saves by itself. Title and notes are debounced and kept as a local
// draft, so a live refresh (Claude editing tasks.json) never overwrites what the user is typing.
import * as React from 'react'
import { Link } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, Check, FileQuestion, Settings2, Trash2, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { api, seg } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import { qk, usePatchTask, useDeleteTask, useSettings, useTopics } from '@/lib/queries'
import type { Task, TaskInput, TaskPriority, TaskProject, TaskStatus } from '@/lib/types'
import {
  Button,
  EmptyState,
  Input,
  Segmented,
  Select,
  Sensitive,
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  Skeleton,
  Spinner,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  confirm,
  toast,
  useMask,
  usePresentation,
} from '@/components/ui'
import { Combobox } from '@/components/ui/combobox'
import { PRIORITIES, PRIORITY_KEY, STATUSES, STATUS_KEY, addDays, allLabels, dueState, todayISO } from './model'
import { LabelChip, PriorityIcon, ProjectDot } from './parts'

const Markdown = React.lazy(() => import('@/components/ui/markdown').then((m) => ({ default: m.Markdown })))

export function TaskSheet({
  id,
  tasks,
  projects,
  loading,
  onClose,
  onManageProjects,
}: {
  id: string | null
  tasks: Task[] | undefined
  projects: TaskProject[]
  loading: boolean
  onClose: () => void
  onManageProjects: () => void
}) {
  const t = useT()
  const task = id ? tasks?.find((x) => x.id === id) : undefined
  return (
    <Sheet open={!!id} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="md:w-[560px]" aria-describedby={undefined}>
        {task ? (
          <TaskEditor key={task.id} task={task} tasks={tasks || []} projects={projects} onClose={onClose} onManageProjects={onManageProjects} />
        ) : loading ? (
          <div className="grid gap-4 p-5">
            <SheetTitle className="sr-only">{t('tasks.task')}</SheetTitle>
            <Skeleton className="h-8 w-3/4" />
            <Skeleton className="h-40" />
          </div>
        ) : (
          <>
            <SheetTitle className="sr-only">{t('tasks.notFound')}</SheetTitle>
            <EmptyState icon={FileQuestion} title={t('tasks.notFound')} description={t('tasks.notFoundDesc')} action={<Button variant="outline" onClick={onClose}>{t('common.back')}</Button>} />
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

/** Local draft of a text field: follows the server value until edited, saved after `delay` ms idle. */
function useDraft(server: string, save: (v: string) => Promise<unknown> | void, delay = 700, valid: (v: string) => boolean = () => true) {
  const [value, setValue] = React.useState(server)
  const dirty = React.useRef(false)
  const saving = React.useRef(false)
  const latest = React.useRef(value)
  const saveRef = React.useRef(save)
  saveRef.current = save
  React.useEffect(() => {
    if (!dirty.current) {
      setValue(server)
      latest.current = server
    }
  }, [server])
  const flush = React.useCallback(() => {
    if (!dirty.current || saving.current) return
    const v = latest.current
    if (!valid(v)) return
    if (v === server) {
      dirty.current = false
      return
    }
    saving.current = true
    void Promise.resolve(saveRef.current(v))
      .then((ok) => {
        // Failed saves retain the edited draft across live server refreshes.
        if (ok !== false && latest.current === v) dirty.current = false
      })
      .catch(() => { /* Keep the draft dirty; retry on blur or the next edit. */ })
      .finally(() => {
        saving.current = false
        if (dirty.current && latest.current !== v) flushRef.current()
      })
  }, [server, valid])
  const flushRef = React.useRef(flush)
  flushRef.current = flush
  React.useEffect(() => {
    if (!dirty.current) return
    const id = setTimeout(() => flushRef.current(), delay)
    return () => clearTimeout(id)
  }, [value, delay])
  React.useEffect(() => () => flushRef.current(), []) // closing the drawer saves pending text
  const onChange = (v: string) => {
    dirty.current = true
    latest.current = v
    setValue(v)
  }
  return { value, onChange, flush, dirty: () => dirty.current }
}

function TaskEditor({
  task,
  tasks,
  projects,
  onClose,
  onManageProjects,
}: {
  task: Task
  tasks: Task[]
  projects: TaskProject[]
  onClose: () => void
  onManageProjects: () => void
}) {
  const t = useT()
  const lang = useLang()
  const qc = useQueryClient()
  const { data: settings } = useSettings()
  const tz = settings?.timezone
  const today = todayISO(tz)
  const presentation = usePresentation()
  const mask = useMask()
  const patch = usePatchTask(task.id)
  const del = useDeleteTask()
  const { topics } = useTopics()
  const [state, setState] = React.useState<SaveState>('idle')
  const mounted = React.useRef(true)
  React.useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const save = React.useCallback(
    async (b: TaskInput) => {
      if (!mounted.current) {
        // drawer already closed: plain request + refresh
        try {
          await api.patch(`/api/tasks/${seg(task.id)}`, b)
        } catch {
          toast.error(t('tasks.saveFailed'))
          return false
        }
        await qc.invalidateQueries({ queryKey: qk.tasks })
        return true
      }
      setState('saving')
      try {
        await patch.mutateAsync({ id: task.id, ...b })
        if (mounted.current) setState('saved')
        return true
      } catch {
        if (mounted.current) setState('error')
        return false
      }
    },
    [patch, qc, task.id, t],
  )

  const title = useDraft(task.title, (v) => save({ title: v.trim() }), 700, (v) => v.trim().length > 0)
  const notes = useDraft(task.notes, (v) => save({ notes: v }), 900)
  const [labelDraft, setLabelDraft] = React.useState('')
  const known = React.useMemo(() => allLabels(tasks).filter((l) => !task.labels.includes(l)), [tasks, task.labels])

  const addLabel = (raw: string) => {
    const l = raw.trim().replace(/^#/, '').slice(0, 40)
    setLabelDraft('')
    if (!l || task.labels.includes(l)) return
    void save({ labels: [...task.labels, l] })
  }

  const topicOptions = React.useMemo(
    () => [
      { value: '__none', label: t('tasks.noTopic') },
      ...topics.map((x) => ({ value: x.path, label: mask(`${x.project} / ${x.name}`, 8) })),
    ],
    [topics, t, mask],
  )
  const topicKnown = !task.topic_path || topics.some((x) => x.path === task.topic_path)
  const st = dueState(task, today)

  return (
    <>
      <SheetHeader className="gap-3 pr-12 max-md:pr-5">
        <div className="flex h-5 items-center gap-2 text-xs text-muted-foreground" aria-live="polite">
          <SheetTitle className="text-xs font-medium text-muted-foreground">{t('tasks.task')}</SheetTitle>
          <span aria-hidden>·</span>
          {state === 'saving' ? (
            <span className="inline-flex items-center gap-1">
              <Spinner className="size-3" /> {t('tasks.saving')}
            </span>
          ) : state === 'saved' ? (
            <span className="inline-flex items-center gap-1">
              <Check className="size-3" /> {t('common.saved')}
            </span>
          ) : state === 'error' ? (
            <span className="text-destructive">{t('tasks.saveFailed')}</span>
          ) : (
            <span>{t('tasks.autosave')}</span>
          )}
        </div>
        <SheetDescription className="sr-only">{t('tasks.drawerDesc')}</SheetDescription>
        {presentation ? (
          <Sensitive block className="h-9">{null}</Sensitive>
        ) : (
          <div className="grid gap-1">
            <Textarea
              value={title.value}
              onChange={(e) => title.onChange(e.target.value.replace(/\n/g, ' '))}
              onBlur={title.flush}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  title.flush()
                }
              }}
              minRows={1}
              maxRows={4}
              aria-label={t('tasks.field.title')}
              aria-invalid={!title.value.trim() || undefined}
              className="-mx-2 border-transparent bg-transparent px-2 text-lg leading-snug font-semibold shadow-none hover:border-input focus-visible:border-ring dark:bg-transparent max-md:text-lg"
            />
            {!title.value.trim() && <p className="text-[13px] text-destructive">{t('tasks.titleRequired')}</p>}
          </div>
        )}
      </SheetHeader>
      <SheetBody className="grid content-start gap-6">
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[minmax(84px,auto)_minmax(0,1fr)] sm:items-center sm:gap-y-3 max-sm:[&>dd]:mb-2.5 max-sm:[&>dt]:text-xs">
          <dt className="text-muted-foreground">{t('tasks.field.status')}</dt>
          <dd className="min-w-0">
            <Segmented<TaskStatus>
              size="sm"
              value={task.status}
              onChange={(s) => void save({ status: s })}
              aria-label={t('tasks.field.status')}
              options={STATUSES.map((s) => ({ value: s, label: t(STATUS_KEY[s]) }))}
            />
          </dd>

          <dt className="text-muted-foreground">{t('tasks.field.priority')}</dt>
          <dd className="min-w-0">
            <Segmented<string>
              size="sm"
              value={String(task.priority)}
              onChange={(p) => void save({ priority: Number(p) as TaskPriority })}
              aria-label={t('tasks.field.priority')}
              options={[...PRIORITIES].reverse().map((p) => ({
                value: String(p),
                label: (
                  <>
                    {p > 0 && <PriorityIcon p={p} className="size-3.5 max-sm:hidden" />}
                    {t(PRIORITY_KEY[p])}
                  </>
                ),
              }))}
            />
          </dd>

          <dt className="text-muted-foreground">
            <label htmlFor="task-due">{t('tasks.field.due')}</label>
          </dt>
          <dd className="flex min-w-0 flex-wrap items-center gap-2">
            <Input
              id="task-due"
              type="date"
              value={task.due || ''}
              onChange={(e) => void save({ due: e.target.value || null })}
              className={cn('w-40', st === 'overdue' && 'border-destructive/60 text-destructive')}
            />
            {task.due !== today && (
              <Button variant="ghost" size="sm" onClick={() => void save({ due: today })}>
                {t('tasks.due.today')}
              </Button>
            )}
            {task.due !== addDays(today, 1) && (
              <Button variant="ghost" size="sm" onClick={() => void save({ due: addDays(today, 1) })}>
                {t('tasks.due.tomorrow')}
              </Button>
            )}
            {task.due && (
              <Button variant="ghost" size="icon-sm" onClick={() => void save({ due: null })} aria-label={t('tasks.clearDue')}>
                <X />
              </Button>
            )}
          </dd>

          <dt className="text-muted-foreground">{t('tasks.field.project')}</dt>
          <dd className="flex min-w-0 items-center gap-2">
            <Select
              value={task.project_id || '__none'}
              onValueChange={(v) => void save({ project_id: v === '__none' ? null : v })}
              aria-label={t('tasks.field.project')}
              className="max-w-64"
              options={[
                { value: '__none', label: t('tasks.noProject') },
                ...projects.map((p) => ({
                  value: p.id,
                  label: (
                    <span className="inline-flex items-center gap-2">
                      <ProjectDot color={p.color} />
                      <Sensitive length={6}>{p.name}</Sensitive>
                    </span>
                  ),
                })),
              ]}
            />
            <Button variant="ghost" size="icon-sm" onClick={onManageProjects} aria-label={t('tasks.manageProjects')} title={t('tasks.manageProjects')}>
              <Settings2 />
            </Button>
          </dd>

          <dt className="text-muted-foreground">{t('tasks.field.topic')}</dt>
          <dd className="grid min-w-0 gap-1.5">
            <Combobox
              value={task.topic_path || '__none'}
              onChange={(v) => void save({ topic_path: v === '__none' ? null : v })}
              options={topicKnown ? topicOptions : [...topicOptions, { value: task.topic_path!, label: mask(task.topic_path, 8) }]}
              placeholder={t('tasks.noTopic')}
              searchPlaceholder={t('tasks.searchTopic')}
              aria-label={t('tasks.field.topic')}
              className="max-w-80"
            />
            {task.topic_path && (
              <Link
                to={`/sessions?path=${encodeURIComponent(task.topic_path)}`}
                className="inline-flex w-fit items-center gap-1 text-[13px] font-medium text-primary underline-offset-4 hover:underline"
              >
                {t('tasks.openTopic')}
                <ArrowUpRight className="size-3.5" />
              </Link>
            )}
          </dd>

          <dt className="text-muted-foreground sm:self-start sm:pt-1">
            <label htmlFor="task-label">{t('tasks.field.labels')}</label>
          </dt>
          <dd className="grid min-w-0 gap-2">
            {task.labels.length > 0 && (
              <ul className="flex flex-wrap gap-1.5">
                {task.labels.map((l) => (
                  <li key={l}>
                    <LabelChip label={l} className="h-6 pr-0.5 text-xs">
                      <button
                        type="button"
                        onClick={() => void save({ labels: task.labels.filter((x) => x !== l) })}
                        aria-label={`${t('common.remove')} ${mask(l)}`}
                        className="relative flex size-4 items-center justify-center rounded-full before:absolute before:-inset-2.5 before:content-[''] hover:bg-accent hover:text-foreground"
                      >
                        <X className="size-3" />
                      </button>
                    </LabelChip>
                  </li>
                ))}
              </ul>
            )}
            <Input
              id="task-label"
              list="task-label-suggestions"
              value={labelDraft}
              onChange={(e) => {
                const v = e.target.value
                if (v.endsWith(',')) addLabel(v.slice(0, -1))
                else setLabelDraft(v)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  addLabel(labelDraft)
                }
              }}
              onBlur={() => labelDraft.trim() && addLabel(labelDraft)}
              placeholder={t('tasks.addLabel')}
              className="max-w-64"
            />
            <datalist id="task-label-suggestions">
              {known.map((l) => (
                <option key={l} value={presentation ? '' : l} />
              ))}
            </datalist>
          </dd>
        </dl>

        <div className="grid gap-2">
          <Tabs defaultValue={task.notes ? 'preview' : 'write'}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">{t('tasks.field.notes')}</span>
              <TabsList className="h-8 max-md:h-10">
                <TabsTrigger value="write" className="text-[13px]">
                  {t('tasks.notes.write')}
                </TabsTrigger>
                <TabsTrigger value="preview" className="text-[13px]">
                  {t('tasks.notes.preview')}
                </TabsTrigger>
              </TabsList>
            </div>
            <TabsContent value="write" className="mt-2">
              {presentation ? (
                <Sensitive block className="h-24">{null}</Sensitive>
              ) : (
                <Textarea
                  value={notes.value}
                  onChange={(e) => notes.onChange(e.target.value)}
                  onBlur={notes.flush}
                  minRows={6}
                  maxRows={22}
                  placeholder={t('tasks.notes.placeholder')}
                  aria-label={t('tasks.field.notes')}
                  className="font-mono text-[13px]"
                />
              )}
            </TabsContent>
            <TabsContent value="preview" className="mt-2">
              <div className="min-h-28 rounded-md border bg-muted/20 px-4 py-3">
                {notes.value.trim() ? (
                  <Sensitive block>
                    <React.Suspense fallback={<Skeleton className="h-16" />}>
                      <Markdown className="text-sm">{notes.value}</Markdown>
                    </React.Suspense>
                  </Sensitive>
                ) : (
                  <p className="text-sm text-muted-foreground">{t('tasks.notes.empty')}</p>
                )}
              </div>
            </TabsContent>
          </Tabs>
        </div>

        <div className="grid gap-1 border-t pt-4 text-xs text-muted-foreground">
          <span>
            {t('tasks.created')} <Sensitive length={8}>{fmtDate(task.created, lang, tz)}</Sensitive>
          </span>
          <span>
            {t('tasks.updated')} <Sensitive length={8}>{fmtDate(task.updated, lang, tz)}</Sensitive>
          </span>
          {task.done_at && (
            <span>
              {t('tasks.completed')} <Sensitive length={8}>{fmtDate(task.done_at, lang, tz)}</Sensitive>
            </span>
          )}
        </div>

        <div>
          <Button
            variant="outline"
            className="text-destructive hover:text-destructive"
            loading={del.isPending}
            onClick={async () => {
              const ok = await confirm({
                title: t('tasks.deleteTitle'),
                description: t('tasks.deleteDesc'),
                destructive: true,
                confirmText: t('common.delete'),
              })
              if (!ok) return
              onClose()
              del.mutate(task.id)
            }}
          >
            <Trash2 />
            {t('tasks.delete')}
          </Button>
        </div>
      </SheetBody>
    </>
  )
}
