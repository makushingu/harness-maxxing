// One column = one session (or a "new session" draft). Shell (resize, drag-to-reorder, focus) +
// header (inline title, path, state, model, cost, context, notify, menu) + thread + composer.
import * as React from 'react'
import { useNavigate } from 'react-router'
import {
  Archive,
  ArchiveRestore,
  Bot,
  Bell,
  BellOff,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Copy,
  ExternalLink,
  PictureInPicture2,
  FolderOpen,
  GripVertical,
  Hash,
  ListChecks,
  Minimize2,
  MoreHorizontal,
  Sparkles,
  Trash2,
  Upload,
  X,
  Columns2,
  LayoutGrid,
  PenLine,
  Quote,
  Rows2,
} from 'lucide-react'
import { cn, copyText } from '@/lib/utils'
import { TouchAppButton, TouchSessionsButton } from '@/components/shell/TouchNav'
import { Logo } from '@/components/shell/Logo'
import { useQueryClient } from '@tanstack/react-query'
import { useUI } from '@/stores/ui'
import { openHud } from './Hud'
import { costTip, useCostIsBilled, useResultLine } from './resultLine'
import { useT } from '@/i18n'
import {
  useClaudeStatus,
  useClearQueue,
  useCompactSession,
  useCreateSession,
  useDeleteSession,
  useHandoffSession,
  useMarkSeen,
  usePatchSession,
  useSendMessage,
  useSessionSeeded,
  useSettings,
  useSteerSession,
  useTakeQueue,
  useStopSession,
  useTelegram,
  useWorkspace,
  uploadAttachment,
  sessionsQuery,
} from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
import type { Session } from '@/lib/types'
import {
  Button,
  confirm,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Checkbox,
  Input,
  Label,
  Sensitive,
  Skeleton,
  toast,
  Tooltip,
  TooltipContent,
  TooltipRoot,
  TooltipTrigger,
  useMask,
} from '@/components/ui'
import { Combobox } from '@/components/ui/combobox'
import { TaskBar } from './Tasks'
import { forgetLog, getLog, loadEarlier, loadLog, seedEmptyLog, useLogSelect, useSessionLog, useSessionStream } from './log'
import { PlanChip, PlanNotice } from './Plan'
import { ApprovalCards } from './Approvals'
import { MaxxingControls, MaxxingMeter } from './MaxxingMeter'
import { notifySendFailed, notifySent, useMaxxingEnabled } from './maxxing'
import { MobileTabsSlot, TabsToggle } from './Tabs'
import { AsidePanel, useAside } from './Aside'
import { LayoutPicker } from './LayoutPicker'
import { MIN_W } from './layouts'
import { EASE_OUT, reducedMotion } from '@/lib/presence'
import { canShift, focusComposer, groupAt, MAX_STACK, outboxMove, saveDraft, saveQuotes, seedComposer, useSessionsUI, usePending, usePendingFor, type Col, type OutboxEntry, type Seed } from './store'
import { Thread, type ThreadHandle } from './Thread'
import { Composer, type ComposerHandle } from './Composer'
import { QuotePill } from './Quote'
import { FileMenu } from './FileMenu'
import { ItemContext } from './Items'
import { ContextGauge, ModelPicker, StateBadge } from './Widgets'
import { absTopicDir, fileQuote, findAgent, fmtCost, placeOptions, topicLabel, topicPathOf } from './util'
import { AgentAvatarIcon } from '@/features/agents/Avatar'
import { CONTENT_MIME, contentDragLeave, contentDragOver, contentDrop, useContentDrag, type Dropped } from './contentDrag'

export type ColumnVariant = 'column' | 'solo' | 'mobile'
export { MIN_W }
export const MAX_W = 2000

/** Cell of a session in the strip grid: its grid column, and the whole height or the top / bottom half. */
/** `top`: key of the session at the top of this grid column (its width is saved under that key). */
/** `hidden`: kept mounted but not shown (tabs view: only the focused session is on screen). */
/** Where a session sits in the strip grid: its column, its rank `i` in a stack of `n` (row: 'full' alone, 'top'
 *  first of a stack, 'bottom' any other), its grid lines, the top key of its stack. */
export type Place = { col: number; row: 'full' | 'top' | 'bottom'; i: number; n: number; gridRow: string; top?: string; hidden?: boolean }
/** The strip owns the grid template: handles ask it to resize a column or the row split. */
export const StripContext = React.createContext<{
  startColResize: (key: string, e: React.PointerEvent) => void
  resetColWidth: (key: string) => void
  startRowResize: (e: React.PointerEvent) => void
  /** Columns of the strip grid (two stacked sessions are one): no width handle when there is a single one. */
  columns: number
  resetRowSplit: () => void
} | null>(null)

/** Phone, tabs view: the open sessions' chips, under the app bar of the session's header. */
function MobileTabs() {
  return <>{React.useContext(MobileTabsSlot)}</>
}

/* ---------------------------------------------------------------- shell */
export function ColumnShell({ col, index, count, variant, place, children }: { col: Col; index: number; count: number; variant: ColumnVariant; place?: Place; children: React.ReactNode }) {
  const t = useT()
  const focused = useSessionsUI((s) => s.focused === col.key)
  const focus = useSessionsUI((s) => s.focus)
  const strip = React.useContext(StripContext)
  const ref = React.useRef<HTMLElement>(null)
  const [dropSide, setDropSide] = React.useState<'above' | 'below' | null>(null)
  const isCol = variant === 'column'
  const rank = place?.i ?? 0
  const size = place?.n ?? 1
  const groupKey = place?.top ?? col.key
  // beside the whole strip column: the line runs along every session of it, not only the one under the pointer
  const beside = useSessionsUI((s) => (s.dropBeside?.top === groupKey ? s.dropBeside.side : null))
  // widened by hand to read: the conversation and the composer use the whole width (otherwise 860 px at most)
  // a half column fixes every width of the strip (index.tsx template): no resize handle, no hand width
  const halfShown = useSessionsUI((s) => s.cols.some((c) => c.half))
  const widened = useSessionsUI((s) => isCol && !!strip && strip.columns > 1 && !halfShown && (s.widths[groupKey] ?? 0) > 900)

  const isColDrag = (e: React.DragEvent) => e.dataTransfer.types.includes('application/x-mx-col')
  return (
    <section
      ref={ref}
      data-col={col.key}
      aria-label={`Column ${index + 1}`}
      onFocusCapture={() => isCol && focus(col.key)}
      onPointerDownCapture={() => isCol && focus(col.key)}
      onDragOver={(e) => {
        if (!isCol || !isColDrag(e)) return
        e.preventDefault()
        const r = ref.current!.getBoundingClientRect()
        const ui = useSessionsUI.getState()
        // upper third of a stack's top session / lower third of its last one: stack above / under it, while the
        // column holds fewer than MAX_STACK
        const room = size < MAX_STACK
        const v = room && rank === size - 1 && e.clientY > r.top + r.height * 0.66 ? 'below' : room && rank === 0 && e.clientY < r.top + r.height * 0.34 ? 'above' : null
        setDropSide(v)
        ui.setDropBeside(v ? null : { top: groupKey, side: e.clientX < r.left + r.width / 2 ? 'left' : 'right' })
      }}
      onDragLeave={(e) => {
        if (ref.current?.contains(e.relatedTarget as Node)) return
        setDropSide(null)
        const ui = useSessionsUI.getState()
        if (ui.dropBeside?.top === groupKey) ui.setDropBeside(null)
      }}
      onDrop={(e) => {
        if (!isColDrag(e)) return
        e.preventDefault()
        const key = e.dataTransfer.getData('application/x-mx-col')
        const ui = useSessionsUI.getState()
        const side = dropSide ?? (ui.dropBeside?.top === groupKey ? ui.dropBeside.side : null)
        setDropSide(null)
        ui.setDropBeside(null)
        if (!key || key === col.key) return
        if (side === 'below') return ui.stack(key, col.key)
        if (side === 'above') return ui.stackAbove(key, col.key)
        // beside the whole strip column (a stack stays a stack)
        ui.moveBeside(key, col.key, side ?? 'right')
      }}
      // In the strip, the grid places the session (its width comes from the grid template, see index.tsx).
      style={{
        ...(isCol && place && { gridColumn: place.col, gridRow: place.gridRow }),
        ...(widened && ({ '--mx-read': 'none' } as React.CSSProperties)),
      }}
      className={cn(
        'relative flex min-h-0 min-w-0 flex-col bg-background',
        isCol && 'border-r',
        isCol && rank < size - 1 && 'border-b',
        isCol && count > 1 && focused && 'shadow-[inset_0_2px_0_0_var(--primary)]',
        !isCol && 'h-full w-full',
        // tabs view, a session not in front: kept laid out under the shown one but skipped (globals.css), so coming back
        // to it only repaints - no style and layout of its whole thread, nothing re-measured, its scroll kept
        place?.hidden && 'mx-tab-off',
      )}
    >
      {children}
      {dropSide === 'below' || dropSide === 'above' ? (
        <span aria-hidden className={cn('pointer-events-none absolute inset-x-2 z-20 h-1/3 rounded-lg border-2 border-dashed border-primary bg-primary/10 animate-in', dropSide === 'below' ? 'bottom-2' : 'top-2')} />
      ) : (
        beside && <span aria-hidden className={cn('pointer-events-none absolute inset-y-0 z-20 w-0.5 bg-primary', beside === 'left' ? 'left-0' : 'right-0')} />
      )}
      {isCol && strip && strip.columns > 1 && !halfShown && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={t('shell.resize')}
          onPointerDown={(e) => strip.startColResize(place?.top ?? col.key, e)}
          onDoubleClick={() => strip.resetColWidth(place?.top ?? col.key)}
          // Just past the right edge (never over the column's own scrollbar); the strip keeps an 8 px gutter at its
          // end for the last column's handle. Only a thin line on the border lights up.
          className="absolute inset-y-0 left-full z-10 -ml-px w-2 cursor-col-resize touch-none after:absolute after:inset-y-0 after:left-0 after:w-[3px] after:transition-colors hover:after:bg-primary/40 active:after:bg-primary/60"
        />
      )}
      {isCol && strip && size === 2 && rank === 1 && (
        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label={t('shell.resizeRows')}
          onPointerDown={strip.startRowResize}
          onDoubleClick={strip.resetRowSplit}
          className="absolute inset-x-0 -top-1 z-10 h-2 cursor-row-resize touch-none after:absolute after:inset-x-0 after:top-1 after:h-[3px] after:transition-colors hover:after:bg-primary/40 active:after:bg-primary/60"
        />
      )}
    </section>
  )
}

