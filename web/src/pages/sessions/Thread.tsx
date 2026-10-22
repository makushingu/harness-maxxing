// The conversation scroller.
// - renders a window of the last N items; older ones are revealed (sentinel / button) with the
//   scroll position kept exactly (manual anchoring, `overflow-anchor: none`); once every loaded item
//   is shown, the same sentinel/button fetches the previous page from the server (`onLoadEarlier`);
// - sticks to the bottom only while the user is at the bottom (ResizeObserver keeps it pinned
//   while markdown/images settle); otherwise a "jump to latest" pill appears.
import * as React from 'react'
import { ArrowDown, MessageSquareDashed, RotateCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Button, EmptyState, Skeleton, Spinner, toast } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { hideMessage } from '@/lib/queries'
import { reducedMotion } from '@/lib/presence'
import type { Session } from '@/lib/types'
import { ItemRow, UserMessage } from './Items'
import { ErrorBoundary } from '@/components/ui/error-boundary'
import { isShownTask, setHiddenLocal, taskStatus, turnKeys, unanswered, withoutHidden, type Item, type LogState } from './log'
import type { Pending, Seed } from './store'
import { fmtElapsed } from './util'

const PAGE = 120
/** A freshly opened thread first renders only its last rows (they fill the screen), then grows to PAGE rows by
 *  STEP-row slices above them, out of sight (same anchoring as "show earlier"): the thread shows up sooner and the
 *  final page is the same. */
const FIRST = 30
const STEP = 30
const PIN_PX = 48
/** Rows at the bottom of a freshly opened thread that cascade in (the rest is off-screen anyway). */
const INTRO_ROWS = 8

export type ThreadHandle = { scrollToBottom: (smooth?: boolean) => void }

