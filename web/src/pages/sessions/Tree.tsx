// Left pane: project → topic → sessions, with live badges, search filter, folding (persisted),
// per-topic "+", context menus (rename / delete / new topic…) and an archived fold per topic.
// Grouped by project (tree or drill-down, one level at a time) or by session (sessions only, most used first, each
// labelled project › topic); optional Favorites / Recent blocks on top. The header is the same on a computer and
// on a phone: filter field, All / Running / Unread chips, one view menu holding every display choice.
import * as React from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useNavigate } from 'react-router'
import {
  Archive,
  ArrowDownAZ,
  CalendarClock,
  Flame,
  ChevronLeft,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  Clock,
  Columns3,
  FolderOpen,
  FolderPlus,
  Hash,
  List,
  ListTree,
  MoreHorizontal,
  PanelLeftClose,
  Pencil,
  Plus,
  Search,
  ShieldAlert,
  ShieldCheck,
  ShieldHalf,
  SlidersHorizontal,
  Smile,
  SquarePen,
  Star,
  StarOff,
  Trash2,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLongPress } from '@/lib/long-press'
import { useCompact } from '@/stores/media'
import { animateIn, animateOut, PRESENCE_MS, useFlip, usePresence } from '@/lib/presence'
import { useT, useLang } from '@/i18n'
import { fmtRelative } from '@/lib/format'
import { isApiError, errorMessage } from '@/lib/api'
import { slugify, SLUG_RE } from '@/lib/utils'
import {
  useClaudeStatus,
  useCreateProject,
  useCreateTopic,
  useDeleteProject,
  useDeleteSession,
  useDeleteTopic,
  usePatchProject,
  usePatchSession,
  usePatchTopic,
  useSessions,
  useReorderProjects,
  useReorderTopics,
  useWorkspace,
} from '@/lib/queries'
import type { PermissionMode, Project, Session, Topic } from '@/lib/types'
import { OptionCard } from '@/features/common'
import {
  Button,
  confirm,
  CountBadge,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  FormField,
  Input,
  Sensitive,
  Skeleton,
  StatusDot,
  toast,
  Tooltip,
  useMask,
} from '@/components/ui'
import { SlugPreview } from '@/features/workspace/CreateProjectTopic'
import { forgetLog } from './log'
import { FLAT_SORTS, RECENT_COUNTS, saveDraft, saveQuotes, TREE_MODES, useSessionsUI, type FlatSort, type ListBy, type TreeMode } from './store'
import { absTopicDir, modelLabel, topicLabel } from './util'

const SESSIONS_SHOWN = 8
const FLAT_SHOWN = 60
/** "Open all" of a badge filter opens at most this many columns. */
const SHOW_OPEN_MAX = 6

/** True during the first ~0.9 s after the tree data arrives: nodes mounted then rise in; nodes mounted later
 *  (a folder being opened) only unfold, so nothing animates twice. */
const TreeIntro = React.createContext(false)
/** Set once the tree intro has played in this tab (see SessionTree). */
let introPlayed = false

type Props = {
  onOpenSession: (s: Session) => void
  onNewSession: (path: string) => void
  /** Topic highlighted (focused column / ?path=). */
  activePath: string | null
  /** Session ids open in columns. */
  openIds: Set<string>
  focusedId: string | null
  /** Fold the tree (desktop): the button sits next to "New project". */
  onHide?: () => void
  /** Touch layout drawer: bigger header with New session next to the filter; the row menus open with a long press. */
  touch?: boolean
  className?: string
}

export function SessionTree({ onOpenSession, onNewSession, activePath, openIds, focusedId, onHide, touch, className }: Props) {
  const t = useT()
  const ws = useWorkspace()
  const reorderProjects = useReorderProjects()
  const reorderTopics = useReorderTopics()
  const live = useSessions(undefined, false)
  const [q, setQ] = React.useState('')
  const [dialog, setDialog] = React.useState<DialogState>(null)

  const ql = q.trim().toLowerCase()
  // The archived sessions (most of them on a server used for a while) load only when an archived fold is open or a
  // search looks into them; the folds show their count from the tree (topic.archived_count) meanwhile.
  const archOpen = useSessionsUI((s) => Object.entries(s.expanded).some(([k, v]) => v && k.startsWith('a:')))
  const archived = useSessions(undefined, true, archOpen || !!ql)
  const byPath = React.useMemo(() => group(live.data), [live.data])
  const archivedByPath = React.useMemo(() => group(archived.data), [archived.data])
  // A badge was clicked (running / finished): only those sessions, unfolded. Typing a search leaves it.
  const show = useSessionsUI((s) => (ql ? null : s.show))
  const setShow = useSessionsUI((s) => s.setShow)
  const shows = React.useCallback((s: Session) => (show === 'running' ? s.state === 'running' : !!s.unread), [show])
  const narrowed = !!ql || !!show
  // A new filter unfolds everything again.
  const setNarrowFolded = useSessionsUI((s) => s.setNarrowFolded)
  React.useEffect(() => setNarrowFolded({}), [ql, show, setNarrowFolded])

  // The rows rise in on the first visit only (coming back to the page shows them at once).
  const [intro, setIntro] = React.useState(!introPlayed)
  const loaded = !ws.isPending && !live.isPending
  const listBy = useSessionsUI((s) => s.listBy)
  // Switching Projects <-> Sessions replays the intro: the new view's rows rise in, staggered.
  const [shownBy, setShownBy] = React.useState(listBy)
  if (shownBy !== listBy) {
    setShownBy(listBy)
    setIntro(true)
  }
  React.useEffect(() => {
    if (!loaded) return
    introPlayed = true
    const id = setTimeout(() => setIntro(false), 900)
    return () => clearTimeout(id)
  }, [loaded, listBy])

  const projects = ws.data?.projects || []
  const mode = useSessionsUI((s) => s.treeMode)
  const expanded = useSessionsUI((s) => s.expanded)
  const setExpanded = useSessionsUI((s) => s.setExpanded)
  // Something is open (a project is unfolded by default) -> the footer button folds everything;
  // only when everything is folded does it offer to unfold everything.
  const anyFolded = !projects.some((p) => expanded[`p:${p.name}`] !== false)
  const foldAll = (open: boolean) => {
    const nodes: Record<string, boolean> = {}
    for (const p of projects) {
      nodes[`p:${p.name}`] = open
      for (const tp of p.topics || []) nodes[`t:${tp.path}`] = open
    }
    setExpanded(nodes)
  }
  const rootSessions = (byPath.get('') || []).filter((s) => !show || shows(s))
  const shown = React.useMemo(() => (show ? (live.data || []).filter(shows).sort((a, b) => b.updated - a.updated) : []), [show, shows, live.data])
  /** "acme › blog", with the project's emoji in front when it has one (Favorites, Recent, flat layout). */
  const emojiOf = React.useMemo(() => new Map(projects.map((p) => [p.name, p.emoji || ''])), [projects])
  const rootLabel = t('sessions.root')
  /** Touch layout: New session goes to the topic of the session on screen, else the first topic. */
  const newHere = activePath ?? projects.find((p) => p.topics.length)?.topics[0]?.path ?? null
  const labelOf = React.useCallback(
    (s: Session) => {
      const m = /^projects\/([^/]+)/.exec(s.path)
      const e = m ? emojiOf.get(m[1]) : ''
      const label = topicLabel(s.path, rootLabel, ' › ')
      return e ? `${e} ${label}` : label
    },
    [emojiOf, rootLabel],
  )

  const matches = (s: string) => !ql || s.toLowerCase().includes(ql)
  const filtered = React.useMemo(() => {
    if (show && !ql) {
      const out: { p: Project; topics: { tp: Topic; sessions: Session[] }[] }[] = []
      for (const p of projects) {
        const topics = p.topics.map((tp) => ({ tp, sessions: (byPath.get(tp.path) || []).filter(shows) })).filter((x) => x.sessions.length)
        if (topics.length) out.push({ p, topics })
      }
      return out
    }
    if (!ql) return projects.map((p) => ({ p, topics: p.topics.map((tp) => ({ tp, sessions: byPath.get(tp.path) || [] })) }))
    const out: { p: Project; topics: { tp: Topic; sessions: Session[] }[] }[] = []
    for (const p of projects) {
      const pm = matches(p.name) || matches(p.description)
      const topics = []
      for (const tp of p.topics) {
        const tm = pm || matches(tp.name) || matches(tp.description)
        const ss = (byPath.get(tp.path) || []).concat(archivedByPath.get(tp.path) || []).filter((s) => matches(s.title) || matches(s.last_text))
        if (tm || ss.length) topics.push({ tp, sessions: tm && !ss.length ? byPath.get(tp.path) || [] : ss })
      }
      if (pm || topics.length) out.push({ p, topics })
    }
    return out
  }, [projects, byPath, archivedByPath, ql, show, shows]) // eslint-disable-line react-hooks/exhaustive-deps

  const header = (
    <ListHeader
      touch={touch}
      q={q}
      onQ={(v) => {
        setQ(v)
        if (v && useSessionsUI.getState().show) setShow(null)
      }}
      show={show}
      onShow={setShow}
      sessions={live.data || []}
      onNew={touch ? (newHere === null ? undefined : () => onNewSession(newHere)) : undefined}
      onHide={onHide}
      menu={
        projects.length > 0 && (
          <ViewMenu
            fold={!ql && !show && listBy === 'project' && mode === 'tree' ? { anyFolded, onFold: () => foldAll(anyFolded) } : null}
            onNewProject={() => setDialog({ kind: 'project' })}
          />
        )
      }
    />
  )

  return (
    <nav aria-label={t('sessions.tree.label')} data-tour="tree" className={cn('flex min-h-0 flex-col', className)}>
      {header}
      {show && !touch && shown.length > 1 && (
        <div className="mx-2 mb-1 flex shrink-0 items-center gap-1.5 px-1 text-xs text-muted-foreground animate-in" role="status">
          <span className="tabular-nums">{t('sessions.tree.shownCount', { count: shown.length })}</span>
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto h-6 px-1.5 text-xs"
            onClick={() => {
              // Oldest first: the most recent ends up focused; the columns already open stay.
              for (const s of shown.slice(0, SHOW_OPEN_MAX).reverse()) onOpenSession(s)
            }}
          >
            {t('sessions.tree.showOpenAll')}
          </Button>
        </div>
      )}
      <TreeIntro.Provider value={intro}>
      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-4" role="tree">
        {ws.isPending || live.isPending ? (
          <TreeSkeleton />
        ) : ws.isError ? (
          <EmptyState compact tone="error" title={t('sessions.tree.error')} description={errorMessage(ws.error)} action={<Button size="sm" variant="outline" onClick={() => ws.refetch()}>{t('common.retry')}</Button>} />
        ) : projects.length === 0 ? (
          <EmptyState
            compact
            icon={FolderPlus}
            title={t('sessions.tree.emptyTitle')}
            description={t('sessions.tree.emptyDesc')}
            action={
              <Button size="sm" onClick={() => setDialog({ kind: 'project' })}>
                <FolderPlus /> {t('sessions.tree.newProject')}
              </Button>
            }
          />
        ) : (
          <>
            {!ql && !show && <TopBlocks sessions={live.data || []} openIds={openIds} focusedId={focusedId} onOpen={onOpenSession} labelOf={labelOf} />}
            {listBy === 'session' && !show ? (
              <FlatView
                sessions={ql ? (live.data || []).concat(archived.data || []).filter((s) => matches(s.title) || matches(s.last_text) || matches(s.path)) : live.data || []}
                searching={!!ql}
                openIds={openIds}
                focusedId={focusedId}
                onOpen={onOpenSession}
                labelOf={labelOf}
              />
            ) : mode === 'drill' && !ql && !show ? (
              <DrillView
                projects={projects}
                byPath={byPath}
                archivedByPath={archivedByPath}
                rootSessions={rootSessions}
                openIds={openIds}
                focusedId={focusedId}
                onOpenSession={onOpenSession}
                onNewSession={onNewSession}
                onDialog={setDialog}
                rootDirOf={(path) => absTopicDir(ws.data, path)}
              />
            ) : (
          <>
            {filtered.length === 0 && rootSessions.length === 0 && (
              <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                {show ? t(show === 'running' ? 'sessions.tree.noneRunning' : 'sessions.tree.noneUnread') : t('common.noResults')}
              </p>
            )}
            {filtered.map(({ p, topics }, pi) => (
              <ProjectNode
                key={p.name}
                project={p}
                forceOpen={narrowed}
                onDialog={setDialog}
                stagger={Math.min(pi * 2, 10)}
                onMove={narrowed ? undefined : (dragged, before) => reorderProjects.mutate(moveName(projects.map((x) => x.name), dragged, p.name, before))}
              >
                {topics.map(({ tp, sessions }, ti) => (
                  <TopicNode
                    key={tp.path}
                    stagger={Math.min(pi * 2 + ti + 1, 10)}
                    topic={tp}
                    sessions={sessions}
                    archived={narrowed ? [] : archivedByPath.get(tp.path) || []}
                    forceOpen={narrowed}
                    active={activePath === tp.path}
                    openIds={openIds}
                    focusedId={focusedId}
                    onOpenSession={onOpenSession}
                    onNewSession={onNewSession}
                    onDialog={setDialog}
                    rootDir={absTopicDir(ws.data, tp.path)}
                    onMove={narrowed ? undefined : (dragged, before) => reorderTopics.mutate({ project: p.name, names: moveName(p.topics.map((x) => x.name), dragged, tp.name, before) })}
                  />
                ))}
                {topics.length === 0 && !narrowed && (
                  <button type="button" onClick={() => setDialog({ kind: 'topic', project: p.name })} className="ml-6 flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">
                    <Plus className="size-3.5" /> {t('sessions.tree.newTopic')}
                  </button>
                )}
              </ProjectNode>
            ))}
            {rootSessions.length > 0 && !ql && (
              <div className="mt-2 border-t pt-2">
                <div className="flex h-8 items-center gap-1.5 px-2 text-xs font-medium text-muted-foreground">
                  <FolderOpen className="size-3.5" /> {t('sessions.root')}
                </div>
                <SessionRows sessions={rootSessions} openIds={openIds} focusedId={focusedId} onOpen={onOpenSession} depth={1} />
              </div>
            )}
          </>
            )}
          </>
        )}
      </div>
      </TreeIntro.Provider>
      <TreeDialogs state={dialog} onClose={() => setDialog(null)} onTopicCreated={(tp) => onNewSession(tp.path)} />
    </nav>
  )
}