/** A session can go under the column on its left when that column holds one session only. */
function canStackUnderPrevious(key: string) {
  const cols = useSessionsUI.getState().cols
  const i = cols.findIndex((c) => c.key === key)
  if (i < 1) return false
  // the column on the left holds fewer than MAX_STACK
  const [start, end] = groupAt(cols, i - 1)
  return end - start + 1 < MAX_STACK
}

/** Where three sessions share a column, only the focused one shows its composer (the others fold it into a thin
 *  "Write…" bar, smoothly); a click anywhere in the session focuses it and unfolds its composer. Two stacked
 *  sessions both keep theirs (FEU: having to click first was in the way). */
function StackedComposer({ colKey, stacked, children }: { colKey: string; stacked: boolean; children: React.ReactNode }) {
  const t = useT()
  const focused = useSessionsUI((s) => s.focused === colKey)
  const open = !stacked || focused
  // The height changes at once and only the box fades / rises in: animating the height re-laid and repainted the
  // whole conversation above it on every frame. Hidden (not unmounted): the draft and attachments stay.
  const box = React.useRef<HTMLDivElement>(null)
  const wasOpen = React.useRef(open)
  React.useLayoutEffect(() => {
    if (open && !wasOpen.current && !reducedMotion())
      box.current?.animate([{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }], { duration: 160, easing: EASE_OUT })
    wasOpen.current = open
  }, [open])
  return (
    <div className="shrink-0">
      <div ref={box} hidden={!open} inert={!open || undefined}>
        {children}
      </div>
      {!open && (
        <button
          type="button"
          onClick={() => {
            useSessionsUI.getState().focus(colKey)
            requestAnimationFrame(() => focusComposer(colKey))
          }}
          className="mx-3 mb-2 flex h-8 w-[calc(100%-1.5rem)] items-center gap-2 rounded-lg border bg-muted/40 px-3 text-left text-[13px] text-muted-foreground transition-colors animate-in hover:bg-accent hover:text-foreground"
          data-testid="composer-folded"
        >
          <PenLine className="size-3.5 shrink-0" />
          {t('sessions.grid.write')}
        </button>
      )}
    </div>
  )
}

/** Content of another session dropped here (contentDrag.ts): into this column's composer as a quote, never sent. */
function quoteDropped(colKey: string, composer: ComposerHandle | null, d: Dropped) {
  if (!composer) return
  composer.quote(d.kind === 'file' ? fileQuote(d.path) : d.text)
  window.getSelection()?.removeAllRanges()
  // a folded composer (two sessions in a column) unfolds with the focus
  useSessionsUI.getState().focus(colKey)
  requestAnimationFrame(() => composer.focus())
}

/** While content of another session is dragged: this column is a drop zone (stronger under the pointer). Only these
 *  overlays follow the drag, not the threads. */
function ContentDropOverlay({ colKey, sid }: { colKey: string; sid: string | null }) {
  const t = useT()
  const state = useContentDrag((s) => (!s.drag || s.drag.from === sid ? null : s.over === colKey ? 'over' : 'on'))
  if (!state) return null
  return (
    <div
      className={cn(
        'pointer-events-none absolute inset-2 z-30 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed text-sm font-medium transition-colors',
        state === 'over' ? 'border-primary bg-background/95' : 'border-primary/40 bg-background/60 text-muted-foreground',
      )}
      data-testid="content-drop"
      data-over={state === 'over' || undefined}
    >
      <Quote className="size-6 text-primary" />
      {t('drag.dropToQuote')}
    </div>
  )
}

/** Drag handle for reordering (header). Holding it still shows the ready-made layouts; dragging it shows the
 *  layouts bar at the top of the strip (drop the session on a zone). */
function DragGrip({ colKey }: { colKey: string }) {
  const count = useSessionsUI((s) => s.cols.length)
  const fromMenu = useSessionsUI((s) => s.layoutPicker === colKey)
  const ended = React.useRef(false)
  return (
    <LayoutPicker count={count} colKey={colKey} holdOpens open={fromMenu} onOpenChange={(v) => !v && useSessionsUI.getState().setLayoutPicker(null)}>
      <span
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData('application/x-mx-col', colKey)
          e.dataTransfer.effectAllowed = 'move'
          // the header only: a snapshot of the whole column (its conversation) is slow to take
          const head = (e.currentTarget as HTMLElement).closest('header') as HTMLElement | null
          if (head) e.dataTransfer.setDragImage(head, 40, 20)
          // after the drag has started (changing the page during dragstart can cancel it) - unless it already ended
          ended.current = false
          requestAnimationFrame(() => !ended.current && useSessionsUI.getState().setDragging(colKey))
        }}
        onDragEnd={() => {
          ended.current = true
          useSessionsUI.getState().setDragging(null)
        }}
        className="-ml-1 flex h-8 w-4 shrink-0 cursor-grab items-center justify-center text-muted-foreground/60 hover:text-foreground active:cursor-grabbing"
        aria-hidden
        data-testid="col-grip"
      >
        <GripVertical className="size-3.5" />
      </span>
    </LayoutPicker>
  )
}