export const Thread = React.forwardRef<ThreadHandle, {
  log: LogState
  session: Session | undefined
  pending: Pending[]
  onRetry: () => void
  /** Fetch older events from the server (prepended to `log.items`). */
  onLoadEarlier?: () => void
  empty?: React.ReactNode
  /** Edit on a message that got no answer: it goes back into the composer (and leaves the thread). */
  onEdit?: (seed: Seed) => void
  /** Right click → "New session from this message". */
  onFork?: (seed: Seed) => void
}>(function Thread({ log, session, pending, onRetry, onLoadEarlier, empty, onEdit, onFork }, ref) {
  const t = useT()
  const scroller = React.useRef<HTMLDivElement>(null)
  const content = React.useRef<HTMLDivElement>(null)
  const pinned = React.useRef(true)
  const [showPill, setShowPill] = React.useState(false)
  const [unseen, setUnseen] = React.useState(false)
  // Hidden messages (deleted unanswered ones) take their turn's rows with them.
  const items = React.useMemo(() => withoutHidden(log.items, log.hidden), [log.items, log.hidden])
  const ready = log.status === 'ready'

  // Window start: fixed once ready (appends never move it), decreases when loading earlier.
  const [start, setStart] = React.useState<number | null>(null)
  // Where the first page ends up (the progressive first render grows `start` down to it), null once reached.
  const growTo = React.useRef<number | null>(null)
  // A layout effect: the first ready render (FIRST rows) is measured before the browser paints it.
  React.useLayoutEffect(() => {
    if (!ready && start !== null) {
      setStart(null) // reloaded (retry / log reset)
      growTo.current = null
    } else if (ready && start === null) {
      const target = Math.max(0, items.length - PAGE)
      const first = Math.max(target, items.length - FIRST)
      const el = scroller.current
      // The first rows do not overflow the view much (its top is visible): the whole page now, before the paint,
      // so that nothing ever appears in view.
      if (first > target && el && el.scrollHeight - el.clientHeight >= 600) {
        growTo.current = target
        setStart(first)
      } else {
        growTo.current = null
        if (el && first > target) prevHeight.current = el.scrollHeight
        setStart(target)
      }
    }
  }, [ready, items.length, start])
  const from = start ?? Math.max(0, items.length - (ready ? FIRST : PAGE))
  const visible = from > 0 ? items.slice(from) : items
  const moreOnServer = ready && log.moreBefore && !!onLoadEarlier

  const prevHeight = React.useRef<number | null>(null)
  // Older items prepended from the server: remember the height of the DOM *before* it is updated
  // (read during render, the commit has not happened yet) so the layout effect below keeps the
  // reading position exactly.
  const headKey = items[0]?.key
  const lastHead = React.useRef(headKey)
  if (headKey !== lastHead.current) {
    if (lastHead.current !== undefined && headKey !== undefined && ready && prevHeight.current == null && scroller.current)
      prevHeight.current = scroller.current.scrollHeight
    lastHead.current = headKey
  }
  const loadEarlier = React.useCallback(() => {
    const el = scroller.current
    if (!el) return
    if (from > 0) {
      prevHeight.current = el.scrollHeight
      setStart(Math.max(0, from - PAGE))
    } else if (moreOnServer && !log.loadingEarlier) onLoadEarlier!()
  }, [from, moreOnServer, log.loadingEarlier, onLoadEarlier])
  React.useLayoutEffect(() => {
    const el = scroller.current
    if (el && prevHeight.current != null) {
      el.scrollTop += el.scrollHeight - prevHeight.current
      prevHeight.current = null
    }
  }, [from, headKey])

  // Progressive first render: the rest of the first page, a slice per idle moment, prepended out of sight.
  React.useEffect(() => {
    const target = growTo.current
    if (target === null || start === null) return
    if (start <= target) {
      growTo.current = null
      return
    }
    const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (h: number) => void }
    const grow = () => {
      const s = scroller.current
      if (!s || growTo.current === null) return
      prevHeight.current = s.scrollHeight
      setStart((cur) => (cur === null ? cur : Math.max(growTo.current ?? 0, cur - STEP)))
    }
    if (w.requestIdleCallback) {
      const h = w.requestIdleCallback(grow, { timeout: 250 })
      return () => w.cancelIdleCallback?.(h)
    }
    const h = setTimeout(grow, 16)
    return () => clearTimeout(h)
  }, [start])

  const toBottom = React.useCallback((smooth = false) => {
    const el = scroller.current
    if (!el) return
    pinned.current = true
    setShowPill(false)
    setUnseen(false)
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  }, [])
  React.useImperativeHandle(ref, () => ({ scrollToBottom: toBottom }), [toBottom])

  // First paint of a loaded thread: at the bottom, before the browser paints.
  const placed = React.useRef(false)
  React.useLayoutEffect(() => {
    if (ready && !placed.current && scroller.current) {
      placed.current = true
      scroller.current.scrollTop = scroller.current.scrollHeight
    }
  })

  // New rows: follow if pinned, else flag unseen content.
  // (Only the END of the list counts: older items prepended at the top are not "new".)
  const tailKey = `${items[items.length - 1]?.key ?? ''}|${pending.length}`
  const lastTail = React.useRef(tailKey)
  const lastCount = React.useRef(items.length + pending.length)
  React.useLayoutEffect(() => {
    const n = items.length + pending.length
    if (tailKey === lastTail.current) {
      lastCount.current = n
      return
    }
    const grew = n > lastCount.current
    lastTail.current = tailKey
    lastCount.current = n
    const el = scroller.current
    if (!el) return
    if (pinned.current) el.scrollTop = el.scrollHeight
    else if (grew) setUnseen(true)
  }, [tailKey, items.length, pending.length])

  // Size changes stay pinned: the content (markdown, images, expanding cards, text re-wrapped by a new width) and
  // the view itself (composer growing or unfolding, waiting-messages card, grid row split, window, phone keyboard).
  React.useEffect(() => {
    const el = scroller.current
    const inner = content.current
    if (!el || !inner) return
    const ro = new ResizeObserver(() => {
      if (pinned.current && prevHeight.current == null) el.scrollTop = el.scrollHeight
    })
    ro.observe(inner)
    ro.observe(el)
    return () => ro.disconnect()
  }, [ready])

  // Only the user lets go of the bottom: a scroll that moves UP away from it (wheel, drag, keys, scrollbar). Scrolls
  // that go down (smooth "jump to latest", pinning) or that the browser makes when the layout changes keep it.
  const lastTop = React.useRef(0)
  const onScroll = React.useCallback(() => {
    const el = scroller.current
    if (!el) return
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight
    const up = el.scrollTop < lastTop.current - 1
    lastTop.current = el.scrollTop
    if (dist < PIN_PX) pinned.current = true
    else if (up) pinned.current = false
    const atBottom = dist < PIN_PX
    setShowPill(!pinned.current && dist > 160)
    if (atBottom) setUnseen(false)
  }, [])

  // Auto-load earlier rows when the top sentinel shows up.
  const sentinel = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    const s = sentinel.current
    const el = scroller.current
    if (!s || !el || (from <= 0 && !moreOnServer) || log.loadingEarlier) return
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && loadEarlier(), { root: el, rootMargin: '300px 0px 0px 0px' })
    io.observe(s)
    return () => io.disconnect()
  }, [from, moreOnServer, log.loadingEarlier, loadEarlier, headKey])

  // Entrance: the last rows of a freshly opened thread rise one after the other (for ~0.8 s), and rows that
  // arrive live (keys e<N> with N past the count at open time) rise individually. Older rows never animate.
  const [intro, setIntro] = React.useState(true)
  React.useEffect(() => {
    if (!ready) return
    const id = setTimeout(() => setIntro(false), 800)
    return () => clearTimeout(id)
  }, [ready])
  const openedAt = React.useRef<number | null>(null)
  if (ready && openedAt.current === null) openedAt.current = log.count
  const rowAnim = (key: string, fromEnd: number): { className?: string; style?: React.CSSProperties } => {
    if (intro && fromEnd < INTRO_ROWS) return { className: 'mx-rise', style: { '--i': INTRO_ROWS - 1 - fromEnd } as React.CSSProperties }
    const m = /^e(\d+)$/.exec(key)
    return m && openedAt.current !== null && Number(m[1]) >= openedAt.current ? { className: 'mx-rise' } : {}
  }

  const running = session?.state === 'running'
  const optimistic = pending.filter((p) => !p.queued)

  // Deleting an unanswered message: its rows slide out, then the thread drops them; "Undo" in the toast.
  const sid = session?.id
  const hideable = React.useMemo(() => unanswered(items, running), [items, running])
  const [leaving, setLeaving] = React.useState<ReadonlySet<string>>(new Set())
  const itemsRef = React.useRef(items)
  itemsRef.current = items
  // `undo`: the "Deleted" toast with Undo (Edit hides quietly: the text is in the composer).
  const hide = React.useCallback(
    (key: string, at: number, undo: boolean) => {
      if (!sid) return
      const keys = turnKeys(itemsRef.current, key)
      let failed = false
      const fail = (hidden: boolean) => (e: unknown) => {
        setHiddenLocal(sid, at, hidden)
        toast.error(errorMessage(e))
      }
      const show = () => {
        setHiddenLocal(sid, at, false)
        hideMessage(sid, at, false).catch(fail(true))
      }
      setLeaving((cur) => new Set([...cur, ...keys]))
      setTimeout(
        () => {
          if (!failed) setHiddenLocal(sid, at, true)
          setLeaving((cur) => new Set([...cur].filter((k) => !keys.includes(k))))
        },
        reducedMotion() ? 0 : 150,
      )
      hideMessage(sid, at, true).then(
        () => undo && toast.action(t('sessions.msg.deleted'), undefined, { label: t('common.undo'), onClick: show }),
        (e) => {
          failed = true
          fail(false)(e)
        },
      )
    },
    [sid, t],
  )
  const onHide = React.useCallback((key: string, at: number) => hide(key, at, true), [hide])
  const editRef = React.useRef(onEdit)
  editRef.current = onEdit
  const onEditItem = React.useCallback(
    (key: string, at: number, seed: Seed) => {
      editRef.current?.(seed)
      hide(key, at, false)
    },
    [hide],
  )
  const forkRef = React.useRef(onFork)
  forkRef.current = onFork
  const onForkItem = React.useCallback((seed: Seed) => forkRef.current?.(seed), [])
  const turnStart = React.useMemo(() => lastTurnStart(items), [items])

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={scroller} onScroll={onScroll} className="absolute inset-0 overflow-x-hidden overflow-y-auto overscroll-contain [contain:layout_paint] [overflow-anchor:none]" data-thread>
        <div ref={content} className="mx-auto flex min-h-full w-full max-w-[860px] flex-col gap-3 px-4 pt-4 pb-6 max-md:px-3">
          {log.status === 'loading' && <ThreadSkeleton />}
          {log.status === 'error' && (
            <EmptyState
              compact
              tone="error"
              icon={MessageSquareDashed}
              title={log.deleted ? t('sessions.deleted') : t('sessions.loadError')}
              description={log.deleted ? undefined : log.error}
              action={
                !log.deleted && (
                  <Button size="sm" variant="outline" onClick={onRetry}>
                    <RotateCw /> {t('common.retry')}
                  </Button>
                )
              }
            />
          )}
          {ready && (
            <>
              {(from > 0 || moreOnServer) && (
                <div ref={sentinel} className="flex justify-center">
                  <Button size="sm" variant="ghost" onClick={loadEarlier} loading={from <= 0 && log.loadingEarlier} className="text-muted-foreground">
                    {from > 0 ? t('sessions.showEarlier', { count: from }) : t('sessions.showEarlierMessages')}
                  </Button>
                </div>
              )}
              {items.length === 0 && optimistic.length === 0 && !running && (empty ?? <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">{t('sessions.emptyThread')}</div>)}
              {visible.map((it, i) => {
                const anim = rowAnim(it.key, visible.length - 1 - i)
                return (
                  <div
                    key={it.key}
                    style={anim.style}
                    className={cn(anim.className, leaving.has(it.key) && 'pointer-events-none translate-x-4 opacity-0 transition-[opacity,transform] duration-150 ease-in')}
                  >
                    <ErrorBoundary>
                      <ItemRow item={it} live={running && it.kind === 'tool' && !it.result && from + i > turnStart} onHide={hideable.has(it.key) ? onHide : undefined} onEdit={onEdit && onEditItem} onFork={onFork && onForkItem} />
                    </ErrorBoundary>
                  </div>
                )
              })}
              {optimistic.map((p) => (
                <UserMessage key={p.lid} text={p.text} attachments={p.attachments} voice={p.voice || undefined} pending />
              ))}
              {running && <RunningRow session={session!} log={log} />}
              {log.deleted && <p className="text-center text-xs text-muted-foreground">{t('sessions.deleted')}</p>}
            </>
          )}
        </div>
      </div>
      <button
        type="button"
        onClick={() => toBottom(true)}
        tabIndex={showPill ? 0 : -1}
        aria-hidden={!showPill}
        className={cn(
          'absolute bottom-3 left-1/2 z-10 inline-flex h-8 max-md:h-10 pointer-coarse:h-10 -translate-x-1/2 items-center gap-1.5 rounded-full border bg-popover px-3 text-xs font-medium shadow-pop transition-[opacity,transform] duration-150',
          showPill ? 'translate-y-0 opacity-100' : 'pointer-events-none translate-y-2 opacity-0',
        )}
      >
        <ArrowDown className="size-3.5" />
        {unseen ? t('sessions.newMessages') : t('sessions.jumpLatest')}
      </button>
    </div>
  )
})