/** Top of the list, the same on a computer and on a phone: the filter field (with New session on touch, the fold
 *  button on a computer), then the All / Running / Unread chips and the view menu. */
function ListHeader({
  touch,
  q,
  onQ,
  show,
  onShow,
  sessions,
  onNew,
  onHide,
  menu,
}: {
  touch?: boolean
  q: string
  onQ: (v: string) => void
  show: 'running' | 'unread' | null
  onShow: (s: 'running' | 'unread' | null) => void
  sessions: Session[]
  onNew?: () => void
  onHide?: () => void
  menu: React.ReactNode
}) {
  const t = useT()
  const running = sessions.filter((s) => s.state === 'running').length
  const unread = sessions.filter((s) => s.unread).length
  const chip = (on: boolean) =>
    cn(
      'flex shrink-0 items-center gap-1.5 rounded-full font-medium whitespace-nowrap outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring',
      touch ? 'h-10 px-3 text-[13px]' : 'h-6 px-2.5 text-xs',
      on ? 'bg-foreground text-background' : 'bg-muted text-muted-foreground hover:text-foreground active:bg-accent',
    )
  return (
    <div className={cn('grid shrink-0', touch ? 'gap-2.5 px-3 pt-3 pb-2' : 'gap-2 px-2 pt-2 pb-1.5')} data-testid="tree-header">
      <div className={cn('flex items-center', touch ? 'gap-2' : 'gap-1')}>
        {onHide && (
          <Tooltip content={t('sessions.tree.hide')}>
            <Button variant="ghost" size="icon-sm" aria-label={t('sessions.tree.hide')} onClick={onHide} className="shrink-0 text-muted-foreground">
              <PanelLeftClose />
            </Button>
          </Tooltip>
        )}
        <div className="relative min-w-0 flex-1">
          <Search className={cn('pointer-events-none absolute top-1/2 -translate-y-1/2 text-muted-foreground', touch ? 'left-3 size-[18px]' : 'left-2.5 size-3.5')} />
          <Input
            value={q}
            onChange={(e) => onQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Escape' && (onQ(''), e.currentTarget.blur())}
            placeholder={t('sessions.tree.filter')}
            aria-label={t('sessions.tree.filter')}
            className={cn('border-0 bg-muted dark:bg-muted', touch ? 'h-11 rounded-xl pr-10 pl-10' : 'h-8 rounded-lg pr-7 pl-8 text-[13px]')}
            data-testid="tree-filter"
          />
          {q && (
            <button
              type="button"
              onClick={() => onQ('')}
              aria-label={t('sessions.tree.clearFilter')}
              className={cn('absolute top-1/2 -translate-y-1/2 flex items-center justify-center text-muted-foreground hover:text-foreground', touch ? 'right-0.5 size-10 rounded-lg' : 'right-1 size-6 rounded-md')}
            >
              <X className={touch ? 'size-4' : 'size-3.5'} />
            </button>
          )}
        </div>
        {touch && (
          <Button size="icon" className="size-11 shrink-0 rounded-xl [&_svg]:size-5" aria-label={t('sessions.newSession')} disabled={!onNew} onClick={onNew} data-tour="new-session">
            <SquarePen />
          </Button>
        )}
      </div>
      <div className="flex min-w-0 items-center gap-1.5">
        {!q && (
          <div className="-my-1 flex min-w-0 flex-1 gap-1.5 overflow-x-auto py-1" role="group" aria-label={t('sessions.filter.label')} data-hscroll-ok>
            <button type="button" className={chip(!show)} aria-pressed={!show} onClick={() => onShow(null)}>
              {t('sessions.filter.all')}
            </button>
            <button type="button" className={chip(show === 'running')} aria-pressed={show === 'running'} onClick={() => onShow(show === 'running' ? null : 'running')} data-testid="chip-running">
              <StatusDot tone="running" pulse={running > 0} className="size-1.5" /> {t('sessions.filter.running')}
              {running > 0 && <span className="tabular-nums opacity-70">{running}</span>}
            </button>
            <button type="button" className={chip(show === 'unread')} aria-pressed={show === 'unread'} onClick={() => onShow(show === 'unread' ? null : 'unread')} data-testid="chip-unread">
              <StatusDot tone="unread" className="size-1.5" /> {t('sessions.filter.unread')}
              {unread > 0 && <span className="tabular-nums opacity-70">{unread}</span>}
            </button>
          </div>
        )}
        <div className="ml-auto shrink-0">{menu}</div>
      </div>
    </div>
  )
}

function group(list: Session[] | undefined) {
  const m = new Map<string, Session[]>()
  for (const s of list || []) {
    const a = m.get(s.path)
    if (a) a.push(s)
    else m.set(s.path, [s])
  }
  return m
}

function TreeSkeleton() {
  return (
    <div className="grid gap-1.5 p-1.5" aria-busy>
      {[70, 55, 62, 48, 66].map((w, i) => (
        <Skeleton key={i} className="h-7" style={{ width: `${w}%`, marginLeft: i % 3 ? 16 : 0 }} />
      ))}
    </div>
  )
}

/* ---------------------------------------------------------------- nodes */
// Folding a row: saved in the tree state, or only for the current filter while one unfolds the tree.
function useFoldToggle(filtered: boolean): (id: string, open: boolean) => void {
  const toggle = useSessionsUI((s) => s.toggle)
  return React.useCallback(
    (id: string, open: boolean) => {
      if (!filtered) return toggle(id, open)
      const st = useSessionsUI.getState()
      st.setNarrowFolded({ ...st.narrowFolded, [id]: !open })
    },
    [filtered, toggle],
  )
}

function Chevron({ open }: { open: boolean }) {
  return <ChevronRight className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform duration-150', open && 'rotate-90')} />
}

// ---- drag and drop to reorder (projects among projects, topics inside their project) ------------
const DND_PROJECT = 'application/x-mx-project'
const dndTopic = (project: string) => `application/x-mx-topic-${project}`

/** `list` with `dragged` moved just before / after `target`. */
function moveName(list: string[], dragged: string, target: string, before: boolean): string[] {
  const out = list.filter((n) => n !== dragged)
  const i = out.indexOf(target)
  out.splice(i < 0 ? out.length : before ? i : i + 1, 0, dragged)
  return out
}

/** A tree row you can drag, and drop rows of the same kind (`type`) on: before or after it, by its halves. */
function useReorderRow(type: string, name: string, onMove: ((dragged: string, before: boolean) => void) | undefined) {
  const [pos, setPos] = React.useState<'before' | 'after' | null>(null)
  if (!onMove) return { pos: null, props: {} }
  const props = {
    draggable: true,
    onDragStart: (e: React.DragEvent) => {
      e.stopPropagation()
      e.dataTransfer.setData(type, name)
      e.dataTransfer.setData('text/plain', name)
      e.dataTransfer.effectAllowed = 'move'
    },
    onDragOver: (e: React.DragEvent) => {
      if (!e.dataTransfer.types.includes(type)) return
      e.preventDefault()
      e.stopPropagation()
      e.dataTransfer.dropEffect = 'move'
      const r = e.currentTarget.getBoundingClientRect()
      const next = e.clientY < r.top + r.height / 2 ? 'before' : 'after'
      if (next !== pos) setPos(next)
    },
    onDragLeave: (e: React.DragEvent) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setPos(null)
    },
    onDrop: (e: React.DragEvent) => {
      if (!e.dataTransfer.types.includes(type)) return
      e.preventDefault()
      e.stopPropagation()
      const dragged = e.dataTransfer.getData(type)
      const before = pos === 'before'
      setPos(null)
      if (dragged && dragged !== name) onMove(dragged, before)
    },
    onDragEnd: () => setPos(null),
  }
  return { pos, props }
}