/* ---------------------------------------------------------------- session column */
/** The thread with its own subscription to the log (the column opens the stream). */
// Memo: a column re-renders when it gains or loses the focus (and on every session poll); its thread only when its own
// props change (callbacks below are stable per session).
const LiveThread = React.memo(
  React.forwardRef<ThreadHandle, Omit<React.ComponentProps<typeof Thread>, 'log'> & { sid: string }>(function LiveThread({ sid, ...props }, ref) {
    return <Thread ref={ref} log={useSessionLog(sid, false)} {...props} />
  }),
)

/** A stacked session shorter than this keeps a one-line header (see ColumnHeader `slim`). */
const SLIM_BELOW = 560
const QUEUE_PREVIEW_CHARS = 280 // server/maxxing/sessions/service.py: a queued text is cut there in the session list

/** True while the session holding `head` is stacked with others and short: its header drops what is rarely used. */
function useSlimHeader(head: React.RefObject<HTMLElement | null>, stacked: boolean) {
  const [slim, setSlim] = React.useState(false)
  React.useLayoutEffect(() => {
    const box = head.current?.parentElement
    if (!stacked || !box) return setSlim(false)
    const fit = () => setSlim(box.clientHeight < SLIM_BELOW)
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(box)
    return () => ro.disconnect()
  }, [head, stacked])
  return slim
}

/** `agentRun`: a run of an agent shown on the Agents page - it stays where it is (no move, archive or delete: the
 *  agent manages its runs, archiving them by itself), and the archived banner is not shown. */
