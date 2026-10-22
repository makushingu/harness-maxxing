// Kanban board. Drag & drop is pointer-based (mouse, pen, touch):
// - mouse/pen: drag starts after a 5 px move;
// - touch: long-press (~250 ms) anywhere on a card, or immediately from the grip handle;
// - a placeholder shows the drop position, the page and the board auto-scroll near the edges;
// - drop → optimistic PATCH {status, order} (rolled back by usePatchTask on error).
import * as React from 'react'
import { createPortal } from 'react-dom'
import { ArrowRight, Check, FileText, GripVertical, MoreHorizontal, Plus, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT, type TFn } from '@/i18n'
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Input,
  Sensitive,
} from '@/components/ui'
import type { Task, TaskProject, TaskStatus } from '@/lib/types'
import { STATUSES, STATUS_KEY, byOrder } from './model'
import { DueBadge, LabelChip, PriorityIcon, ProjectChip } from './parts'
import { TopicChip } from './List'
import { isSelectClick, useTaskSelection } from './selection'

/** One column of the board: its cards (already sorted) and what a drop / an add does there. */
export type BoardColumn = {
  id: string
  label: string
  /** Small marker before the title (status pip, coloured dot...). */
  pip?: React.ReactNode
  /** Secondary text after the count (a date...). */
  sub?: string
  tasks: Task[]
  /** Cards can be dropped here (default true). */
  droppable?: boolean
  /** "Add a card" at the bottom of the column. */
  onAdd?: (text: string) => Promise<unknown>
  /** Show the first `page` cards, then "Show more" (default: all). */
  page?: number
  tone?: 'danger'
}

type Props = {
  columns: BoardColumn[]
  projects: TaskProject[]
  today: string
  /** grid: columns share the width on desktop (status board); scroll: fixed-width columns scrolled sideways (week). */
  layout?: 'grid' | 'scroll'
  /** Hide the project chip on cards (the page already shows one project). */
  hideProject?: boolean
  onOpen: (id: string) => void
  /** A card dropped in `column` between `prev` and `next` (the cards around the drop slot). */
  onDrop: (task: Task, column: string, prev?: Task, next?: Task) => void
  onMoveStatus: (task: Task, status: TaskStatus) => void
  onDelete: (task: Task) => void
  /** A selected card dragged to another column takes the whole selection with it. */
  onBulkDrop?: (ids: string[], column: string) => void
  testId?: string
}

type Drag = { id: string; w: number; h: number; ox: number; oy: number; from: string }
type Target = { col: string; index: number }

/** The classic three status columns. */
export function statusColumns(tasks: Task[], t: TFn, onAdd?: (status: TaskStatus, text: string) => Promise<unknown>): BoardColumn[] {
  const m: Record<TaskStatus, Task[]> = { todo: [], doing: [], done: [] }
  for (const x of tasks) m[x.status].push(x)
  return STATUSES.map((s) => ({
    id: s,
    label: t(STATUS_KEY[s]),
    pip: <StatusPip status={s} />,
    tasks: m[s].sort(byOrder),
    onAdd: s !== 'done' && onAdd ? (text: string) => onAdd(s, text) : undefined,
    page: s === 'done' ? DONE_PAGE : undefined,
  }))
}
const DONE_PAGE = 30