/** Index of the last user/result row: only tool calls after it can still be running. */
function lastTurnStart(items: Item[]): number {
  for (let i = items.length - 1; i >= 0; i--) if (items[i].kind === 'result' || items[i].kind === 'user') return i
  return -1
}

/** The running time alone ticks every second (not the row, nor its scan of the log). */
function Elapsed({ since }: { since: number }) {
  const [now, setNow] = React.useState(() => Date.now() / 1000)
  React.useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(id)
  }, [])
  return <span className="ml-auto shrink-0 tabular-nums">{fmtElapsed(now - since)}</span>
}

function RunningRow({ session, log }: { session: Session; log: LogState }) {
  const t = useT()
  // Current activity: the last tool still waiting for its result, if any.
  let activity = t('sessions.working')
  for (let i = log.items.length - 1; i >= 0; i--) {
    const it = log.items[i]
    if (it.kind === 'user' || it.kind === 'result') break
    if (it.kind === 'tool') {
      if (!it.result) activity = it.use.summary
      break
    }
  }
  // Nothing pending in the thread but sub-agents / background commands still run: say so (the bar lists them).
  if (activity === t('sessions.working')) {
    const bg = Object.values(log.tasks).filter((tk) => isShownTask(tk) && taskStatus(tk, true) === 'running')
    if (bg.length) activity = t(bg.every((tk) => tk.kind === 'agent') ? 'tasks.bar' : 'tasks.barAny', { count: bg.length })
  }
  const since = log.lastUserAt || session.updated
  return (
    <div className="flex h-7 items-center gap-2 text-xs text-muted-foreground" aria-live="polite">
      <Spinner className="size-3.5 text-primary" />
      <span className="truncate">{activity}</span>
      <Elapsed since={since} />
    </div>
  )
}

function ThreadSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy>
      <Skeleton className="ml-auto h-9 w-2/3 rounded-2xl" />
      <div className="grid gap-2">
        <Skeleton className="h-3.5 w-11/12" />
        <Skeleton className="h-3.5 w-10/12" />
        <Skeleton className="h-3.5 w-7/12" />
      </div>
      <Skeleton className="h-8 w-full" />
      <Skeleton className="ml-auto h-9 w-1/2 rounded-2xl" />
      <div className="grid gap-2">
        <Skeleton className="h-3.5 w-10/12" />
        <Skeleton className="h-3.5 w-8/12" />
      </div>
    </div>
  )
}