export function SessionColumn({ col, sid, variant, index, count, place, agentRun }: { col: Col; sid: string; variant: ColumnVariant; index: number; count: number; place?: Place; agentRun?: boolean }) {
  const t = useT()
  const navigate = useNavigate()
  const { data: session, isError, error } = useSessionSeeded(sid)
  // The stream lives here; only the thread re-renders on new events (LiveThread), not the column and its composer.
  useSessionStream(sid)
  const deleted = useLogSelect(sid, (st) => st.deleted)
  const pending = usePendingFor(sid)
  const { data: ws } = useWorkspace()
  const { data: settings } = useSettings()
  const { data: claude } = useClaudeStatus()
  const { data: tg } = useTelegram()
  const focused = useSessionsUI((s) => s.focused === col.key)
  const onRetry = React.useCallback(() => void loadLog(sid, true), [sid])
  const onLoadEarlier = React.useCallback(() => void loadEarlier(sid), [sid])
  const close = useSessionsUI((s) => s.close)
  const becomeSession = useSessionsUI((s) => s.becomeSession)
  const patch = usePatchSession()
  const send = useSendMessage()
  const stop = useStopSession()
  const clearQueue = useClearQueue()
  const queuedPending = React.useMemo(() => pending.filter((p) => p.queued), [pending])
  const steer = useSteerSession()
  // Steer accepted: "steering…" until the queued messages start (queue empty) or 20 s at most.
  const [steerPending, setSteerPending] = React.useState(false)
  React.useEffect(() => {
    if (!steerPending) return
    if (!session?.queue) {
      setSteerPending(false)
      return
    }
    const id = setTimeout(() => setSteerPending(false), 20_000)
    return () => clearTimeout(id)
  }, [steerPending, session?.queue])
  const takeQueue = useTakeQueue()
  const aside = useAside(sid)
  // Side question: the waiting messages are taken back and asked apart (the running turn goes on).
  const onAsk = async () => {
    let r: Awaited<ReturnType<typeof takeQueue.mutateAsync>>
    try {
      r = await takeQueue.mutateAsync(sid)
    } catch {
      return // already shown as a toast; the messages stay in the queue
    }
    usePending.getState().clearQueued(sid)
    aside.start(r.messages.map((m) => [m.text, ...m.attachments.map((a) => `- ${a}`)].filter(Boolean).join('\n')).join('\n\n'))
  }
  const compact = useCompactSession()
  const handoff = useHandoffSession()
  const del = useDeleteSession()
  const seen = useMarkSeen()
  const thread = React.useRef<ThreadHandle>(null)
  const composer = React.useRef<ComposerHandle>(null)
  const body = React.useRef<HTMLDivElement>(null)
  const [dragFiles, setDragFiles] = React.useState(false)

  const notFound = (isError && isApiError(error) && error.status === 404) || deleted
  const running = session?.state === 'running'
  const path = session?.path ?? ''
  // Message actions of the thread: Edit (a stopped message back into this composer), New session from a message
  // (a new session of the same topic, its composer filled; the URL opens it, on a phone too).
  const onEdit = React.useCallback((seed: Seed) => composer.current?.bringBack(seed), [])
  const onFork = React.useCallback(
    (seed: Seed) => {
      seedComposer(`new:${path}`, seed)
      navigate(`/sessions?path=${encodeURIComponent(path)}&new=1`, { state: { mxPushed: true } })
    },
    [path, navigate],
  )

  // Mark seen while this column is the focused one and the tab is visible.
  const [visible, setVisible] = React.useState(() => document.visibilityState === 'visible')
  React.useEffect(() => {
    const on = () => setVisible(document.visibilityState === 'visible')
    document.addEventListener('visibilitychange', on)
    return () => document.removeEventListener('visibilitychange', on)
  }, [])
  const seenFor = React.useRef<number>(0)
  React.useEffect(() => {
    if (!session || !session.unread || !visible) return
    if (!(focused || variant !== 'column' || count === 1)) return
    if (seenFor.current === session.updated) return
    seenFor.current = session.updated
    seen.mutate(session.id)
  }, [session, focused, visible, variant, count]) // eslint-disable-line react-hooks/exhaustive-deps

  // Queued messages of this tab that the server no longer holds (cleared elsewhere) disappear.
  const trimQueued = usePending((s) => s.trimQueued)
  React.useEffect(() => {
    if (session) trimQueued(sid, session.queue)
  }, [session?.queue, sid, trimQueued]) // eslint-disable-line react-hooks/exhaustive-deps

  const onSend = async (text: string, attachments: string[], clientId?: string) => {
    const add = usePending.getState().add
    const remove = usePending.getState().remove
    const lid = add(sid, { text, attachments, queued: running })
    thread.current?.scrollToBottom()
    notifySent(sid)
    try {
      const r = await send.mutateAsync({ id: sid, text, attachments, client_id: clientId })
      if (r.queued !== running) {
        remove(sid, lid)
        add(sid, { text, attachments, queued: r.queued })
      }
      return true
    } catch {
      remove(sid, lid)
      notifySendFailed(sid)
      return false
    }
  }

  // Sent by a previous page load that went away before the answer: did the server get it? (a user event or a
  // queued message carrying its id; an entry stored before ids were sent: the same text since it was sent).
  const sessionNow = React.useRef(session)
  sessionNow.current = session
  const checkSent = React.useCallback(
    async (left: OutboxEntry[]) => {
      await loadLog(sid)
      for (let i = 0; i < 40 && !sessionNow.current; i++) await new Promise((r) => setTimeout(r, 250))
      const st = getLog(sid)
      if (st.status !== 'ready' || !sessionNow.current) return null // unknown: kept for the next load
      const queued = sessionNow.current.queue_items || []
      const queue = queued.map((q) => q.text)
      const sent = sessionNow.current.sent_items || [] // held behind a summary: received, not in the log yet
      return left.filter((e) => {
        if (e.tagged)
          return (
            !st.items.some((it) => it.kind === 'user' && it.ev.client_ids?.includes(e.id)) &&
            !queued.some((q) => q.client_ids?.includes(e.id)) &&
            !sent.some((q) => q.client_ids?.includes(e.id))
          )
        const text = e.text.trim()
        if (st.items.some((it) => it.kind === 'user' && (it.ev.at ?? Infinity) >= e.at / 1000 - 60 && it.ev.text.trim() === text)) return false
        // the server cuts a queued text at QUEUE_PREVIEW_CHARS: only a cut one is compared on its start
        return !queue.some((q) => q && (q.length >= QUEUE_PREVIEW_CHARS ? text.startsWith(q.trim()) : text === q.trim()))
      })
    },
    [sid],
  )

  // Voice message sent directly: an optimistic voice bubble while the recording uploads, then sent with `voice`.
  const onSendVoice = async (file: File) => {
    const { add, remove } = usePending.getState()
    const lid = add(sid, { text: '', attachments: [], queued: running, voice: true })
    thread.current?.scrollToBottom()
    try {
      const up = await uploadAttachment(path, file)
      const r = await send.mutateAsync({ id: sid, text: '', voice: up.path })
      if (r.queued !== running) {
        remove(sid, lid)
        add(sid, { text: '', attachments: [], queued: r.queued, voice: true })
      }
      return true
    } catch (e) {
      remove(sid, lid)
      toast.error(errorMessage(e))
      return false
    }
  }

  const onStop = () =>
    stop.mutate(sid, {
      onSuccess: () => usePending.getState().clearQueued(sid),
    })

  const tgLinked = !!tg?.configured && !!tg?.chat
  const authReason = claude && !claude.auth.ok ? t(claude.auth.method ? 'sessions.composer.authExpired' : 'sessions.composer.noAuth') : null
  const dir = absTopicDir(ws, path)

  const qc = useQueryClient()
  const hudOn = useUI((s) => s.hud)
  const hud = () => {
    const go = (path: string) => {
      navigate(path)
      window.focus()
    }
    openHud(sid, qc, go).then(
      (ok) => !ok && toast.error(t('sessions.popupBlocked')),
      (e) => toast.error(errorMessage(e)),
    )
  }

  const detach = () => {
    const w = window.open(`/sessions/solo/${sid}`, `mx-solo-${sid}`, 'popup,width=560,height=860')
    if (w) close(col.key)
    else toast.error(t('sessions.popupBlocked'))
  }

  const head = React.useRef<HTMLElement>(null)
  const slim = useSlimHeader(head, variant === 'column' && !!place && place.row !== 'full')
  const actions = {
    rename: (title: string) => patch.mutate({ id: sid, title }),
    model: (model: string) => patch.mutate({ id: sid, model }),
    notify: () => session && patch.mutate({ id: sid, notify: !session.notify }),
    archive: () =>
      session &&
      patch.mutate(
        { id: sid, archived: !session.archived },
        { onSuccess: (s) => toast.success(s.archived ? t('sessions.archived') : t('sessions.unarchived')) },
      ),
    compact: () => compact.mutate(sid, { onSuccess: () => toast.success(t('sessions.compacting')) }),
    handoff: async () => {
      if (!(await confirm({ title: t('sessions.handoff.title'), description: t('sessions.handoff.desc'), confirmText: t('sessions.handoff.confirm') }))) return
      handoff.mutate(sid, {
        onSuccess: (s) => {
          seedEmptyLog(s.id)
          becomeSession(col.key, s.id)
          toast.success(t('sessions.handoff.done'))
        },
      })
    },
    del: async () => {
      if (!session) return
      const ok = await confirm({ title: t('sessions.delete.title'), description: t('sessions.delete.desc'), destructive: true, confirmText: t('common.delete') })
      if (!ok) return
      del.mutate(sid, {
        onSuccess: () => {
          close(col.key)
          forgetLog(sid)
          saveDraft(sid, '')
          saveQuotes(sid, [])
          toast.success(t('sessions.delete.done'))
        },
      })
    },
  }

  // (a picture dragged from a thread carries a file too: that is a content drag)
  const isFileDrag = (e: React.DragEvent) => e.dataTransfer.types.includes('Files') && !e.dataTransfer.types.includes(CONTENT_MIME)
  return (
    <ColumnShell col={col} index={index} count={count} variant={variant} place={place}>
      <div
        ref={body}
        className="relative flex min-h-0 flex-1 flex-col"
        onDragEnter={(e) => isFileDrag(e) && setDragFiles(true)}
        onDragOver={(e) => {
          if (contentDragOver(e, col.key, sid)) return
          if (isFileDrag(e)) e.preventDefault()
        }}
        onDragLeave={(e) => {
          contentDragLeave(e, col.key)
          if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragFiles(false)
        }}
        onDrop={(e) => {
          const d = contentDrop(e, sid)
          if (d !== undefined) return d && quoteDropped(col.key, composer.current, d)
          if (!isFileDrag(e)) return
          e.preventDefault()
          setDragFiles(false)
          composer.current?.addFiles(Array.from(e.dataTransfer.files))
        }}
      >
        <ColumnHeader
          col={col}
          variant={variant}
          session={session}
          rootLabel={t('sessions.root')}
          onClose={() => close(col.key)}
          fixedPlace={agentRun}
          tgLinked={tgLinked}
          headRef={head}
          slim={slim}
          menu={
            <DropdownMenu>
              <Tooltip content={t('common.more')}>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon-sm" aria-label={t('common.more')} disabled={!session}>
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
              </Tooltip>
              <DropdownMenuContent
                align="end"
                className="w-60"
                // "Layouts…": the focus goes to the picker, not back to this button (that would close the picker)
                onCloseAutoFocus={(e) => useSessionsUI.getState().layoutPicker === col.key && e.preventDefault()}
              >
                {(variant === 'mobile' || slim) && (
                  <>
                    {/* Touch layout and short stacked session: the header keeps room for the title - Telegram lives
                        here (on a phone plan mode is next to the title). */}
                    {slim && (
                      <DropdownMenuCheckboxItem checked={!!session?.plan_mode} disabled={!session} onSelect={() => session && patch.mutate({ id: sid, plan_mode: !session.plan_mode })}>
                        {t('plan.toggle')}
                      </DropdownMenuCheckboxItem>
                    )}
                    <DropdownMenuCheckboxItem checked={!!session?.notify} disabled={!session || !tgLinked} onSelect={actions.notify}>
                      {t('sessions.notify.label')}
                    </DropdownMenuCheckboxItem>
                    <DropdownMenuSeparator />
                  </>
                )}
                <DropdownMenuItem disabled={running || !session?.turns} onSelect={actions.compact}>
                  <Minimize2 /> {t('sessions.menu.compact')}
                </DropdownMenuItem>
                <DropdownMenuItem disabled={running || !session?.turns} onSelect={actions.handoff}>
                  <Sparkles /> {t('sessions.menu.handoff')}
                </DropdownMenuItem>
                {!agentRun && (
                  <DropdownMenuItem onSelect={actions.archive}>
                    {session?.archived ? <ArchiveRestore /> : <Archive />} {session?.archived ? t('sessions.menu.unarchive') : t('sessions.menu.archive')}
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={!dir} onSelect={() => dir && navigate(`/files?path=${encodeURIComponent(dir)}`)}>
                  <FolderOpen /> {t('sessions.menu.openFolder')}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => copyText(sid).then((ok) => ok && toast.success(t('sessions.menu.idCopied')))}>
                  <Copy /> {t('sessions.menu.copyId')}
                </DropdownMenuItem>
                {hudOn && variant !== 'mobile' && (
                  <DropdownMenuItem onSelect={hud}>
                    <PictureInPicture2 /> {t('hud.open')}
                  </DropdownMenuItem>
                )}
                {variant === 'column' && (
                  <>
                    <DropdownMenuItem onSelect={detach}>
                      <ExternalLink /> {t('sessions.menu.detach')}
                    </DropdownMenuItem>
                    {index > 0 && (
                      col.below ? (
                        <DropdownMenuItem onSelect={() => useSessionsUI.getState().unstack(col.key)}>
                          <Columns2 /> {t('sessions.grid.unstack')}
                        </DropdownMenuItem>
                      ) : (
                        <DropdownMenuItem
                          disabled={!canStackUnderPrevious(col.key)}
                          onSelect={() => {
                            const cols = useSessionsUI.getState().cols
                            const i = cols.findIndex((c) => c.key === col.key)
                            // under the last session of the strip column on the left
                            if (i > 0) useSessionsUI.getState().stack(col.key, cols[i - 1].key)
                          }}
                        >
                          <Rows2 /> {t('sessions.grid.stack')}
                        </DropdownMenuItem>
                      )
                    )}
                    {count > 1 && (
                      <>
                        <DropdownMenuItem onSelect={() => useSessionsUI.getState().setLayoutPicker(col.key)}>
                          <LayoutGrid /> {t('sessions.layout.menu')}
                        </DropdownMenuItem>
                        <DropdownMenuItem disabled={!canShift(useSessionsUI.getState().cols, col.key, -1)} onSelect={() => useSessionsUI.getState().shift(col.key, -1)}>
                          <ChevronLeft /> {t('sessions.menu.moveLeft')}
                        </DropdownMenuItem>
                        <DropdownMenuItem disabled={!canShift(useSessionsUI.getState().cols, col.key, 1)} onSelect={() => useSessionsUI.getState().shift(col.key, 1)}>
                          <ChevronRight /> {t('sessions.menu.moveRight')}
                        </DropdownMenuItem>
                      </>
                    )}
                  </>
                )}
                {!agentRun && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem destructive onSelect={actions.del}>
                      <Trash2 /> {t('sessions.menu.delete')}
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          }
          onRename={actions.rename}
          onHud={hudOn ? hud : undefined}
          onPlan={() => session && patch.mutate({ id: sid, plan_mode: !session.plan_mode })}
          onNotify={actions.notify}
        />
        {session?.archived && !agentRun && (
          <div className="flex items-center gap-2 border-b bg-muted/40 px-4 py-1.5 text-xs text-muted-foreground">
            <Archive className="size-3.5" /> {t('sessions.archivedBanner')}
            <Button size="sm" variant="link" className="ml-auto h-auto text-xs" onClick={actions.archive}>
              {t('sessions.menu.unarchive')}
            </Button>
          </div>
        )}
        <ItemContext.Provider value={React.useMemo(() => ({ filesRoot: settings?.files_root || null, models: claude?.models, running, tz: settings?.timezone, topicDir: dir, wsRoot: ws?.root || null }), [settings?.files_root, settings?.timezone, claude?.models, running, dir, ws?.root])}>
          {notFound ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-sm text-muted-foreground">
              {t('sessions.deleted')}
              <Button size="sm" variant="outline" onClick={() => close(col.key)}>
                {t('sessions.closeColumn')}
              </Button>
            </div>
          ) : (
            <LiveThread ref={thread} sid={sid} session={session} pending={pending} onRetry={onRetry} onLoadEarlier={onLoadEarlier} onEdit={onEdit} onFork={path ? onFork : undefined} />
          )}
        </ItemContext.Provider>
        {session?.state === 'error' && session.error && !running && (
          <div className="mx-auto w-full max-w-(--mx-read,860px) px-3">
            <div role="alert" className="rounded-md bg-destructive/10 px-3 py-1.5 text-xs text-destructive">
              <Sensitive>{session.error}</Sensitive>
            </div>
          </div>
        )}
        {!notFound && (
          <QuotePill
            scope={body}
            onQuote={(text) => {
              composer.current?.quote(text)
              window.getSelection()?.removeAllRanges()
              composer.current?.focus()
            }}
          />
        )}
        {!notFound && (
          <FileMenu
            scope={body}
            onQuote={(path) => {
              composer.current?.quote(fileQuote(path))
              composer.current?.focus()
            }}
          />
        )}
        {!notFound && aside.aside && <AsidePanel aside={aside.aside} onClose={aside.close} />}
        {!notFound && <ApprovalCards session={session} />}
        {!notFound && <TaskBar sid={sid} running={running} />}
        {!notFound && (
          <StackedComposer colKey={col.key} stacked={!!place && place.n >= 3}>
          <Composer
            ref={composer}
            colKey={col.key}
            maxRows={place && place.row !== 'full' ? 4 : 12}
            draftKey={sid}
            placeholder={session?.plan_mode ? t(session.plan_ready ? 'plan.placeholderAdjust' : 'plan.placeholder') : undefined}
            notice={session?.plan_ready && !running ? <PlanNotice session={session} onAdjust={() => composer.current?.focus()} /> : null}
            topicPath={path}
            running={running}
            disabledReason={authReason || (!session ? t('sessions.composer.loading') : null)}
            queueCount={session?.queue || 0}
            queued={queuedPending}
            queueItems={session?.queue_items}
            onClearQueue={() => clearQueue.mutateAsync(sid).then(() => usePending.getState().clearQueued(sid))}
            onSteer={() =>
              steer.mutate(sid, {
                onSuccess: (r) => {
                  if (r.steered) {
                    setSteerPending(true)
                    if (!r.interrupted) toast.info(t('sessions.queue.steerAfter'))
                  }
                  else toast.info(t('sessions.queue.steerNothing'), t('sessions.queue.steerNothingDesc'))
                },
              })
            }
            steerPending={steerPending}
            onTakeQueue={async () => {
              const r = await takeQueue.mutateAsync(sid)
              usePending.getState().clearQueued(sid)
              return r.messages
            }}
            steering={steer.isPending}
            onAsk={() => void onAsk()}
            asking={takeQueue.isPending || aside.pending}
            clearingQueue={clearQueue.isPending}
            onSend={onSend}
            checkSent={checkSent}
            onSendVoice={onSendVoice}
            onStop={onStop}
            stopping={stop.isPending}
            autoFocus={variant !== 'mobile'}
            toolbar={
              session ? (
                <>
                  <ModelPicker chosen={session.model} real={session.real_model} contextTokens={session.context_tokens} onChange={actions.model} />
                  {session.plan_mode && <PlanChip session={session} />}
                </>
              ) : (
                <Skeleton className="h-6 w-24" />
              )
            }
          />
          </StackedComposer>
        )}
        {dragFiles && (
          <div className="pointer-events-none absolute inset-2 z-30 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-primary bg-background/95 text-sm font-medium">
            <Upload className="size-6 text-primary" />
            {t('sessions.dropToAttach')}
          </div>
        )}
        <ContentDropOverlay colKey={col.key} sid={sid} />
      </div>
    </ColumnShell>
  )
}

/* ---------------------------------------------------------------- header */
function ColumnHeader({
  col,
  variant,
  session,
  rootLabel,
  onClose,
  menu,
  onRename,
  onNotify,
  onHud,
  onPlan,
  tgLinked,
  headRef,
  slim,
  fixedPlace,
}: {
  col: Col
  variant: ColumnVariant
  session: Session | undefined
  rootLabel: string
  onClose: () => void
  menu: React.ReactNode
  onRename: (title: string) => void
  onNotify: () => void
  onHud?: () => void
  onPlan?: () => void
  tgLinked: boolean
  /** The place is shown, not a picker (a run of an agent stays in the agent's folder). */
  fixedPlace?: boolean
  headRef?: React.Ref<HTMLElement>
  /** Short stacked session: one line (title, state, context, menu, close); plan mode and Telegram show only
   *  while on and are in the menu, the picture-in-picture is in the menu, topic and cost go. */
  slim?: boolean
}) {
  const t = useT()
  const billed = useCostIsBilled()
  const showCost = !useResultLine().hidden.includes('cost')
  const notifyTip = !tgLinked ? t('sessions.notify.unavailable') : session?.notify ? t('sessions.notify.on') : t('sessions.notify.off')
  const maxxing = useMaxxingEnabled()
  if (variant === 'mobile')
    // phone / tablet: app bar (☰ logo ⋯ ⊞), then the session's title, then its topic and what it used
    return (
      <header data-kbd-short-hide="" className="relative shrink-0 border-b bg-background px-3 pb-2 pt-[calc(0.25rem+var(--safe-top))]">
        {maxxing && <MaxxingMeter strip />}
        <div className="flex h-11 min-w-0 items-center gap-1">
          <TouchSessionsButton className="-ml-2" />
          <Logo className="min-w-0 flex-1 gap-2 [&_img]:size-6" nameClassName={maxxing ? 'max-[479px]:sr-only' : undefined} />
          <div className="flex shrink-0 items-center">
            <TabsToggle compact />
            {maxxing && <MaxxingControls compact />}
            {menu}
            <TouchAppButton className="-mr-2" />
          </div>
        </div>
        <MobileTabs />
        <div className="flex min-h-8 min-w-0 items-center gap-2">
          {session ? <InlineTitle value={session.title} onSave={onRename} className="text-[17px] font-semibold" /> : <Skeleton className="h-5 w-48" />}
          {session && <StateBadge session={session} />}
          {onPlan && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t('plan.toggle')}
              aria-pressed={!!session?.plan_mode}
              disabled={!session}
              onClick={onPlan}
              className={cn('-mr-1 ml-auto shrink-0 pointer-coarse:size-10', session?.plan_mode && 'bg-primary/12 text-primary hover:bg-primary/20 hover:text-primary')}
            >
              <ListChecks />
            </Button>
          )}
        </div>
        <div data-kbd-hide="" className="mt-0.5 flex h-6 min-w-0 items-center gap-2 text-[13px] text-muted-foreground">
          {session ? (
            <>
              <MoveSessionPicker session={session} rootLabel={rootLabel} locked={fixedPlace} />
              {session.source === 'cron' && <Clock className="size-3.5 shrink-0" aria-label={t('sessions.source.cron')} />}
              <span className="ml-auto flex shrink-0 items-center gap-3 tabular-nums">
                {session.cost_usd > 0 && showCost && (
                  <Tooltip content={<span className="block max-w-72 whitespace-normal">{costTip(t, billed, session.turns)}</span>}>
                    <span tabIndex={0} className="rounded outline-none focus-visible:ring-2 focus-visible:ring-ring">
                      <Sensitive length={4}>{fmtCost(session.cost_usd)}</Sensitive>
                    </span>
                  </Tooltip>
                )}
                <ContextGauge ring tokens={session.context_tokens} window={session.context_window} model={session.model} realModel={session.real_model} />
              </span>
            </>
          ) : (
            <Skeleton className="h-3.5 w-32" />
          )}
        </div>
      </header>
    )
  return (
    <header ref={headRef} data-col-head data-kbd-short-hide="" className={cn('shrink-0 border-b bg-background/95 px-3', slim ? 'py-0.5' : 'py-1.5', variant !== 'column' && 'pt-[calc(0.375rem+var(--safe-top))]')}>
      <div className="flex h-9 min-w-0 items-center gap-1 pointer-coarse:h-10">
        {variant === 'column' && <DragGrip colKey={col.key} />}
        {session ? <InlineTitle value={session.title} onSave={onRename} /> : <Skeleton className="h-4 w-40" />}
        {session && <StateBadge session={session} />}
        <div className="ml-auto flex shrink-0 items-center">
          {slim && session && (
            <span className="mr-1 flex">
              <ContextGauge ring tokens={session.context_tokens} window={session.context_window} model={session.model} realModel={session.real_model} />
            </span>
          )}
          {onHud && !slim && (
            <Tooltip content={t('hud.open')}>
              <Button variant="ghost" size="icon-sm" aria-label={t('hud.open')} onClick={onHud}>
                <PictureInPicture2 />
              </Button>
            </Tooltip>
          )}
          {onPlan && (!slim || session?.plan_mode) && (
            <Tooltip content={session?.plan_mode ? t('plan.toggleOff') : t('plan.toggleOn')}>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t('plan.toggle')}
                aria-pressed={!!session?.plan_mode}
                disabled={!session}
                onClick={onPlan}
                className={cn(session?.plan_mode && 'bg-primary/12 text-primary hover:bg-primary/20 hover:text-primary')}
              >
                <ListChecks />
              </Button>
            </Tooltip>
          )}
          {(!slim || session?.notify) && (
          <Tooltip content={notifyTip}>
            <span>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={notifyTip}
                aria-pressed={!!session?.notify}
                disabled={!session || !tgLinked}
                onClick={onNotify}
                className={cn(session?.notify && 'text-primary')}
              >
                {session?.notify ? <Bell /> : <BellOff />}
              </Button>
            </span>
          </Tooltip>
          )}
          {menu}
          {variant === 'column' && (
            <Tooltip content={t('sessions.closeColumn')}>
              <Button variant="ghost" size="icon-sm" aria-label={t('sessions.closeColumn')} onClick={onClose}>
                <X />
              </Button>
            </Tooltip>
          )}
        </div>
      </div>
      <div data-kbd-hide="" className={cn('flex h-5 min-w-0 items-center gap-2 text-[11px] text-muted-foreground', slim && 'hidden')}>
        {session ? (
          <>
            <MoveSessionPicker session={session} rootLabel={rootLabel} locked={fixedPlace} />
            {session.source === 'cron' && (
              <Tooltip content={t('sessions.source.cron')}>
                <span className="inline-flex shrink-0 items-center"><Clock className="size-3" /></span>
              </Tooltip>
            )}
            <span className="ml-auto flex shrink-0 items-center gap-2.5 tabular-nums">
              {session.cost_usd > 0 && showCost && (
                <Tooltip content={<span className="block max-w-72 whitespace-normal">{costTip(t, billed, session.turns)}</span>}>
                  <span tabIndex={0} className="rounded outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    <Sensitive length={4}>{fmtCost(session.cost_usd)}</Sensitive>
                  </span>
                </Tooltip>
              )}
              <ContextGauge tokens={session.context_tokens} window={session.context_window} model={session.model} realModel={session.real_model} />
            </span>
          </>
        ) : (
          <Skeleton className="h-3 w-28" />
        )}
      </div>
    </header>
  )
}