export function TaskBoard({ columns, projects, today, layout = 'grid', hideProject, onOpen, onDrop, onMoveStatus, onDelete, onBulkDrop, testId = 'task-board' }: Props) {
  const t = useT()
  const projById = React.useMemo(() => new Map(projects.map((p) => [p.id, p])), [projects])
  const byId = React.useMemo(() => new Map(columns.map((c) => [c.id, c])), [columns])
  const [limits, setLimits] = React.useState<Record<string, number>>({})
  const selected = useTaskSelection((s) => s.ids)
  const selecting = selected.size > 0

  // ---- drag state
  const [drag, setDrag] = React.useState<Drag | null>(null)
  const [target, setTarget] = React.useState<Target | null>(null)
  const targetRef = React.useRef<Target | null>(null)
  const pos = React.useRef({ x: 0, y: 0 })
  const overlay = React.useRef<HTMLDivElement | null>(null)
  const colEls = React.useRef(new Map<string, HTMLElement>())
  const cardEls = React.useRef(new Map<string, HTMLElement>())
  const scroller = React.useRef<HTMLDivElement | null>(null)
  const suppressClick = React.useRef(false)
  const columnsRef = React.useRef(byId)
  columnsRef.current = byId

  const computeTarget = React.useCallback((dragId: string) => {
    const { x, y } = pos.current
    let col: string | null = null
    let best = Infinity
    for (const [id, c] of columnsRef.current) {
      if (c.droppable === false) continue
      const el = colEls.current.get(id)
      if (!el) continue
      const r = el.getBoundingClientRect()
      const d = x < r.left ? r.left - x : x > r.right ? x - r.right : 0
      if (d < best) {
        best = d
        col = id
      }
    }
    if (!col) return
    let index = 0
    for (const c of columnsRef.current.get(col)!.tasks) {
      if (c.id === dragId) continue
      const el = cardEls.current.get(c.id)
      if (!el) break
      const r = el.getBoundingClientRect()
      if (y > r.top + r.height / 2) index++
      else break
    }
    const cur = targetRef.current
    if (!cur || cur.col !== col || cur.index !== index) {
      targetRef.current = { col, index }
      setTarget(targetRef.current)
    }
  }, [])

  const placeOverlay = (d: Drag) => {
    const el = overlay.current
    if (el) el.style.transform = `translate3d(${pos.current.x - d.ox}px, ${pos.current.y - d.oy}px, 0) rotate(1.5deg)`
  }

  // auto-scroll while dragging
  React.useEffect(() => {
    if (!drag) return
    let raf = 0
    const tick = () => {
      const { x, y } = pos.current
      const main = document.getElementById('main')
      const edge = 64
      if (main) {
        const r = main.getBoundingClientRect()
        const bottom = Math.min(r.bottom, window.innerHeight)
        if (y < r.top + edge) main.scrollTop -= Math.ceil((r.top + edge - y) / 6)
        else if (y > bottom - edge) main.scrollTop += Math.ceil((y - (bottom - edge)) / 6)
      }
      const sc = scroller.current
      if (sc && sc.scrollWidth > sc.clientWidth) {
        const r = sc.getBoundingClientRect()
        if (x < r.left + 40) sc.scrollLeft -= 12
        else if (x > r.right - 40) sc.scrollLeft += 12
      }
      computeTarget(drag.id)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [drag, computeTarget])

  const onPointerDown = (e: React.PointerEvent<HTMLElement>, task: Task, from: string) => {
    if (e.button !== 0 || drag) return
    const tgt = e.target as HTMLElement
    const handle = !!tgt.closest('[data-drag-handle]')
    if (!handle && tgt.closest('button, a, input, textarea, [role="menuitem"]')) return
    const card = e.currentTarget
    const start = { x: e.clientX, y: e.clientY }
    pos.current = start
    const touch = e.pointerType === 'touch'
    let started = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let current: Drag | null = null

    const preventScroll = (ev: TouchEvent) => {
      if (started) ev.preventDefault()
    }
    const begin = () => {
      if (started) return
      started = true
      const r = card.getBoundingClientRect()
      current = { id: task.id, w: r.width, h: r.height, ox: start.x - r.left, oy: start.y - r.top, from }
      targetRef.current = null
      setDrag(current)
      computeTarget(task.id)
      document.body.style.userSelect = 'none'
      if (touch) navigator.vibrate?.(8)
    }
    const move = (ev: PointerEvent) => {
      pos.current = { x: ev.clientX, y: ev.clientY }
      if (!started) {
        const dist = Math.hypot(ev.clientX - start.x, ev.clientY - start.y)
        if (touch && !handle) {
          if (dist > 8) cleanup() // the user is scrolling
        } else if (dist > 5) begin()
        return
      }
      if (current) placeOverlay(current)
    }
    const finish = (drop: boolean) => {
      const tg = targetRef.current
      const d = current
      cleanup()
      if (!d) return
      suppressClick.current = true
      setTimeout(() => (suppressClick.current = false), 50)
      setDrag(null)
      setTarget(null)
      targetRef.current = null
      if (!drop || !tg) return
      const sel = useTaskSelection.getState().ids
      if (onBulkDrop && sel.has(d.id) && sel.size > 1 && tg.col !== d.from) {
        onBulkDrop([...sel], tg.col)
        return
      }
      const list = (columnsRef.current.get(tg.col)?.tasks ?? []).filter((c) => c.id !== d.id)
      const prev = list[tg.index - 1]
      const next = list[tg.index]
      const orig = columnsRef.current.get(d.from)?.tasks ?? []
      const oi = orig.findIndex((c) => c.id === d.id)
      if (tg.col === d.from && orig[oi - 1]?.id === prev?.id && orig[oi + 1]?.id === next?.id) return // unchanged
      const dragged = orig[oi]
      if (dragged) onDrop(dragged, tg.col, prev, next)
    }
    const up = () => finish(true)
    const cancel = () => finish(false)
    const key = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') finish(false)
    }
    function cleanup() {
      clearTimeout(timer)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', cancel)
      window.removeEventListener('keydown', key)
      document.removeEventListener('touchmove', preventScroll)
      document.body.style.userSelect = ''
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', cancel)
    window.addEventListener('keydown', key)
    document.addEventListener('touchmove', preventScroll, { passive: false })
    if (touch && !handle) timer = setTimeout(begin, 260)
    else if (handle) {
      e.preventDefault()
    }
  }

  React.useLayoutEffect(() => {
    if (drag) placeOverlay(drag)
  }, [drag])

  const dragged = drag ? columns.flatMap((c) => c.tasks).find((x) => x.id === drag.id) : undefined
  const grid = layout === 'grid'

  return (
    <>
      <div
        ref={scroller}
        className={cn(
          '-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-2',
          grid ? 'md:mx-0 md:grid md:snap-none md:grid-cols-[repeat(var(--cols),minmax(0,1fr))] md:gap-4 md:overflow-visible md:px-0' : 'md:mx-0 md:snap-none md:px-0',
        )}
        style={grid ? ({ '--cols': columns.length } as React.CSSProperties) : undefined}
        data-testid={testId}
      >
        {columns.map((col) => {
          const all = col.tasks
          const limit = col.page ? Math.max(limits[col.id] ?? col.page, target?.col === col.id ? target.index + 1 : 0) : Infinity
          const list = all.slice(0, limit)
          const hidden = all.length - list.length
          return (
            <section
              key={col.id}
              aria-label={col.label}
              data-column={col.id}
              className={cn(
                'flex w-[84vw] max-w-[360px] shrink-0 snap-start flex-col rounded-xl border bg-muted/25',
                grid ? 'md:w-auto md:max-w-none' : 'md:w-64',
                col.tone === 'danger' && all.length > 0 && 'border-destructive/30',
                drag && col.droppable === false && 'opacity-60',
              )}
            >
              <header className="group/col flex h-11 items-center gap-2 px-3">
                {col.pip}
                <h2 className={cn('truncate text-[13px] font-semibold', col.tone === 'danger' && all.length > 0 && 'text-destructive')}>{col.label}</h2>
                <span className="text-xs text-muted-foreground tabular-nums">{all.length}</span>
                {col.sub && <span className="truncate text-xs text-muted-foreground">{col.sub}</span>}
                {list.length > 0 && <ColumnSelect ids={list.map((x) => x.id)} selected={selected} visible={selecting} label={t('tasks.bulk.selectColumn')} />}
              </header>
              <div
                ref={(el) => {
                  if (el) colEls.current.set(col.id, el)
                  else colEls.current.delete(col.id)
                }}
                className={cn('flex min-h-24 flex-1 flex-col gap-2 px-2 pb-2', drag && 'pb-6')}
              >
                {list.map((task, i) => {
                  const isDragged = drag?.id === task.id
                  const indexAmongOthers = drag ? list.slice(0, i).filter((c) => c.id !== drag.id).length : i
                  return (
                    <React.Fragment key={task.id}>
                      {target && target.col === col.id && target.index === indexAmongOthers && !isDragged && <DropSlot h={drag!.h} />}
                      <TaskCard
                        ref={(el) => {
                          if (el) cardEls.current.set(task.id, el)
                          else cardEls.current.delete(task.id)
                        }}
                        task={task}
                        project={!hideProject && task.project_id ? projById.get(task.project_id) : undefined}
                        today={today}
                        hidden={isDragged}
                        selected={selected.has(task.id)}
                        selecting={selecting}
                        onSelect={() => useTaskSelection.getState().toggle(task.id)}
                        onPointerDown={(e) => onPointerDown(e, task, col.id)}
                        onOpen={(e) => {
                          if (suppressClick.current) return
                          if (e && isSelectClick(e)) useTaskSelection.getState().toggle(task.id)
                          else onOpen(task.id)
                        }}
                        onMoveTo={(s) => onMoveStatus(task, s)}
                        onDelete={() => onDelete(task)}
                      />
                    </React.Fragment>
                  )
                })}
                {target && target.col === col.id && target.index >= list.filter((c) => c.id !== drag?.id).length && <DropSlot h={drag!.h} />}
                {hidden > 0 && (
                  <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => setLimits((m) => ({ ...m, [col.id]: (m[col.id] ?? col.page ?? 0) + (col.page ?? DONE_PAGE) }))}>
                    {t('tasks.showMore', { count: hidden })}
                  </Button>
                )}
                {col.onAdd && !drag && <ColumnAdd onAdd={col.onAdd} />}
              </div>
            </section>
          )
        })}
      </div>
      {drag &&
        dragged &&
        createPortal(
          <div ref={overlay} className="pointer-events-none fixed top-0 left-0 z-[70] will-change-transform" style={{ width: drag.w }}>
            <TaskCard task={dragged} project={!hideProject && dragged.project_id ? projById.get(dragged.project_id) : undefined} today={today} lifted />
            {selected.has(dragged.id) && selected.size > 1 && (
              <span className="absolute -top-2 -right-2 inline-flex h-6 min-w-6 items-center justify-center rounded-full bg-primary px-1.5 text-xs font-semibold text-primary-foreground shadow-pop">
                {selected.size}
              </span>
            )}
          </div>,
          document.body,
        )}
    </>
  )
}

function ColumnSelect({ ids, selected, visible, label }: { ids: string[]; selected: Set<string>; visible: boolean; label: string }) {
  const all = ids.every((id) => selected.has(id))
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={all ? true : ids.some((id) => selected.has(id)) ? 'mixed' : false}
      aria-label={label}
      title={label}
      onClick={() => (all ? useTaskSelection.getState().remove(ids) : useTaskSelection.getState().add(ids))}
      className="group/dot relative ml-auto flex size-5 shrink-0 items-center justify-center rounded-full outline-none before:absolute before:-inset-2.5 before:content-[''] pointer-coarse:-my-2.5 pointer-coarse:-mr-2.5 pointer-coarse:size-10 pointer-coarse:before:content-none"
    >
      <span
        className={cn(
          'flex size-5 items-center justify-center rounded-full border text-primary-foreground transition-opacity group-focus-visible/dot:opacity-100 group-focus-visible/dot:ring-2 group-focus-visible/dot:ring-ring',
          all ? 'border-primary bg-primary' : 'border-muted-foreground/40 bg-card',
          !visible && 'opacity-0 group-hover/col:opacity-100 max-md:opacity-100 pointer-coarse:opacity-100',
        )}
      >
        {all && <Check className="size-3" strokeWidth={3} />}
      </span>
    </button>
  )
}

