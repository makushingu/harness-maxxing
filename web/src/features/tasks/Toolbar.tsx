// Search + filters (popover) + active filter chips, and the quick-add bar.
import * as React from 'react'
import { CalendarDays, Filter, Hash, Plus, Search, X } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { Badge, Button, Input, Kbd, Label, Popover, PopoverContent, PopoverTrigger, Select, Sensitive, Spinner, useMask } from '@/components/ui'
import type { TaskProject } from '@/lib/types'
import { EMPTY_FILTERS, PRIORITIES, PRIORITY_KEY, activeFilterCount, fmtDue, parseQuickAdd, type DueFilter, type QuickParse, type TaskFilters } from './model'
import { PriorityIcon, ProjectDot } from './parts'

export function FilterBar({
  filters,
  onChange,
  projects,
  labels,
  extra,
  withProject = true,
}: {
  filters: TaskFilters
  onChange: (f: TaskFilters) => void
  projects: TaskProject[]
  labels: string[]
  extra?: React.ReactNode
  /** Project filter in the popover (off when the page has its projects bar). */
  withProject?: boolean
}) {
  const t = useT()
  const mask = useMask()
  const n = activeFilterCount(withProject ? filters : { ...filters, project: 'all' })
  const set = (p: Partial<TaskFilters>) => onChange({ ...filters, ...p })
  const dueOpts: { value: DueFilter; label: string }[] = [
    { value: 'all', label: t('tasks.filter.anyDue') },
    { value: 'overdue', label: t('tasks.filter.overdue') },
    { value: 'today', label: t('tasks.filter.today') },
    { value: 'week', label: t('tasks.filter.week') },
    { value: 'none', label: t('tasks.filter.noDate') },
  ]
  const proj = projects.find((p) => p.id === filters.project)
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 basis-48 md:max-w-xs">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            value={filters.q}
            onChange={(e) => set({ q: e.target.value })}
            placeholder={t('tasks.searchPlaceholder')}
            aria-label={t('tasks.searchPlaceholder')}
            className="pl-9"
          />
        </div>
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" aria-label={t('tasks.filters')}>
              <Filter />
              <span className="max-sm:hidden">{t('tasks.filters')}</span>
              {n > 0 && (
                <Badge variant="default" className="h-5 min-w-5 justify-center rounded-full px-1 tabular-nums">
                  {n}
                </Badge>
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="grid w-72 gap-3 p-4">
            {withProject && (
            <div className="grid gap-1.5">
              <Label htmlFor="f-project">{t('tasks.field.project')}</Label>
              <Select
                id="f-project"
                value={filters.project}
                onValueChange={(v) => set({ project: v })}
                options={[
                  { value: 'all', label: t('tasks.filter.allProjects') },
                  { value: 'none', label: t('tasks.noProject') },
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
            </div>
            )}
            <div className="grid gap-1.5">
              <Label htmlFor="f-label">{t('tasks.field.labels')}</Label>
              <Select
                id="f-label"
                value={filters.label}
                onValueChange={(v) => set({ label: v })}
                options={[{ value: 'all', label: t('tasks.filter.anyLabel') }, ...labels.map((l) => ({ value: l, label: mask(l, 5) }))]}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="f-prio">{t('tasks.field.priority')}</Label>
              <Select
                id="f-prio"
                value={filters.priority}
                onValueChange={(v) => set({ priority: v })}
                options={[
                  { value: 'all', label: t('tasks.filter.anyPriority') },
                  ...PRIORITIES.map((p) => ({
                    value: String(p),
                    label: (
                      <span className="inline-flex items-center gap-2">
                        <PriorityIcon p={p} className="size-3.5" />
                        {t(PRIORITY_KEY[p])}
                      </span>
                    ),
                  })),
                ]}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="f-due">{t('tasks.field.due')}</Label>
              <Select id="f-due" value={filters.due} onValueChange={(v) => set({ due: v as DueFilter })} options={dueOpts} />
            </div>
            {n > 0 && (
              <Button variant="ghost" size="sm" onClick={() => onChange({ ...EMPTY_FILTERS, q: filters.q, project: withProject ? 'all' : filters.project })}>
                {t('tasks.clearFilters')}
              </Button>
            )}
          </PopoverContent>
        </Popover>
        {extra}
      </div>
      {n > 0 && (
        <div className="flex flex-wrap items-center gap-1.5" aria-label={t('tasks.activeFilters')}>
          {withProject && filters.project !== 'all' && (
            <FilterChip onClear={() => set({ project: 'all' })}>
              {proj ? (
                <>
                  <ProjectDot color={proj.color} className="size-2" />
                  <Sensitive length={5}>{proj.name}</Sensitive>
                </>
              ) : (
                t('tasks.noProject')
              )}
            </FilterChip>
          )}
          {filters.label !== 'all' && (
            <FilterChip onClear={() => set({ label: 'all' })}>
              <Hash className="size-3" />
              <Sensitive length={4}>{filters.label}</Sensitive>
            </FilterChip>
          )}
          {filters.priority !== 'all' && (
            <FilterChip onClear={() => set({ priority: 'all' })}>
              <PriorityIcon p={Number(filters.priority) as 0} className="size-3" />
              {t(PRIORITY_KEY[Number(filters.priority) as 0])}
            </FilterChip>
          )}
          {filters.due !== 'all' && (
            <FilterChip onClear={() => set({ due: 'all' })}>
              <CalendarDays className="size-3" />
              {dueOpts.find((o) => o.value === filters.due)?.label}
            </FilterChip>
          )}
        </div>
      )}
    </div>
  )
}

function FilterChip({ children, onClear }: { children: React.ReactNode; onClear: () => void }) {
  const t = useT()
  return (
    <span className="inline-flex h-7 items-center gap-1.5 rounded-full border bg-muted/40 pr-1 pl-2.5 text-xs font-medium">
      {children}
      <button type="button" onClick={onClear} aria-label={t('tasks.removeFilter')} className="flex size-5 items-center justify-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground">
        <X className="size-3" />
      </button>
    </span>
  )
}

export function QuickAdd({
  projects,
  today,
  onAdd,
  inputRef,
}: {
  projects: TaskProject[]
  today: string
  onAdd: (p: QuickParse) => Promise<unknown>
  inputRef?: React.Ref<HTMLInputElement>
}) {
  const t = useT()
  const lang = useLang()
  const [text, setText] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState('')
  const parsed = React.useMemo(() => parseQuickAdd(text, projects, today), [text, projects, today])
  const tokens = parsed.labels.length > 0 || parsed.priority != null || !!parsed.project_id || !!parsed.due
  return (
    <form
      className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1.5"
      onSubmit={async (e) => {
        e.preventDefault()
        if (busy || !text.trim()) return
        if (!parsed.title.trim()) {
          setError(t('tasks.titleRequired'))
          return
        }
        setBusy(true)
        try {
          await onAdd(parsed)
          setText('')
          setError('')
        } catch {
          /* toast already shown */
        } finally {
          setBusy(false)
        }
      }}
    >
      <div className="relative">
        <span className="pointer-events-none absolute top-1/2 left-3 flex -translate-y-1/2 text-muted-foreground">{busy ? <Spinner className="size-4" /> : <Plus className="size-4" />}</span>
        <Input
          ref={inputRef}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            if (error) setError('')
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setText('')
              e.currentTarget.blur()
            }
          }}
          placeholder={t('tasks.quickAddPlaceholder')}
          aria-label={t('tasks.quickAdd')}
          aria-invalid={!!error || undefined}
          aria-describedby="quick-add-hint"
          className="h-10 pr-12 pl-9 max-md:h-11"
          data-testid="quick-add"
        />
        <Kbd className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 max-md:hidden">N</Kbd>
      </div>
      <div id="quick-add-hint" className="flex min-h-5 min-w-0 flex-wrap items-center gap-x-3 gap-y-1 overflow-hidden px-1 text-xs text-muted-foreground" aria-live="polite">
        {error ? (
          <span className="text-destructive">{error}</span>
        ) : tokens ? (
          <>
            {parsed.priority != null && (
              <span className="inline-flex items-center gap-1">
                <PriorityIcon p={parsed.priority} className="size-3.5" />
                {t(PRIORITY_KEY[parsed.priority])}
              </span>
            )}
            {parsed.due && (
              <span className="inline-flex items-center gap-1">
                <CalendarDays className="size-3.5" />
                {fmtDue(parsed.due, today, lang, t)}
              </span>
            )}
            {parsed.projectName && (
              <span className="inline-flex items-center gap-1.5">
                <ProjectDot color={projects.find((p) => p.id === parsed.project_id)?.color} className="size-2" />
                <Sensitive length={5}>{parsed.projectName}</Sensitive>
              </span>
            )}
            {parsed.labels.map((l) => (
              <span key={l} className="inline-flex items-center gap-0.5">
                <Hash className="size-3" />
                <Sensitive length={4}>{l}</Sensitive>
              </span>
            ))}
          </>
        ) : (
          <span className="min-w-0 truncate">{t('tasks.quickAddHint')}</span>
        )}
      </div>
    </form>
  )
}