function InlineTitle({ value, onSave, className }: { value: string; onSave: (v: string) => void; className?: string }) {
  const t = useT()
  const mask = useMask()
  const [editing, setEditing] = React.useState(false)
  const [draft, setDraft] = React.useState(value)
  const input = React.useRef<HTMLInputElement>(null)
  React.useEffect(() => {
    if (!editing) setDraft(value)
  }, [value, editing])
  React.useEffect(() => {
    if (editing) input.current?.select()
  }, [editing])
  const commit = () => {
    setEditing(false)
    const v = draft.trim()
    if (v && v !== value) onSave(v)
  }
  if (editing)
    return (
      <input
        ref={input}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') {
            setDraft(value)
            setEditing(false)
          }
        }}
        aria-label={t('sessions.rename')}
        maxLength={120}
        className={cn('h-7 min-w-0 flex-1 rounded-md border border-input bg-transparent px-2 text-sm font-semibold outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25', className)}
      />
    )
  return (
    <Tooltip content={t('sessions.renameHint')}>
      <button
        type="button"
        onClick={() => setEditing(true)}
        className={cn('min-w-0 truncate rounded px-1 text-left text-sm font-semibold hover:bg-accent pointer-coarse:h-10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none', className)}
        aria-label={`${t('sessions.rename')}: ${mask(value, 8)}`}
      >
        <Sensitive length={10}>{value}</Sensitive>
      </button>
    </Tooltip>
  )
}