// ---- drag a session onto another topic (or onto a session of another topic) to move it there ---------
// Same as "Move to another topic" in the session's column: the server moves its folder and its Claude
// transcript. Within a topic the order follows the list's sort (activity), so dropping there does nothing.
const DND_SESSION = 'application/x-mx-session'
/** The session being dragged (dragover cannot read the data, only its type). */
let draggedSession: { id: string; path: string } | null = null

/** Move a session to a topic, like the column header does (expand the destination, confirm). */
export function useMoveSessionTo() {
  const t = useT()
  const patch = usePatchSession()
  const setExpanded = useSessionsUI((s) => s.setExpanded)
  const rootLabel = t('sessions.root')
  return React.useCallback(
    (id: string, path: string) =>
      patch.mutate(
        { id, path },
        {
          onSuccess: () => {
            const project = path.split('/')[1]
            setExpanded({ [`p:${project}`]: true, [`t:${path}`]: true })
            toast.success(t('sessions.move.done', { where: topicLabel(path, rootLabel) }))
          },
        },
      ),
    [patch, setExpanded, t, rootLabel],
  )
}

function sessionDragProps(s: Session) {
  if (s.state === 'running' || s.queue > 0) return {}          // a running session cannot move (the server refuses)
  return {
    draggable: true,
    onDragStart: (e: React.DragEvent) => {
      e.stopPropagation()
      draggedSession = { id: s.id, path: s.path }
      e.dataTransfer.setData(DND_SESSION, s.id)
      e.dataTransfer.setData('text/plain', s.title)
      e.dataTransfer.effectAllowed = 'move'
    },
    onDragEnd: () => {
      draggedSession = null
    },
  }
}

/** A row that takes a dragged session and moves it to `path` (a topic row, or a session row of that topic). */
function useSessionDrop(path: string) {
  const move = useMoveSessionTo()
  const [over, setOver] = React.useState(false)
  const accepts = (e: React.DragEvent) => e.dataTransfer.types.includes(DND_SESSION) && !!draggedSession && draggedSession.path !== path
  const props = {
    onDragOver: (e: React.DragEvent) => {
      if (!accepts(e)) return
      e.preventDefault()
      e.stopPropagation()
      e.dataTransfer.dropEffect = 'move'
      if (!over) setOver(true)
    },
    onDragLeave: (e: React.DragEvent) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false)
    },
    onDrop: (e: React.DragEvent) => {
      if (!accepts(e)) return
      e.preventDefault()
      e.stopPropagation()
      setOver(false)
      const id = draggedSession!.id
      draggedSession = null
      move(id, path)
    },
  }
  return { over, props }
}

/** Both handlers of one DnD event, each ignoring the drags that are not its kind. */
function mergeDnd(a: Record<string, unknown>, b: Record<string, unknown>) {
  const out: Record<string, unknown> = { ...a, ...b }
  for (const k of Object.keys(a)) {
    const fa = a[k], fb = b[k]
    if (typeof fa === 'function' && typeof fb === 'function')
      out[k] = (e: React.DragEvent) => {
        ;(fa as (e: React.DragEvent) => void)(e)
        ;(fb as (e: React.DragEvent) => void)(e)
      }
  }
  return out
}

const dropCls = 'bg-primary/10 ring-2 ring-primary/50 ring-inset'

function DropLine({ pos }: { pos: 'before' | 'after' | null }) {
  if (!pos) return null
  return <span aria-hidden className={cn('pointer-events-none absolute inset-x-1 z-10 h-0.5 rounded-full bg-primary', pos === 'before' ? '-top-px' : '-bottom-px')} />
}

function ProjectNode({ project, forceOpen, onDialog, stagger, onMove, children }: { project: Project; forceOpen: boolean; onDialog: (d: DialogState) => void; stagger: number; onMove?: (dragged: string, before: boolean) => void; children: React.ReactNode }) {
  const t = useT()
  const id = `p:${project.name}`
  const stored = useSessionsUI((s) => s.expanded[id])
  const toggle = useFoldToggle(forceOpen)
  const folded = useSessionsUI((s) => forceOpen && !!s.narrowFolded[id])
  const open = forceOpen ? !folded : stored !== false
  const [intro] = React.useState(React.useContext(TreeIntro))
  const [menu, setMenu] = React.useState(false)
  const running = project.topics.reduce((n, tp) => n + tp.running, 0)
  const unread = project.topics.reduce((n, tp) => n + tp.unread, 0)
  const dnd = useReorderRow(DND_PROJECT, project.name, onMove)
  const press = useLongPress(() => setMenu(true))
  return (
    <div role="treeitem" aria-expanded={open} className={cn('mt-1 first:mt-0 max-md:[contain-intrinsic-size:auto_48px] max-md:[content-visibility:auto]', intro && 'mx-rise')} style={{ '--i': stagger } as React.CSSProperties}>
      <div
        {...dnd.props}
        {...press}
        data-testid="tree-project"
        className="group/row relative flex h-8 items-center gap-1 rounded-md pr-1 hover:bg-accent/60 max-md:h-12 max-md:select-none max-md:[-webkit-touch-callout:none]"
        onContextMenu={(e) => {
          e.preventDefault()
          setMenu(true)
        }}
      >
        <button type="button" onClick={() => toggle(id, !open)} className="flex min-w-0 flex-1 items-center gap-1.5 self-stretch rounded-md pl-1.5 text-left text-[13px] font-semibold focus-visible:ring-2 max-md:gap-2 max-md:text-[15px] focus-visible:ring-ring focus-visible:outline-none">
          <Chevron open={open} />
          {project.emoji && (
            <span className="shrink-0 text-[14px] leading-none" aria-hidden>
              {project.emoji}
            </span>
          )}
          <span className="truncate">
            <Sensitive length={8}>{project.name}</Sensitive>
          </span>
          {!open && <Badges running={running} unread={unread} />}
        </button>
        <RowMenu open={menu} onOpenChange={setMenu} label={t('common.more')}>
          <ProjectMenuItems project={project} onDialog={onDialog} />
        </RowMenu>
        <DropLine pos={dnd.pos} />
      </div>
      {open && (
        <div role="group" className={cn(!intro && 'mx-unfold')}>
          {children}
        </div>
      )}
    </div>
  )
}