function DropSlot({ h }: { h: number }) {
  return <div aria-hidden className="shrink-0 rounded-lg border-2 border-dashed border-primary/50 bg-primary/5" style={{ height: h }} />
}

export function StatusPip({ status }: { status: TaskStatus }) {
  return (
    <span
      aria-hidden
      className={cn(
        'inline-block size-2.5 shrink-0 rounded-full border-2',
        status === 'todo' && 'border-muted-foreground/60',
        status === 'doing' && 'border-primary bg-primary/30',
        status === 'done' && 'border-success bg-success',
      )}
    />
  )
}

type CardProps = {
  task: Task
  project?: TaskProject
  today: string
  hidden?: boolean
  lifted?: boolean
  ref?: React.Ref<HTMLDivElement>
  selected?: boolean
  selecting?: boolean
  onSelect?: () => void
  onPointerDown?: (e: React.PointerEvent<HTMLDivElement>) => void
  onOpen?: (e?: React.MouseEvent | React.KeyboardEvent) => void
  onMoveTo?: (s: TaskStatus) => void
  onDelete?: () => void
}

function TaskCard({ task, project, today, hidden, lifted, ref, selected, selecting, onSelect, onPointerDown, onOpen, onMoveTo, onDelete }: CardProps) {
  const t = useT()
  const done = task.status === 'done'
  const overdue = !done && !!task.due && task.due < today
  return (
    <div
      ref={ref}
      role={lifted ? undefined : 'button'}
      tabIndex={lifted ? undefined : 0}
      data-task-id={task.id}
      aria-pressed={onSelect ? !!selected : undefined}
      onPointerDown={onPointerDown}
      onClick={(e) => onOpen?.(e)}
      onKeyDown={(e) => {
        if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) {
          e.preventDefault()
          onOpen?.(e)
        }
      }}
      onContextMenu={(e) => {
        if ((e.nativeEvent as PointerEvent).pointerType === 'touch') e.preventDefault()
      }}
      className={cn(
        'group relative grid cursor-pointer gap-2 rounded-lg border bg-card p-3 text-left shadow-xs transition-[border-color,box-shadow] outline-none select-none [-webkit-touch-callout:none]',
        'hover:border-foreground/20 focus-visible:ring-2 focus-visible:ring-ring',
        overdue && 'border-destructive/40',
        hidden && 'hidden',
        lifted && 'cursor-grabbing border-primary/50 shadow-pop ring-1 ring-primary/30',
        selected && 'border-primary/60 bg-primary/5 ring-2 ring-primary/40',
      )}
    >
      {onSelect && !lifted && (
        <button
          type="button"
          role="checkbox"
          aria-checked={!!selected}
          aria-label={task.title}
          onClick={(e) => {
            e.stopPropagation()
            onSelect()
          }}
          className="group/dot absolute -top-2 -left-2 z-10 flex size-5 items-center justify-center rounded-full outline-none pointer-coarse:-top-4 pointer-coarse:-left-4 pointer-coarse:size-10"
        >
          <span
            className={cn(
              'flex size-5 items-center justify-center rounded-full border shadow-xs transition-opacity group-focus-visible/dot:opacity-100 group-focus-visible/dot:ring-2 group-focus-visible/dot:ring-ring max-md:size-6',
              selected ? 'border-primary bg-primary text-primary-foreground' : 'border-muted-foreground/40 bg-card',
              !selected && !selecting && 'opacity-0 group-hover:opacity-100 pointer-coarse:opacity-100',
            )}
          >
            {selected && <Check className="size-3" strokeWidth={3} />}
          </span>
        </button>
      )}
      <div className="flex items-start gap-2">
        <span
          data-drag-handle
          aria-hidden
          className="-my-1 -ml-1.5 flex h-6 w-5 shrink-0 cursor-grab touch-none items-center justify-center rounded text-muted-foreground/50 hover:text-muted-foreground max-md:h-8 max-md:w-6"
        >
          <GripVertical className="size-3.5" />
        </span>
        <p className={cn('line-clamp-3 min-w-0 flex-1 text-sm leading-snug font-medium break-words', done && 'text-muted-foreground line-through decoration-muted-foreground/40')}>
          <Sensitive length={10}>{task.title}</Sensitive>
        </p>
        {!lifted && onMoveTo && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={t('common.more')}
                onClick={(e) => e.stopPropagation()}
                className="-my-1 -mr-1.5 flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground opacity-0 transition group-hover:opacity-100 hover:bg-accent hover:text-foreground focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none data-[state=open]:opacity-100 max-md:-my-2.5 max-md:-mr-2.5 max-md:size-10 max-md:opacity-100 pointer-coarse:-my-2.5 pointer-coarse:-mr-2.5 pointer-coarse:size-10 pointer-coarse:opacity-100"
              >
                <MoreHorizontal className="size-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
              <DropdownMenuLabel>{t('tasks.moveTo')}</DropdownMenuLabel>
              {STATUSES.filter((s) => s !== task.status).map((s) => (
                <DropdownMenuItem key={s} onSelect={() => onMoveTo(s)}>
                  <ArrowRight />
                  {t(STATUS_KEY[s])}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              <DropdownMenuItem destructive onSelect={() => onDelete?.()}>
                <Trash2 />
                {t('common.delete')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      <CardMeta task={task} project={project} today={today} />
    </div>
  )
}

function CardMeta({ task, project, today }: { task: Task; project?: TaskProject; today: string }) {
  const t = useT()
  const hasAny = task.priority > 0 || task.due || project || task.labels.length || task.topic_path || task.notes
  if (!hasAny) return null
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5 pl-5">
      {task.priority > 0 && <PriorityIcon p={task.priority} className="size-3.5" />}
      <DueBadge task={task} today={today} />
      {project && <ProjectChip project={project} className="max-w-[45%]" />}
      {task.labels.slice(0, 3).map((l) => (
        <LabelChip key={l} label={l} />
      ))}
      {task.labels.length > 3 && <span className="text-[11px] text-muted-foreground">+{task.labels.length - 3}</span>}
      <span className="ml-auto flex items-center gap-1.5 text-muted-foreground">
        {task.notes && <FileText className="size-3.5" aria-label={t('tasks.hasNotes')} role="img" />}
        {task.topic_path && <TopicChip path={task.topic_path} />}
      </span>
    </div>
  )
}

function ColumnAdd({ onAdd }: { onAdd: (text: string) => Promise<unknown> }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const [text, setText] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  if (!open)
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex h-9 items-center gap-2 rounded-lg px-2 text-[13px] text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none max-md:h-11"
      >
        <Plus className="size-4" />
        {t('tasks.addCard')}
      </button>
    )
  return (
    <form
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
      <Input
        autoFocus
        value={text}
        disabled={busy}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => !text.trim() && setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setText('')
            setOpen(false)
          }
        }}
        placeholder={t('tasks.quickAddPlaceholder')}
        aria-label={t('tasks.addCard')}
      />
    </form>
  )
}