/* ---------------------------------------------------------------- new session column */
/** The session's project / topic: click to move the session to another topic (once its turn is over). */
function MoveSessionPicker({ session, rootLabel, locked }: { session: Session; rootLabel: string; locked?: boolean }) {
  const t = useT()
  const { data: ws } = useWorkspace()
  const patch = usePatchSession()
  const mask = useMask()
  const setExpanded = useSessionsUI((s) => s.setExpanded)
  const projects = ws?.projects || []
  // projects/<p>[/topics/<t>[/agents/<a>]]
  const m = /^projects\/([^/]+)(?:\/topics\/([^/]+)(?:\/agents\/([^/]+))?)?$/.exec(session.path)
  const project = m ? projects.find((p) => p.name === m[1]) : undefined
  const topic = m?.[2] ? project?.topics.find((tp) => tp.name === m[2]) : undefined
  const agent = m?.[3] ? findAgent(ws, session.path) : undefined
  // Topics only: an agent's folder is the agent's (its runs live on the Agents page).
  const options = placeOptions(ws, false, (l) => mask(l, 10))
  const busy = !!locked || session.state === 'running' || session.queue > 0
  const hint = t(locked ? 'sessions.move.agentRun' : busy ? 'sessions.move.busy' : 'where.move')
  const label = m ? (
    <>
      <WhereBadge kind="project" name={m[1]} description={project?.description} dir={absTopicDir(ws, `projects/${m[1]}`)} hint={hint}>
        {project?.emoji ? <span className="shrink-0 leading-none">{project.emoji}</span> : <FolderOpen className="size-3 shrink-0 opacity-70" />}
      </WhereBadge>
      {m[2] && (
        <WhereBadge kind="topic" name={m[2]} description={topic?.description} dir={absTopicDir(ws, topicPathOf(session.path))} hint={hint}>
          <Hash className="size-3 shrink-0 opacity-70" />
        </WhereBadge>
      )}
      {m[3] && (
        <WhereBadge kind="agent" name={agent?.display_name || m[3]} description={agent?.description} dir={absTopicDir(ws, session.path)} hint={hint}>
          <AgentAvatarIcon avatar={agent?.avatar} size={16} />
        </WhereBadge>
      )}
      {!busy && <ChevronDown className="size-3 shrink-0 opacity-60" />}
    </>
  ) : (
    <>
      <FolderOpen className="size-3 shrink-0" />
      <span className="truncate">
        <Sensitive length={10}>{topicLabel(session.path, rootLabel)}</Sensitive>
      </span>
      {!busy && <ChevronDown className="size-3 shrink-0 opacity-60" />}
    </>
  )
  // The row stays 20 px on phones (the header must stay short): an invisible 40 px tap area instead of a taller row.
  const cls = "relative inline-flex min-w-0 items-center gap-1 rounded hover:text-foreground pointer-coarse:before:absolute pointer-coarse:before:inset-x-0 pointer-coarse:before:-top-1.5 pointer-coarse:before:-bottom-3.5 pointer-coarse:before:content-[''] focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
  if (busy)
    return (
      <span className={cn(cls, !locked && 'cursor-not-allowed')} data-testid="session-path">
        {label}
      </span>
    )
  return (
    <Combobox
      value={session.path}
      options={options}
      searchPlaceholder={t('sessions.move.search')}
      aria-label={t('sessions.move.label')}
      onChange={(path) => {
        if (path === session.path) return
        patch.mutate(
          { id: session.id, path },
          {
            onSuccess: () => {
              // Show it where it now lives in the sessions list.
              const project = path.split('/')[1]
              const tp = topicPathOf(path)
              setExpanded({ [`p:${project}`]: true, [`t:${tp}`]: true, ...(tp !== path && { [`g:${path}`]: true }) })
              toast.success(t('sessions.move.done', { where: topicLabel(path, rootLabel) }))
            },
          },
        )
      }}
      trigger={
        <button type="button" className={cls} data-testid="session-path" aria-label={t('sessions.move.label')}>
          {label}
        </button>
      }
    />
  )
}