/** Mouse: the row actions (+, ⋯) take no room until the row is hovered or focused, so the counters stay flush right;
 *  they swap with the counters. Touch keeps them in place. */
const HOVER_ACTION = 'md:pointer-fine:w-0 md:pointer-fine:overflow-hidden md:pointer-fine:group-hover/row:w-7 md:pointer-fine:group-has-[:focus-visible]/row:w-7 md:pointer-fine:data-[state=open]:w-7'
const HOVER_HIDE = 'md:pointer-fine:group-hover/row:hidden md:pointer-fine:group-has-[[data-state=open]]/row:hidden'

function Badges({ running, unread, count = 0 }: { running: number; unread: number; /** Sessions in the folded topic, shown when nothing runs nor waits. */ count?: number }) {
  const t = useT()
  const setShow = useSessionsUI((s) => s.setShow)
  // Inside the row's fold button: a click on a counter filters the tree instead of folding the row.
  const pick = (show: 'running' | 'unread') => (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setShow(show)
  }
  return (
    <span className={cn('ml-auto flex shrink-0 items-center gap-1.5 pl-1', HOVER_HIDE)}>
      {count > 0 && !running && !unread && <span className="text-[11px] text-muted-foreground tabular-nums">{count}</span>}
      {running > 0 && (
        <span onClick={pick('running')} className="inline-flex cursor-pointer items-center gap-1 rounded text-[11px] text-primary tabular-nums hover:underline" title={t('sessions.showRunning', { count: running })}>
          <StatusDot tone="running" pulse className="size-1.5" />
          {running}
        </span>
      )}
      <span onClick={pick('unread')} className="cursor-pointer rounded-full empty:hidden">
        <CountBadge count={unread} title={t('sessions.showUnread', { count: unread })} />
      </span>
    </span>
  )
}

function TopicNode({
  topic,
  sessions,
  archived,
  forceOpen,
  active,
  openIds,
  focusedId,
  onOpenSession,
  onNewSession,
  onDialog,
  rootDir,
  stagger,
  onMove,
}: {
  stagger: number
  onMove?: (dragged: string, before: boolean) => void
  topic: Topic
  sessions: Session[]
  archived: Session[]
  forceOpen: boolean
  active: boolean
  openIds: Set<string>
  focusedId: string | null
  onOpenSession: (s: Session) => void
  onNewSession: (path: string) => void
  onDialog: (d: DialogState) => void
  rootDir: string | null
}) {
  const t = useT()
  const id = `t:${topic.path}`
  const stored = useSessionsUI((s) => s.expanded[id])
  const archOpen = useSessionsUI((s) => !!s.expanded[`a:${topic.path}`])
  const nArchived = forceOpen ? archived.length : (topic.archived_count ?? archived.length)
  const toggle = useFoldToggle(forceOpen)
  const folded = useSessionsUI((s) => forceOpen && !!s.narrowFolded[id])
  const open = forceOpen ? !folded : (stored ?? (active || sessions.some((s) => openIds.has(s.id))))
  const [intro] = React.useState(React.useContext(TreeIntro))
  const [all, setAll] = React.useState(false)
  const [menu, setMenu] = React.useState(false)
  const row = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    if (active) row.current?.scrollIntoView({ block: 'nearest' })
  }, [active])
  const shown = all || forceOpen ? sessions : sessions.slice(0, SESSIONS_SHOWN)
  const dnd = useReorderRow(dndTopic(topic.project), topic.name, onMove)
  const drop = useSessionDrop(topic.path)
  const press = useLongPress(() => setMenu(true))
  return (
    <div role="treeitem" aria-expanded={open} className={cn(intro && 'mx-rise')} style={{ '--i': stagger } as React.CSSProperties}>
      <div
        ref={row}
        {...mergeDnd(dnd.props, drop.props)}
        {...press}
        data-testid="tree-topic"
        className={cn('group/row relative flex h-8 items-center gap-0.5 rounded-md pr-1 pl-3 hover:bg-accent/60 max-md:h-12 max-md:select-none max-md:[-webkit-touch-callout:none]', active && 'bg-accent/70', drop.over && dropCls)}
        onContextMenu={(e) => {
          e.preventDefault()
          setMenu(true)
        }}
      >
        <button type="button" onClick={() => toggle(id, !open)} className="flex min-w-0 flex-1 items-center gap-1.5 self-stretch rounded-md pl-1 text-left text-[13px] focus-visible:ring-2 max-md:gap-2 max-md:text-[15px] focus-visible:ring-ring focus-visible:outline-none">
          <Chevron open={open} />
          <Hash className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate">
            <Sensitive length={8}>{topic.name}</Sensitive>
          </span>
          {(!open || topic.running > 0 || topic.unread > 0) && <Badges running={topic.running} unread={topic.unread} count={open ? 0 : topic.session_count} />}
        </button>
        <Tooltip content={t('sessions.newIn')}>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={t('sessions.newIn')}
            onClick={() => onNewSession(topic.path)}
            className={cn('size-7 opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100 max-md:size-10 max-md:opacity-100 pointer-coarse:opacity-100', HOVER_ACTION)}
          >
            <Plus />
          </Button>
        </Tooltip>
        <RowMenu open={menu} onOpenChange={setMenu} label={t('common.more')}>
          <TopicMenuItems topic={topic} rootDir={rootDir} onNewSession={onNewSession} onDialog={onDialog} />
        </RowMenu>
        <DropLine pos={dnd.pos} />
      </div>
      {open && (
        <div role="group" className={cn(!intro && 'mx-unfold')}>
          {sessions.length === 0 && nArchived === 0 && (
            <button type="button" onClick={() => onNewSession(topic.path)} className="ml-9 flex h-7 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground hover:bg-accent hover:text-foreground max-md:h-10">
              <Plus className="size-3.5" /> {t('sessions.newSession')}
            </button>
          )}
          <SessionRows sessions={shown} openIds={openIds} focusedId={focusedId} onOpen={onOpenSession} still={forceOpen} />
          {!all && !forceOpen && sessions.length > SESSIONS_SHOWN && (
            <button type="button" onClick={() => setAll(true)} className="ml-9 h-7 rounded-md px-2 text-xs text-muted-foreground hover:text-foreground">
              {t('sessions.tree.showMore', { count: sessions.length - SESSIONS_SHOWN })}
            </button>
          )}
          {nArchived > 0 && (
            <>
              <button
                type="button"
                onClick={() => toggle(`a:${topic.path}`, !archOpen)}
                aria-expanded={archOpen}
                className="ml-7 flex h-7 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground hover:text-foreground max-md:h-10"
              >
                <Chevron open={archOpen} />
                <Archive className="size-3.5" /> {t('sessions.tree.archived', { count: nArchived })}
              </button>
              {archOpen && <SessionRows sessions={archived} openIds={openIds} focusedId={focusedId} onOpen={onOpenSession} depth={3} still={forceOpen} />}
            </>
          )}
        </div>
      )}
    </div>
  )
}

/** Session rows that unfold when a session is created, fold away when it is deleted / archived and slide
 * when the order changes (the most recent goes to the top). */
function SessionRows({
  sessions,
  openIds,
  focusedId,
  onOpen,
  depth,
  still,
  labelOf,
  compact,
  rise,
}: {
  sessions: Session[]
  openIds: Set<string>
  focusedId: string | null
  onOpen: (s: Session) => void
  depth?: number
  still?: boolean
  /** Small `project / topic` label under the title (flat layout, Favorites, Recent). */
  labelOf?: (s: Session) => string
  /** One line: title, then the label on the right (session list). */
  compact?: boolean
  /** Rows mounted now rise in, staggered (session list intro). */
  rise?: boolean
}) {
  const ms = still ? 0 : PRESENCE_MS
  const rows = usePresence(sessions, (s) => s.id, ms)
  const box = React.useRef<HTMLDivElement>(null)
  useFlip(
    () => new Map([...(box.current?.querySelectorAll<HTMLElement>(':scope > [data-row]:not([data-leaving])') ?? [])].map((el) => [el.dataset.row!, el])),
    [sessions.map((s) => s.id).join(' ')],
    'y',
    ms,
  )
  return (
    <div ref={box} className="relative">
      {rows.map((p, i) => (
        <RowPresence key={p.key} id={p.key} leaving={p.leaving} appear={p.appear} rise={rise ? Math.min(i, 10) : undefined}>
          <SessionRow s={p.item} open={openIds.has(p.item.id)} focused={focusedId === p.item.id} onOpen={onOpen} depth={depth} label={labelOf?.(p.item)} compact={compact} />
        </RowPresence>
      ))}
    </div>
  )
}

function RowPresence({ id, leaving, appear, rise, children }: { id: string; leaving: boolean; appear: boolean; rise?: number; children: React.ReactNode }) {
  const ref = React.useRef<HTMLDivElement>(null)
  const [stagger] = React.useState(rise)
  React.useLayoutEffect(() => {
    if (appear && ref.current) animateIn(ref.current, 'y')
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  React.useLayoutEffect(() => {
    if (leaving && ref.current) animateOut(ref.current, 'y')
  }, [leaving])
  return (
    <div ref={ref} data-row={id} data-leaving={leaving || undefined} className={stagger != null ? 'mx-rise' : undefined} style={stagger != null ? ({ '--i': stagger } as React.CSSProperties) : undefined}>
      {children}
    </div>
  )
}

const SessionRow = React.memo(function SessionRow({ s, open, focused, onOpen, depth = 2, label, compact }: { s: Session; open: boolean; focused: boolean; onOpen: (s: Session) => void; depth?: number; label?: string; compact?: boolean }) {
  const t = useT()
  const lang = useLang()
  const { data: claude } = useClaudeStatus()
  const [menu, setMenu] = React.useState(false)
  const [rename, setRename] = React.useState(false)
  const patch = usePatchSession()
  const del = useDeleteSession()
  const closeSession = useSessionsUI((x) => x.closeSession)
  const mask = useMask()
  const model = s.real_model || s.model
  const drop = useSessionDrop(s.path)
  const press = useLongPress(() => setMenu(true))
  // Touch layout: two lines (title, then where and when) even in the Favorites / Recent blocks.
  const touchLayout = useCompact()
  const oneLine = compact && !touchLayout
  return (
    <div
      role="treeitem"
      aria-selected={focused}
      {...sessionDragProps(s)}
      {...drop.props}
      {...press}
      data-testid="tree-session"
      className={cn(
        'group/row relative flex items-center rounded-md pr-1 hover:bg-accent/60 max-md:h-14 max-md:select-none max-md:[-webkit-touch-callout:none]',
        compact ? 'h-8' : 'h-9',
        focused && 'bg-accent',
        s.unread && 'font-medium',
        drop.over && dropCls,
      )}
      style={{ paddingLeft: depth * 12 + 8 }}
      onContextMenu={(e) => {
        e.preventDefault()
        setMenu(true)
      }}
    >
      {open && <span aria-hidden className="absolute top-2 bottom-2 left-1 w-0.5 rounded-full bg-primary/70" />}
      <button type="button" onClick={() => onOpen(s)} className="flex min-w-0 flex-1 items-center gap-2 self-stretch rounded-md text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none" data-session-row={s.id}>
        <span className="flex size-3.5 shrink-0 items-center justify-center">
          {s.state === 'running' ? (
            <StatusDot tone="running" pulse label={t('sessions.state.running')} />
          ) : s.state === 'error' ? (
            <StatusDot tone="error" label={t('sessions.state.error')} />
          ) : s.unread ? (
            <StatusDot tone="unread" label={t('sessions.unreadOne')} />
          ) : s.source === 'cron' ? (
            <Clock className="size-3 text-muted-foreground" aria-label={t('sessions.source.cron')} />
          ) : (
            <StatusDot tone="idle" className="size-1.5" />
          )}
        </span>
        {oneLine ? (
          <span className="flex min-w-0 flex-1 items-center gap-1.5 text-[13px]" title={fmtRelative(s.updated, lang)}>
            <span className="min-w-0 truncate">
              <Sensitive length={10}>{s.title}</Sensitive>
            </span>
            {s.favorite && <Star className="size-3 shrink-0 fill-current text-warning" aria-label={t('sessions.fav.on')} />}
            {label && (
              // Only the topic, like the project tree; "project › topic" is in the tooltip.
              <span className="ml-auto flex max-w-[40%] min-w-0 shrink-0 items-center gap-0.5 pl-1 text-[11px] font-normal text-muted-foreground" title={mask(label, 8)} data-testid="session-label">
                {label.includes(" › ") && <Hash className="size-3 shrink-0 opacity-60" />}
                <span className="min-w-0 truncate">
                  <Sensitive length={6}>{label.split(' › ').pop()}</Sensitive>
                </span>
              </span>
            )}
          </span>
        ) : (
        <span className="grid min-w-0 flex-1 leading-tight max-md:gap-0.5">
          <span className="flex min-w-0 items-center gap-1 text-[13px] max-md:text-[15px]">
            <span className="truncate">
              <Sensitive length={10}>{s.title}</Sensitive>
            </span>
            {s.favorite && <Star className="size-3 shrink-0 fill-current text-warning" aria-label={t('sessions.fav.on')} />}
          </span>
          <span className="flex min-w-0 items-center gap-1.5 text-[11px] font-normal text-muted-foreground max-md:text-[12.5px]">
            {label && (
              <span className="min-w-0 shrink truncate" data-testid="session-label">
                <Sensitive length={8}>{label}</Sensitive> ·
              </span>
            )}
            <span className="shrink-0 tabular-nums">{fmtRelative(s.updated, lang)}</span>
            {model && !label && <span className="truncate">· {modelLabel(model, claude?.models)}</span>}
            {s.queue > 0 && <span className="shrink-0">· {t('sessions.queue.short', { count: s.queue })}</span>}
          </span>
        </span>
        )}
      </button>
      <RowMenu open={menu} onOpenChange={setMenu} label={t('common.more')}>
        <DropdownMenuItem onSelect={() => onOpen(s)}>
          <ChevronRight /> {t('sessions.open')}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setRename(true)}>
          <Pencil /> {t('sessions.rename')}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => patch.mutate({ id: s.id, favorite: !s.favorite })} data-testid="fav-toggle">
          {s.favorite ? <StarOff /> : <Star />} {s.favorite ? t('sessions.fav.remove') : t('sessions.fav.add')}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => patch.mutate({ id: s.id, archived: !s.archived })}>
          <Archive /> {s.archived ? t('sessions.menu.unarchive') : t('sessions.menu.archive')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          destructive
          onSelect={async () => {
            if (!(await confirm({ title: t('sessions.delete.title'), description: t('sessions.delete.desc'), destructive: true, confirmText: t('common.delete') }))) return
            del.mutate(s.id, {
              onSuccess: () => {
                closeSession(s.id)
                forgetLog(s.id)
                saveDraft(s.id, '')
                saveQuotes(s.id, [])
                toast.success(t('sessions.delete.done'))
              },
            })
          }}
        >
          <Trash2 /> {t('sessions.menu.delete')}
        </DropdownMenuItem>
      </RowMenu>
      <RenameDialog
        open={rename}
        onOpenChange={setRename}
        title={t('sessions.rename')}
        initial={s.title}
        slug={false}
        onSubmit={async (v) => {
          await patch.mutateAsync({ id: s.id, title: v })
        }}
      />
    </div>
  )
})

function RowMenu({ open, onOpenChange, label, children }: { open: boolean; onOpenChange: (o: boolean) => void; label: string; children: React.ReactNode }) {
  return (
    <DropdownMenu open={open} onOpenChange={onOpenChange}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={label}
          className={cn('size-7 shrink-0 opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100 pointer-coarse:opacity-100 max-md:pointer-events-none max-md:invisible max-md:absolute max-md:right-2 max-md:size-px', HOVER_ACTION)}
        >
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        {children}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/* ---------------------------------------------------------------- menus shared by the tree and drill-down */
function ProjectMenuItems({ project, onDialog }: { project: Project; onDialog: (d: DialogState) => void }) {
  const t = useT()
  return (
    <>
      <DropdownMenuItem onSelect={() => onDialog({ kind: 'topic', project: project.name })}>
        <Plus /> {t('sessions.tree.newTopic')}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => onDialog({ kind: 'rename-project', project })}>
        <Pencil /> {t('sessions.tree.rename')}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => onDialog({ kind: 'emoji-project', project })} data-testid="project-emoji">
        <Smile /> {project.emoji ? t('sessions.emoji.change') : t('sessions.emoji.set')}
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem destructive onSelect={() => onDialog({ kind: 'delete-project', project })}>
        <Trash2 /> {t('sessions.tree.delete')}
      </DropdownMenuItem>
    </>
  )
}

function TopicMenuItems({ topic, rootDir, onNewSession, onDialog }: { topic: Topic; rootDir: string | null; onNewSession: (path: string) => void; onDialog: (d: DialogState) => void }) {
  const t = useT()
  const navigate = useNavigate()
  return (
    <>
      <DropdownMenuItem onSelect={() => onNewSession(topic.path)}>
        <Plus /> {t('sessions.newSession')}
      </DropdownMenuItem>
      <DropdownMenuItem disabled={!rootDir} onSelect={() => rootDir && navigate(`/files?path=${encodeURIComponent(rootDir)}`)}>
        <FolderOpen /> {t('sessions.menu.openFolder')}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => onDialog({ kind: 'rename-topic', topic })}>
        <Pencil /> {t('sessions.tree.rename')}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => onDialog({ kind: 'permission-topic', topic })} data-testid="topic-permission">
        <ShieldHalf /> {t('sessions.permission.menu')}
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem destructive onSelect={() => onDialog({ kind: 'delete-topic', topic })}>
        <Trash2 /> {t('sessions.tree.delete')}
      </DropdownMenuItem>
    </>
  )
}