/** One part of the session's place (project or topic) as a badge; hovering it explains what it is. */
export function WhereBadge({ kind, name, description, dir, hint, generic, children }: { kind: 'project' | 'topic' | 'agent'; name: string; description?: string; dir?: string | null; hint: string; /** The word itself (page subtitle): no name, no folder in the card. */ generic?: boolean; children?: React.ReactNode }) {
  const t = useT()
  return (
    <TooltipRoot delayDuration={350}>
      <TooltipTrigger asChild>
        <span className="inline-flex h-[18px] min-w-0 items-center gap-1 rounded-md border bg-muted/50 px-1.5 text-[11px] font-medium text-foreground/80 max-md:h-5 max-md:text-xs" data-testid={generic ? `where-word-${kind}` : `where-${kind}`} tabIndex={generic ? 0 : undefined}>
          {children}
          <span className="truncate">{generic ? name : <Sensitive length={8}>{name}</Sensitive>}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent side="bottom" align="start" className="block w-72 rounded-lg border bg-popover p-3 text-popover-foreground font-normal">
        <span className="flex items-center gap-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          {kind === 'project' ? <FolderOpen className="size-3" /> : kind === 'agent' ? <Bot className="size-3" /> : <Hash className="size-3" />}
          {t(kind === 'project' ? 'where.project' : kind === 'agent' ? 'where.agent' : 'where.topic')}
        </span>
        {!generic && (
          <span className="mt-1 block text-sm font-semibold">
            <Sensitive length={8}>{name}</Sensitive>
          </span>
        )}
        {description && <span className="mt-0.5 block text-xs text-muted-foreground"><Sensitive length={20}>{description.replace(/[*`_]+/g, '')}</Sensitive></span>}
        <span className="mt-2 block text-xs leading-relaxed">{t(kind === 'project' ? 'where.projectHelp' : kind === 'agent' ? 'where.agentHelp' : generic ? 'where.topicHelpAny' : 'where.topicHelp')}</span>
        {dir && <span className="mt-2 block truncate font-mono text-[11px] text-muted-foreground"><Sensitive length={16}>{dir}</Sensitive></span>}
        <span className="mt-2 block border-t pt-2 text-[11px] text-muted-foreground">{hint}</span>
      </TooltipContent>
    </TooltipRoot>
  )
}

export function NewSessionColumn({ col, variant, index, count, place }: { col: Extract<Col, { kind: 'new' }>; variant: ColumnVariant; index: number; count: number; place?: Place }) {
  const t = useT()
  const { data: ws } = useWorkspace()
  const { data: claude } = useClaudeStatus()
  const close = useSessionsUI((s) => s.close)
  const becomeSession = useSessionsUI((s) => s.becomeSession)
  const setNewPath = useSessionsUI((s) => s.setNewPath)
  const create = useCreateSession()
  const send = useSendMessage()
  const [title, setTitle] = React.useState('')
  const [model, setModel] = React.useState('')
  const [planMode, setPlanMode] = React.useState(false)
  const composer = React.useRef<ComposerHandle>(null)
  const [dragFiles, setDragFiles] = React.useState(false)
  const mask = useMask()
  const options = placeOptions(ws, false, (l) => mask(l, 10))
  const valid = options.some((o) => o.value === col.path)

  // The session made by the first message: the messages sent while it was being created go to it (sends are
  // chained, so they run once it is known), never into a second session.
  const made = React.useRef<string | null>(null)
  const toMade = async (sid: string, text: string, attachments: string[], extra: { client_id?: string; voice?: string }) => {
    const { add, remove } = usePending.getState()
    const voice = extra.voice ? { voice: true } : {}
    const lid = add(sid, { text, attachments, queued: true, ...voice })
    try {
      const r = await send.mutateAsync({ id: sid, text, attachments, ...extra })
      if (!r.queued) {
        remove(sid, lid)
        add(sid, { text, attachments, queued: false, ...voice })
      }
      return true
    } catch {
      remove(sid, lid)
      return false
    }
  }

  const onSend = async (text: string, attachments: string[], clientId?: string) => {
    if (made.current) return toMade(made.current, text, attachments, { client_id: clientId })
    try {
      const s = await create.mutateAsync({ path: col.path, message: text, client_id: clientId, title: title.trim() || undefined, model: model || undefined, attachments, plan_mode: planMode || undefined })
      made.current = s.id
      seedEmptyLog(s.id)
      usePending.getState().add(s.id, { text, attachments, queued: false })
      saveDraft(`new:${col.path}`, '')
      becomeSession(col.key, s.id)
      requestAnimationFrame(() => focusComposer(col.key))
      return true
    } catch (e) {
      toast.error(errorMessage(e))
      return false
    }
  }

  const onSendVoice = async (file: File) => {
    try {
      const up = await uploadAttachment(col.path, file)
      if (made.current) return toMade(made.current, '', [], { voice: up.path })
      const s = await create.mutateAsync({ path: col.path, title: title.trim() || undefined, model: model || undefined, plan_mode: planMode || undefined, voice: up.path })
      made.current = s.id
      seedEmptyLog(s.id)
      usePending.getState().add(s.id, { text: '', attachments: [], queued: false, voice: true })
      becomeSession(col.key, s.id)
      requestAnimationFrame(() => focusComposer(col.key))
      return true
    } catch (e) {
      toast.error(errorMessage(e))
      return false
    }
  }

  // The first message was being sent when the page went away: if the server made the session (its first message,
  // or one queued in it, carries the outbox id), that session takes the column and its own composer checks the
  // other entries. null = could not tell (kept for the next load).
  const qc = useQueryClient()
  const checkSent = React.useCallback(
    async (left: OutboxEntry[]) => {
      let list: Session[]
      try {
        list = await qc.fetchQuery({ ...sessionsQuery(col.path, false), staleTime: 0 })
      } catch {
        return null
      }
      const since = Math.min(...left.map((e) => e.at)) / 1000 - 600 // the browser clock may be off
      const recent = list.filter((x) => x.path === col.path && x.created >= since).sort((a, b) => b.created - a.created).slice(0, 5)
      for (const x of recent) {
        await loadLog(x.id)
        const st = getLog(x.id)
        if (st.status !== 'ready') return null
        const got = (e: OutboxEntry) =>
          e.tagged
            ? st.items.some((it) => it.kind === 'user' && it.ev.client_ids?.includes(e.id)) || !!x.queue_items?.some((q) => q.client_ids?.includes(e.id)) || !!x.sent_items?.some((q) => q.client_ids?.includes(e.id))
            : st.items.some((it) => it.kind === 'user' && it.ev.text.trim() === e.text.trim())
        if (!left.some(got)) continue
        made.current = x.id
        outboxMove(`new:${col.path}`, x.id)
        becomeSession(col.key, x.id)
        return []
      }
      return left
    },
    [qc, col.path, col.key, becomeSession],
  )

  // (a picture dragged from a thread carries a file too: that is a content drag)
  const isFileDrag = (e: React.DragEvent) => e.dataTransfer.types.includes('Files') && !e.dataTransfer.types.includes(CONTENT_MIME)
  return (
    <ColumnShell col={col} index={index} count={count} variant={variant} place={place}>
      <div
        className="relative flex min-h-0 flex-1 flex-col"
        onDragEnter={(e) => isFileDrag(e) && setDragFiles(true)}
        onDragOver={(e) => !contentDragOver(e, col.key, null) && isFileDrag(e) && e.preventDefault()}
        onDragLeave={(e) => {
          contentDragLeave(e, col.key)
          if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragFiles(false)
        }}
        onDrop={(e) => {
          const d = contentDrop(e, null)
          if (d !== undefined) return d && quoteDropped(col.key, composer.current, d)
          if (!isFileDrag(e)) return
          e.preventDefault()
          setDragFiles(false)
          composer.current?.addFiles(Array.from(e.dataTransfer.files))
        }}
      >
        <header data-col-head className={cn('shrink-0 border-b px-3 py-1.5', variant !== 'column' && 'pt-[calc(0.375rem+var(--safe-top))]')}>
          <div className="flex h-9 items-center gap-1">
            {variant === 'mobile' && <TouchSessionsButton className="-ml-2" />}
            {variant === 'column' && <DragGrip colKey={col.key} />}
            <span className="truncate px-1 text-sm font-semibold max-md:flex-1 max-md:text-[15px]">{t('sessions.new.title')}</span>
            {variant === 'mobile' && <TouchAppButton className="-mr-2" />}
            {variant === 'column' && (
              <Tooltip content={t('sessions.closeColumn')}>
                <Button variant="ghost" size="icon-sm" className="ml-auto" aria-label={t('sessions.closeColumn')} onClick={() => close(col.key)}>
                  <X />
                </Button>
              </Tooltip>
            )}
          </div>
          {variant === 'mobile' && <MobileTabs />}
          <div className="flex h-5 items-center text-[11px] text-muted-foreground">{t('sessions.new.subtitle')}</div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto grid w-full max-w-[560px] gap-4 px-4 py-6">
            <div className="grid gap-1.5">
              <Label htmlFor={`topic-${col.key}`}>{t('sessions.new.topic')}</Label>
              <Combobox id={`topic-${col.key}`} value={col.path} onChange={(v) => setNewPath(col.key, v)} options={options} placeholder={t('sessions.new.pickTopic')} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`title-${col.key}`}>
                {t('sessions.new.titleLabel')} <span className="font-normal text-muted-foreground">{t('sessions.new.optional')}</span>
              </Label>
              <Input id={`title-${col.key}`} value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t('sessions.new.titlePlaceholder')} maxLength={120} autoComplete="off" />
            </div>
            <div className="grid gap-1.5">
              <span className="text-sm font-medium">{t('sessions.model.label')}</span>
              <div>
                <ModelPicker chosen={model} onChange={setModel} />
              </div>
            </div>
            <label htmlFor={`plan-${col.key}`} className="flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2.5 has-[:checked]:border-primary/50 has-[:checked]:bg-primary/[0.06]">
              <Checkbox id={`plan-${col.key}`} checked={planMode} onCheckedChange={(v) => setPlanMode(v === true)} className="mt-0.5" />
              <span className="grid gap-0.5 leading-tight">
                <span className="flex items-center gap-1.5 text-sm font-medium">
                  <ListChecks className="size-3.5 text-primary" /> {t('plan.newLabel')}
                </span>
                <span className="text-xs text-muted-foreground">{t('plan.newHint')}</span>
              </span>
            </label>
            <p className="text-[13px] text-muted-foreground">{t('sessions.new.hint')}</p>
          </div>
        </div>
        <Composer
          ref={composer}
          colKey={col.key}
          draftKey={`new:${col.path}`}
          topicPath={col.path}
          disabledReason={!valid ? t('sessions.new.pickTopic') : claude && !claude.auth.ok ? t(claude.auth.method ? 'sessions.composer.authExpired' : 'sessions.composer.noAuth') : null}
          onSend={onSend}
          checkSent={checkSent}
          onSendVoice={onSendVoice}
          autoFocus={variant !== 'mobile'}
          placeholder={planMode ? t('plan.placeholder') : t('sessions.new.placeholder')}
        />
        {dragFiles && (
          <div className="pointer-events-none absolute inset-2 z-30 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-primary bg-background/95 text-sm font-medium">
            <Upload className="size-6 text-primary" />
            {t('sessions.dropToAttach')}
          </div>
        )}
        <ContentDropOverlay colKey={col.key} sid={null} />
      </div>
    </ColumnShell>
  )
}