/* ---------------------------------------------------------------- Favorites / Recent blocks */
function TopBlocks({ sessions, openIds, focusedId, onOpen, labelOf }: { sessions: Session[]; openIds: Set<string>; focusedId: string | null; onOpen: (s: Session) => void; labelOf: (s: Session) => string }) {
  const t = useT()
  const { showFavorites, showRecent, recentCount } = useSessionsUI(useShallow((s) => ({ showFavorites: s.showFavorites, showRecent: s.showRecent, recentCount: s.recentCount })))
  const favs = React.useMemo(() => sessions.filter((s) => s.favorite).sort((a, b) => a.title.localeCompare(b.title)), [sessions])
  // A favorite is not repeated in Recent while the Favorites block is shown.
  const recent = React.useMemo(
    () => [...sessions].filter((s) => !(showFavorites && s.favorite)).sort((a, b) => b.updated - a.updated).slice(0, recentCount),
    [sessions, showFavorites, recentCount],
  )
  // An empty Favorites block is not shown (the hint lives in the docs and the session menu).
  const withFavs = showFavorites && favs.length > 0
  const withRecent = showRecent && recent.length > 0
  if (!withFavs && !withRecent) return null
  return (
    <div className="mb-2 grid gap-1 border-b pb-2" data-testid="tree-blocks">
      {withFavs && (
        <section aria-label={t('sessions.fav.title')} className="mx-unfold" data-testid="block-favorites">
          <h3 className="flex h-7 items-center gap-1.5 px-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            <Star className="size-3" /> {t('sessions.fav.title')}
          </h3>
          <SessionRows sessions={favs} openIds={openIds} focusedId={focusedId} onOpen={onOpen} depth={0} labelOf={labelOf} compact />
        </section>
      )}
      {withRecent && (
        <section aria-label={t('sessions.recent.title')} data-testid="block-recent">
          <h3 className="flex h-7 items-center gap-1.5 px-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            <Clock className="size-3" /> {t('sessions.recent.title')}
          </h3>
          <SessionRows sessions={recent} openIds={openIds} focusedId={focusedId} onOpen={onOpen} depth={0} labelOf={labelOf} compact />
        </section>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- session list */
const USAGE_HALF_LIFE_DAYS = 7

/** "Most used" score: the turns of a session, halved for every week since its last activity - a long session
 *  used this week comes before a one-off from today, and an old marathon slowly fades. */
function usage(s: Session, now: number) {
  const days = Math.max(0, now - s.updated) / 86400
  return (s.turns + 1) * 0.5 ** (days / USAGE_HALF_LIFE_DAYS)
}

function FlatView({ sessions, searching, openIds, focusedId, onOpen, labelOf }: { sessions: Session[]; searching: boolean; openIds: Set<string>; focusedId: string | null; onOpen: (s: Session) => void; labelOf: (s: Session) => string }) {
  const t = useT()
  const { flatSort, flatDesc } = useSessionsUI(useShallow((s) => ({ flatSort: s.flatSort, flatDesc: s.flatDesc })))
  const intro = React.useContext(TreeIntro)
  const [shown, setShown] = React.useState(FLAT_SHOWN)
  const sorted = React.useMemo(() => {
    const now = Date.now() / 1000
    const key = (s: Session) =>
      flatSort === 'used' ? usage(s, now) : flatSort === 'name' ? s.title.toLowerCase() : flatSort === 'created' ? s.created : s.updated
    const out = [...sessions].sort((a, b) => {
      const x = key(a)
      const y = key(b)
      const c = typeof x === 'string' ? x.localeCompare(y as string) : (x as number) - (y as number)
      return flatDesc ? -c : c
    })
    return out
  }, [sessions, flatSort, flatDesc])
  if (!sorted.length) return <p className="px-3 py-6 text-center text-sm text-muted-foreground">{searching ? t('common.noResults') : t('sessions.flat.empty')}</p>
  return (
    <div data-testid="flat-view">
      <SessionRows sessions={sorted.slice(0, shown)} openIds={openIds} focusedId={focusedId} onOpen={onOpen} depth={0} still={searching} labelOf={labelOf} compact rise={intro && !searching} />
      {sorted.length > shown && (
        <button type="button" onClick={() => setShown((n) => n + FLAT_SHOWN)} className="ml-2 h-7 rounded-md px-2 text-xs text-muted-foreground hover:text-foreground">
          {t('sessions.tree.showMore', { count: sorted.length - shown })}
        </button>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- drill-down layout */
function DrillView({
  projects,
  byPath,
  archivedByPath,
  rootSessions,
  openIds,
  focusedId,
  onOpenSession,
  onNewSession,
  onDialog,
  rootDirOf,
}: {
  projects: Project[]
  byPath: Map<string, Session[]>
  archivedByPath: Map<string, Session[]>
  rootSessions: Session[]
  openIds: Set<string>
  focusedId: string | null
  onOpenSession: (s: Session) => void
  onNewSession: (path: string) => void
  onDialog: (d: DialogState) => void
  rootDirOf: (path: string) => string | null
}) {
  const t = useT()
  const drill = useSessionsUI((s) => s.drill)
  const setDrill = useSessionsUI((s) => s.setDrill)
  const archOpen = useSessionsUI((s) => (drill.topic ? !!s.expanded[`a:${drill.topic}`] : false))
  const toggle = useSessionsUI((s) => s.toggle)
  // A project / topic that no longer exists (renamed, deleted) brings the list back one level.
  const project = projects.find((p) => p.name === drill.project)
  const topic = project?.topics.find((tp) => tp.path === drill.topic)
  const level = !project ? 'projects' : !topic ? 'topics' : 'sessions'

  if (level === 'projects')
    return (
      <div key="projects" className="animate-in" data-testid="drill-projects">
        {projects.map((p, i) => (
          <DrillRow
            key={p.name}
            stagger={Math.min(i, 10)}
            icon={p.emoji ? <span className="w-3.5 shrink-0 text-center text-[14px] leading-none" aria-hidden>{p.emoji}</span> : <FolderOpen className="size-3.5 text-muted-foreground" />}
            name={p.name}
            bold
            count={p.topics.length}
            running={p.topics.reduce((n, tp) => n + tp.running, 0)}
            unread={p.topics.reduce((n, tp) => n + tp.unread, 0)}
            onOpen={() => setDrill({ project: p.name, topic: null })}
            menu={<ProjectMenuItems project={p} onDialog={onDialog} />}
          />
        ))}
        {rootSessions.length > 0 && (
          <div className="mt-2 border-t pt-2">
            <div className="flex h-8 items-center gap-1.5 px-2 text-xs font-medium text-muted-foreground">
              <FolderOpen className="size-3.5" /> {t('sessions.root')}
            </div>
            <SessionRows sessions={rootSessions} openIds={openIds} focusedId={focusedId} onOpen={onOpenSession} depth={0} />
          </div>
        )}
      </div>
    )

  if (level === 'topics')
    return (
      <div key={`p:${project!.name}`} className="animate-in" data-testid="drill-topics">
        <DrillHeader back={t('sessions.drill.projects')} onBack={() => setDrill({ project: null, topic: null })} title={project!.emoji ? `${project!.emoji} ${project!.name}` : project!.name} menu={<ProjectMenuItems project={project!} onDialog={onDialog} />} />
        {project!.topics.map((tp, i) => (
          <DrillRow
            key={tp.path}
            stagger={Math.min(i, 10)}
            icon={<Hash className="size-3.5 text-muted-foreground" />}
            name={tp.name}
            count={tp.session_count}
            running={tp.running}
            unread={tp.unread}
            onOpen={() => setDrill({ project: project!.name, topic: tp.path })}
            onNew={() => onNewSession(tp.path)}
            menu={<TopicMenuItems topic={tp} rootDir={rootDirOf(tp.path)} onNewSession={onNewSession} onDialog={onDialog} />}
          />
        ))}
        {project!.topics.length === 0 && (
          <button type="button" onClick={() => onDialog({ kind: 'topic', project: project!.name })} className="ml-2 flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">
            <Plus className="size-3.5" /> {t('sessions.tree.newTopic')}
          </button>
        )}
      </div>
    )

  const sessions = byPath.get(topic!.path) || []
  const archived = archivedByPath.get(topic!.path) || []
  const nArchived = topic!.archived_count ?? archived.length
  return (
    <div key={`t:${topic!.path}`} className="animate-in" data-testid="drill-sessions">
      <DrillHeader
        back={project!.emoji ? `${project!.emoji} ${project!.name}` : project!.name}
        onBack={() => setDrill({ project: project!.name, topic: null })}
        title={topic!.name}
        hash
        onNew={() => onNewSession(topic!.path)}
        menu={<TopicMenuItems topic={topic!} rootDir={rootDirOf(topic!.path)} onNewSession={onNewSession} onDialog={onDialog} />}
      />
      {sessions.length === 0 && nArchived === 0 && (
        <button type="button" onClick={() => onNewSession(topic!.path)} className="ml-2 flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground hover:bg-accent hover:text-foreground max-md:h-10">
          <Plus className="size-3.5" /> {t('sessions.newSession')}
        </button>
      )}
      <SessionRows sessions={sessions} openIds={openIds} focusedId={focusedId} onOpen={onOpenSession} depth={0} />
      {nArchived > 0 && (
        <>
          <button
            type="button"
            onClick={() => toggle(`a:${topic!.path}`, !archOpen)}
            aria-expanded={archOpen}
            className="ml-1 flex h-7 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground hover:text-foreground max-md:h-10"
          >
            <Chevron open={archOpen} />
            <Archive className="size-3.5" /> {t('sessions.tree.archived', { count: nArchived })}
          </button>
          {archOpen && <SessionRows sessions={archived} openIds={openIds} focusedId={focusedId} onOpen={onOpenSession} depth={1} />}
        </>
      )}
    </div>
  )
}

function DrillHeader({ back, onBack, title, hash, onNew, menu }: { back: string; onBack: () => void; title: string; hash?: boolean; onNew?: () => void; menu: React.ReactNode }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  return (
    <div className="mb-1 grid gap-0.5 border-b pb-1.5">
      <button type="button" onClick={onBack} className="flex h-7 w-fit max-w-full items-center gap-1 rounded-md px-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground max-md:h-10" data-testid="drill-back">
        <ChevronLeft className="size-3.5 shrink-0" />
        <span className="truncate">
          <Sensitive length={8}>{back}</Sensitive>
        </span>
      </button>
      <div className="group/row flex h-8 items-center gap-1 rounded-md pr-1 pl-2 max-md:h-10">
        {hash && <Hash className="size-3.5 shrink-0 text-muted-foreground" />}
        <span className="min-w-0 flex-1 truncate text-[13px] font-semibold">
          <Sensitive length={8}>{title}</Sensitive>
        </span>
        {onNew && (
          <Tooltip content={t('sessions.newIn')}>
            <Button variant="ghost" size="icon-sm" aria-label={t('sessions.newIn')} onClick={onNew} className="size-7 max-md:size-10">
              <Plus />
            </Button>
          </Tooltip>
        )}
        <RowMenu open={open} onOpenChange={setOpen} label={t('common.more')}>
          {menu}
        </RowMenu>
      </div>
    </div>
  )
}

function DrillRow({
  icon,
  name,
  bold,
  count,
  running,
  unread,
  onOpen,
  onNew,
  menu,
  stagger,
}: {
  icon: React.ReactNode
  name: string
  bold?: boolean
  count: number
  running: number
  unread: number
  onOpen: () => void
  onNew?: () => void
  menu: React.ReactNode
  stagger: number
}) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  return (
    <div
      className="group/row mx-rise flex h-9 items-center gap-0.5 rounded-md pr-1 hover:bg-accent/60 max-md:h-12"
      style={{ '--i': stagger } as React.CSSProperties}
      onContextMenu={(e) => {
        e.preventDefault()
        setOpen(true)
      }}
    >
      <button type="button" onClick={onOpen} className={cn('flex min-w-0 flex-1 items-center gap-2 self-stretch rounded-md pl-2 text-left text-[13px] focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none', bold && 'font-semibold')} data-drill-row={name}>
        {icon}
        <span className="truncate">
          <Sensitive length={8}>{name}</Sensitive>
        </span>
        {running > 0 || unread > 0 ? <Badges running={running} unread={unread} /> : count > 0 && <span className="ml-auto text-[11px] font-normal text-muted-foreground tabular-nums">{count}</span>}
        <ChevronRight className={cn('size-3.5 shrink-0 text-muted-foreground', !(running > 0 || unread > 0 || count > 0) && 'ml-auto')} />
      </button>
      {onNew && (
        <Tooltip content={t('sessions.newIn')}>
          <Button variant="ghost" size="icon-sm" aria-label={t('sessions.newIn')} onClick={onNew} className="size-7 opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100 max-md:size-10 max-md:opacity-100 pointer-coarse:opacity-100">
            <Plus />
          </Button>
        </Tooltip>
      )}
      <RowMenu open={open} onOpenChange={setOpen} label={t('common.more')}>
        {menu}
      </RowMenu>
    </div>
  )
}

/* ---------------------------------------------------------------- footer controls */
const SORT_ICON: Record<FlatSort, React.ComponentType<{ className?: string }>> = { used: Flame, recent: Clock, name: ArrowDownAZ, created: CalendarClock }

/** The one view menu of the list: group by projects or sessions, how projects show (tree or one level at a time),
 *  the session sort, fold / unfold all, the Favorites / Recent blocks, and New project. */
function ViewMenu({ fold, onNewProject }: { fold: { anyFolded: boolean; onFold: () => void } | null; onNewProject: () => void }) {
  const t = useT()
  const ui = useSessionsUI(
    useShallow((s) => ({
      listBy: s.listBy,
      setListBy: s.setListBy,
      mode: s.treeMode,
      setMode: s.setTreeMode,
      flatSort: s.flatSort,
      setFlatSort: s.setFlatSort,
      showFavorites: s.showFavorites,
      showRecent: s.showRecent,
      recentCount: s.recentCount,
      setBlocks: s.setBlocks,
    })),
  )
  const keep = (e: Event) => e.preventDefault()
  return (
    <DropdownMenu>
      <Tooltip content={t('sessions.options')}>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" className="size-7 shrink-0 text-muted-foreground max-md:size-10" aria-label={t('sessions.options')} data-testid="tree-options">
            <SlidersHorizontal />
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end" className="max-h-[min(80vh,var(--radix-dropdown-menu-content-available-height))] w-60 overflow-y-auto">
        <DropdownMenuLabel>{t('sessions.view.groupBy')}</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={ui.listBy} onValueChange={(v) => ui.setListBy(v as ListBy)}>
          <DropdownMenuRadioItem value="project" onSelect={keep} data-testid="list-by-project">
            <ListTree /> {t('sessions.view.projects')}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="session" onSelect={keep} data-testid="list-by-session">
            <List /> {t('sessions.view.sessions')}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        {ui.listBy === 'project' ? (
          <>
            <DropdownMenuLabel>{t('sessions.view.layout')}</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={ui.mode} onValueChange={(v) => ui.setMode(v as TreeMode)}>
              {TREE_MODES.map((m) => {
                const Icon = m === 'tree' ? ListTree : Columns3
                return (
                  <DropdownMenuRadioItem key={m} value={m} onSelect={keep} data-testid={`tree-mode-${m}`}>
                    <Icon /> {t(`sessions.mode.${m}` as const)}
                  </DropdownMenuRadioItem>
                )
              })}
            </DropdownMenuRadioGroup>
            {fold && (
              <DropdownMenuItem onSelect={fold.onFold} data-testid="tree-fold">
                {fold.anyFolded ? <ChevronsUpDown /> : <ChevronsDownUp />}
                {fold.anyFolded ? t('sessions.tree.expandAll') : t('sessions.tree.collapseAll')}
              </DropdownMenuItem>
            )}
          </>
        ) : (
          <>
            <DropdownMenuLabel>{t('sessions.view.sort')}</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={ui.flatSort} onValueChange={(v) => ui.setFlatSort(v as FlatSort)}>
              {FLAT_SORTS.map((f) => {
                const Icon = SORT_ICON[f]
                return (
                  <DropdownMenuRadioItem key={f} value={f} onSelect={keep}>
                    <Icon /> {t(`sessions.sort.${f}` as const)}
                  </DropdownMenuRadioItem>
                )
              })}
            </DropdownMenuRadioGroup>
          </>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuLabel>{t('sessions.options.blocks')}</DropdownMenuLabel>
        <DropdownMenuCheckboxItem checked={ui.showFavorites} onCheckedChange={(v) => ui.setBlocks({ showFavorites: !!v })} onSelect={keep} data-testid="opt-favorites">
          {t('sessions.fav.title')}
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked={ui.showRecent} onCheckedChange={(v) => ui.setBlocks({ showRecent: !!v })} onSelect={keep} data-testid="opt-recent">
          {t('sessions.recent.title')}
        </DropdownMenuCheckboxItem>
        {ui.showRecent && (
          <div className="flex items-center gap-1 px-2 py-1.5 text-xs text-muted-foreground">
            <span className="mr-auto pl-6">{t('sessions.recent.count')}</span>
            {RECENT_COUNTS.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => ui.setBlocks({ recentCount: n })}
                aria-pressed={ui.recentCount === n}
                className={cn('h-6 min-w-6 rounded-md px-1.5 tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring', ui.recentCount === n ? 'bg-foreground text-background' : 'hover:bg-accent hover:text-foreground')}
              >
                {n}
              </button>
            ))}
          </div>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onNewProject}>
          <FolderPlus /> {t('sessions.tree.newProject')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/* ---------------------------------------------------------------- dialogs */
type DialogState =
  | null
  | { kind: 'project' }
  | { kind: 'topic'; project: string }
  | { kind: 'rename-project'; project: Project }
  | { kind: 'emoji-project'; project: Project }
  | { kind: 'rename-topic'; topic: Topic }
  | { kind: 'permission-topic'; topic: Topic }
  | { kind: 'delete-project'; project: Project }
  | { kind: 'delete-topic'; topic: Topic }

function TreeDialogs({ state, onClose, onTopicCreated }: { state: DialogState; onClose: () => void; onTopicCreated: (tp: Topic) => void }) {
  const t = useT()
  const createProject = useCreateProject()
  const createTopic = useCreateTopic()
  const patchProject = usePatchProject()
  const patchTopic = usePatchTopic()
  const delProject = useDeleteProject()
  const delTopic = useDeleteTopic()
  const mask = useMask()

  // Deletions go through the shared confirm dialog.
  React.useEffect(() => {
    if (!state || (state.kind !== 'delete-project' && state.kind !== 'delete-topic')) return
    onClose()
    const isP = state.kind === 'delete-project'
    const name = isP ? state.project.name : state.topic.name
    void confirm({
      title: isP ? t('sessions.tree.deleteProjectTitle', { name: mask(name, 8) }) : t('sessions.tree.deleteTopicTitle', { name: mask(name, 8) }),
      description: t('sessions.tree.deleteDesc'),
      destructive: true,
      confirmText: t('common.delete'),
      typeToConfirm: name,
    }).then((ok) => {
      if (!ok) return
      const done = { onSuccess: () => toast.success(t('sessions.tree.deleted')), onError: () => {} }
      if (isP) delProject.mutate(state.project.name, done)
      else delTopic.mutate({ project: state.topic.project, topic: state.topic.name }, done)
    })
  }, [state]) // eslint-disable-line react-hooks/exhaustive-deps

  const open = !!state && state.kind !== 'delete-project' && state.kind !== 'delete-topic'
  if (!state || !open) return null
  if (state.kind === 'emoji-project')
    return (
      <EmojiDialog
        project={state.project}
        onClose={onClose}
        onSubmit={async (emoji) => {
          await patchProject.mutateAsync({ project: state.project.name, emoji })
        }}
      />
    )
  if (state.kind === 'permission-topic')
    return (
      <PermissionDialog
        topic={state.topic}
        onClose={onClose}
        onSelect={(mode) => {
          patchTopic.mutate({ project: state.topic.project, topic: state.topic.name, permission_mode: mode })
          onClose()
        }}
      />
    )
  if (state.kind === 'project' || state.kind === 'topic')
    return (
      <CreateDialog
        kind={state.kind}
        project={state.kind === 'topic' ? state.project : undefined}
        onClose={onClose}
        onSubmit={async (name, description) => {
          if (state.kind === 'project') {
            await createProject.mutateAsync({ name, description })
            toast.success(t('sessions.tree.projectCreated'))
          } else {
            const tp = await createTopic.mutateAsync({ project: state.project, name, description })
            onTopicCreated(tp)
          }
        }}
      />
    )
  const isP = state.kind === 'rename-project'
  return (
    <RenameDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={isP ? t('sessions.tree.renameProject') : t('sessions.tree.renameTopic')}
      description={t('sessions.tree.renameDesc')}
      initial={isP ? state.project.name : state.topic.name}
      slug
      prefix={isP ? 'projects/' : `projects/${state.topic.project}/topics/`}
      onSubmit={async (v) => {
        if (isP) await patchProject.mutateAsync({ project: state.project.name, name: v })
        else await patchTopic.mutateAsync({ project: state.topic.project, topic: state.topic.name, name: v })
      }}
    />
  )
}

/** Common picks; any other emoji can be typed or pasted (phone keyboards have an emoji key). */
const EMOJI_PICKS = ['🛒', '📦', '💼', '🏢', '🚀', '💡', '🧠', '📈', '💰', '🛍️', '☕', '🍕', '🎨', '🎬', '🎵', '📸', '✍️', '📚', '🎓', '🧪', '💻', '🛠️', '⚙️', '🤖', '🌐', '📱', '🎮', '🏠', '❤️', '⭐', '🔥', '🌱', '🐾', '✈️', '⚽', '🏛️', '⚖️', '🩺', '📣', '🗂️']

/** The topic's own permission mode for Claude turns ("" = the global setting); saved on click. */
function PermissionDialog({ topic, onClose, onSelect }: { topic: Topic; onClose: () => void; onSelect: (mode: '' | PermissionMode) => void }) {
  const t = useT()
  const cur = topic.permission_mode || ''
  const modes: { id: '' | PermissionMode; icon: typeof ShieldAlert; title: string; desc: string }[] = [
    { id: '', icon: SlidersHorizontal, title: t('sessions.permission.inherit'), desc: t('sessions.permission.inheritDesc') },
    { id: 'bypass', icon: ShieldAlert, title: t('claude.mode.bypass'), desc: t('claude.mode.bypassDesc') },
    { id: 'acceptEdits', icon: ShieldHalf, title: t('claude.mode.acceptEdits'), desc: t('claude.mode.acceptEditsDesc') },
    { id: 'default', icon: ShieldCheck, title: t('claude.mode.default'), desc: t('claude.mode.defaultDesc') },
  ]
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="permission-dialog">
        <DialogHeader>
          <DialogTitle>{t('sessions.permission.title', { name: topic.name })}</DialogTitle>
          <DialogDescription>{t('sessions.permission.desc')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-2" role="radiogroup">
          {modes.map((m) => (
            <OptionCard key={m.id || 'inherit'} name="topic-permission" value={m.id || 'inherit'} selected={cur === m.id} onSelect={() => onSelect(m.id)} icon={m.icon} title={m.title} description={m.desc} />
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function EmojiDialog({ project, onClose, onSubmit }: { project: Project; onClose: () => void; onSubmit: (emoji: string) => Promise<void> }) {
  const t = useT()
  const [v, setV] = React.useState(project.emoji || '')
  const [err, setErr] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const save = async (emoji: string) => {
    setBusy(true)
    try {
      await onSubmit(emoji.trim())
      onClose()
    } catch (x) {
      setErr(isApiError(x) && x.status === 400 ? t('sessions.emoji.invalid') : errorMessage(x))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="emoji-dialog">
        <form
          className="grid gap-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            void save(v)
          }}
        >
          <DialogHeader>
            <DialogTitle>{t('sessions.emoji.title', { name: project.name })}</DialogTitle>
            <DialogDescription>{t('sessions.emoji.desc')}</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-8 gap-1" role="listbox" aria-label={t('sessions.emoji.title', { name: project.name })}>
            {EMOJI_PICKS.map((e) => (
              <button
                key={e}
                type="button"
                role="option"
                aria-selected={v === e}
                onClick={() => {
                  setV(e)
                  setErr(null)
                }}
                className={cn('flex aspect-square items-center justify-center rounded-md text-xl outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring', v === e && 'bg-primary/15 ring-2 ring-primary')}
              >
                {e}
              </button>
            ))}
          </div>
          <FormField label={t('sessions.emoji.other')} error={err || undefined}>
            <Input
              value={v}
              onChange={(e) => {
                setV(e.target.value)
                setErr(null)
              }}
              maxLength={8}
              placeholder="🙂"
              className="w-24 text-center text-lg"
              autoComplete="off"
              data-testid="emoji-input"
            />
          </FormField>
          <DialogFooter>
            {project.emoji && (
              <Button type="button" variant="ghost" className="mr-auto" onClick={() => void save('')} disabled={busy}>
                {t('sessions.emoji.remove')}
              </Button>
            )}
            <Button type="button" variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={busy} disabled={!v.trim() && !project.emoji}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function CreateDialog({ kind, project, onClose, onSubmit }: { kind: 'project' | 'topic'; project?: string; onClose: () => void; onSubmit: (name: string, description?: string) => Promise<void> }) {
  const t = useT()
  const [label, setLabel] = React.useState('')
  const [desc, setDesc] = React.useState('')
  const [err, setErr] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const slug = slugify(label)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!SLUG_RE.test(slug)) return setErr(t('workspace.nameInvalid'))
    setBusy(true)
    try {
      await onSubmit(slug, desc.trim() || undefined)
      onClose()
    } catch (x) {
      setErr(isApiError(x, 'exists') ? t('workspace.exists') : isApiError(x, 'has_running_sessions') ? t('workspace.hasRunningSessions') : errorMessage(x))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <DialogHeader>
            <DialogTitle>{kind === 'project' ? t('sessions.tree.newProject') : t('sessions.tree.newTopic')}</DialogTitle>
            <DialogDescription>{kind === 'project' ? t('sessions.tree.newProjectDesc') : t('sessions.tree.newTopicDesc')}</DialogDescription>
          </DialogHeader>
          <FormField
            label={kind === 'project' ? t('workspace.projectName') : t('workspace.topicName')}
            error={err || undefined}
            hint={<SlugPreview label={label} prefix={kind === 'project' ? 'projects/' : `projects/${project}/topics/`} />}
          >
            <Input
              autoFocus
              value={label}
              onChange={(e) => {
                setLabel(e.target.value)
                setErr(null)
              }}
              placeholder={kind === 'project' ? t('workspace.projectPlaceholder') : t('workspace.topicPlaceholder')}
              autoComplete="off"
            />
          </FormField>
          <FormField label={t('workspace.description')} hint={t('workspace.descriptionHint')}>
            <Input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder={t('workspace.descriptionPlaceholder')} autoComplete="off" />
          </FormField>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={busy}>
              {t('workspace.create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function RenameDialog({
  open,
  onOpenChange,
  title,
  description,
  initial,
  slug,
  prefix,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  title: string
  description?: string
  initial: string
  slug: boolean
  prefix?: string
  onSubmit: (v: string) => Promise<void>
}) {
  const t = useT()
  const [v, setV] = React.useState(initial)
  const [err, setErr] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  React.useEffect(() => {
    if (open) {
      setV(initial)
      setErr(null)
    }
  }, [open, initial])
  const value = slug ? slugify(v) : v.trim()
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (slug ? !SLUG_RE.test(value) : !value) return setErr(t('workspace.nameInvalid'))
    if (value === initial) return onOpenChange(false)
    setBusy(true)
    try {
      await onSubmit(value)
      onOpenChange(false)
    } catch (x) {
      setErr(isApiError(x, 'exists') ? t('workspace.exists') : isApiError(x, 'has_running_sessions') ? t('workspace.hasRunningSessions') : errorMessage(x))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description && <DialogDescription>{description}</DialogDescription>}
          </DialogHeader>
          <FormField label={t('sessions.tree.name')} error={err || undefined} hint={slug ? <SlugPreview label={v} prefix={prefix} /> : undefined}>
            <Input autoFocus value={v} onChange={(e) => setV(e.target.value)} maxLength={slug ? 48 : 120} autoComplete="off" />
          </FormField>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={busy}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
