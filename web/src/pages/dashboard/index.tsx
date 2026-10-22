// Dashboard: widget cards from GET /api/dashboard rendered with native blocks.
// Edit mode: reorder (drag handle or arrow buttons), hide/show, PUT /api/dashboard/layout.
import * as React from 'react'
import { ArrowDown, ArrowUp, Bell, Check, ExternalLink, Eye, EyeOff, GripVertical, LayoutDashboard, Pencil, RefreshCw, TriangleAlert, X } from 'lucide-react'
import { useDashboard, useFeed, useFillPendingWidgets, useRefreshWidget, useSaveLayout } from '@/lib/queries'
import { useNavigate } from 'react-router'
import { useUI } from '@/stores/ui'
import { useMediaQuery } from '@/stores/media'
import { FeedPanel } from '@/features/feed/FeedItems'
import { fmtRelative } from '@/lib/format'
import type { Widget } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Button, Card, CountBadge, EmptyState, NamedIcon, Skeleton, SkeletonText, Spinner, StatusDot, Tooltip } from '@/components/ui'
import { Page } from '@/components/shell/Page'
import { useRegisterCommands } from '@/commands/registry'
import { BlockView, InView, SmartLink } from './blocks'
import { HtmlWidget } from './HtmlWidget'
import { ErrorBoundary } from '@/components/ui/error-boundary'
import { EASE_OUT, reducedMotion } from '@/lib/presence'

/** With the notifications panel open, the grid has 2 columns up to 2xl (3 above). */
const spanCls = (s: number, panel = false) =>
  s >= 3 ? (panel ? 'md:col-span-2 2xl:col-span-3' : 'md:col-span-2 xl:col-span-3') : s === 2 ? 'md:col-span-2' : ''

// Memoised: a feed or layout refetch only re-renders the cards whose data changed (patched widgets keep identity).
/** True until the element has been on screen once: a card below the fold keeps its entrance (and its charts',
 *  timeline's, numbers') for the moment it scrolls into view, instead of playing it unseen at load. */
function useWaitForView(ref: React.RefObject<HTMLElement | null>): boolean {
  const [wait, setWait] = React.useState(true)
  React.useLayoutEffect(() => {
    const el = ref.current
    if (!el || typeof IntersectionObserver === 'undefined' || reducedMotion()) return setWait(false)
    const r = el.getBoundingClientRect()
    if (r.top < window.innerHeight && r.bottom > 0) return setWait(false) // on screen at once: no pause at all
    const io = new IntersectionObserver((es) => es.some((e) => e.isIntersecting) && (setWait(false), io.disconnect()), { rootMargin: '0px 0px -8% 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [ref])
  return wait
}

const WidgetCard = React.memo(function WidgetCard({ w, index, panel }: { w: Widget; index: number; panel?: boolean }) {
  const t = useT()
  const lang = useLang()
  const refresh = useRefreshWidget()
  const card = w.card
  const cardRef = React.useRef<HTMLDivElement>(null)
  const wait = useWaitForView(cardRef)
  return (
    <InView.Provider value={!wait}>
    {/* Widgets arrive one after the other (32 ms apart, capped so a long dashboard is complete in ~0.5 s). */}
    <Card ref={cardRef} className={cn('mx-card-in min-w-0 gap-0 overflow-hidden', wait && 'mx-wait', spanCls(w.span, panel))} style={{ '--i': Math.min(index, 6) } as React.CSSProperties}>
      <div className="flex h-12 items-center gap-2.5 px-[var(--pad-card)] pt-1">
        <NamedIcon name={w.icon} className="size-4 text-muted-foreground" />
        <h2 className="min-w-0 flex-1 truncate text-sm font-medium">{card?.title || w.title}</h2>
        {card?.status && card.status !== 'ok' && <StatusDot tone={card.status} label={card.status} />}
        {card?.updated && (
          // keyed by the update: the time fades in again each time the card gets fresh data
          <span key={card.updated} className="mx-fade text-[11px] text-muted-foreground tabular-nums max-sm:hidden" title={new Date(card.updated * 1000).toLocaleString(lang)}>
            {fmtRelative(card.updated, lang)}
          </span>
        )}
        <Tooltip content={t('dash.refresh')}>
          <Button variant="ghost" size="icon-sm" className="-mr-2 size-7 text-muted-foreground" onClick={() => refresh.mutate(w.id)} disabled={refresh.isPending} aria-label={`${t('dash.refresh')} ${w.title}`}>
            {refresh.isPending ? <Spinner className="size-3.5" /> : <RefreshCw className="size-3.5" />}
          </Button>
        </Tooltip>
      </div>
      <div className={cn('flex-1 px-[var(--pad-card)] pt-2 pb-[var(--pad-card)] transition-opacity', refresh.isPending && 'opacity-60')}>
        {w.pending ? (
          <SkeletonText lines={3} className="py-1" />
        ) : w.error && !card ? (
          <div className="flex min-h-24 flex-col items-center justify-center gap-2 text-center">
            <TriangleAlert className="size-5 text-destructive" />
            <p className="text-[13px] text-muted-foreground">{w.error}</p>
            <Button variant="outline" size="sm" onClick={() => refresh.mutate(w.id)} loading={refresh.isPending}>
              {t('common.retry')}
            </Button>
          </div>
        ) : card?.html ? (
          <HtmlWidget key={card.updated} id={w.id} src={card.html} height={card.height || 260} title={w.title} />
        ) : card ? (
          <div className="mx-fade grid gap-5">
            {(Array.isArray(card.blocks) ? card.blocks : []).map((b, i) => (
              // a malformed block (an extension's card()) shows a line instead of breaking the dashboard
              <ErrorBoundary key={i} resetKey={card.updated}>
                <BlockView block={b} />
              </ErrorBoundary>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t('dash.noData')}</p>
        )}
      </div>
      {card?.link && (
        <SmartLink href={card.link} className="flex h-10 items-center gap-1.5 border-t px-[var(--pad-card)] text-[13px] font-medium text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground">
          {t('dash.open')} <ExternalLink className="size-3" />
        </SmartLink>
      )}
    </Card>
    </InView.Provider>
  )
})

function SkeletonGrid() {
  const spans = [2, 1, 1, 1, 1, 1]
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy>
      {spans.map((s, i) => (
        <Card key={i} className={cn('gap-4 p-[var(--pad-card)]', spanCls(s))}>
          <div className="flex items-center gap-2.5">
            <Skeleton className="size-4 rounded" />
            <Skeleton className="h-4 w-28" />
          </div>
          <Skeleton className="h-8 w-24" />
          <Skeleton className="h-[120px]" />
        </Card>
      ))}
    </div>
  )
}

type Layout = { order: string[]; hidden: Set<string> }

function EditList({ widgets, layout, setLayout }: { widgets: Widget[]; layout: Layout; setLayout: (l: Layout) => void }) {
  const t = useT()
  const byId = new Map(widgets.map((w) => [w.id, w]))
  const [dragging, setDragging] = React.useState<string | null>(null)
  const move = (from: number, to: number) => {
    if (to < 0 || to >= layout.order.length) return
    const o = [...layout.order]
    const [x] = o.splice(from, 1)
    o.splice(to, 0, x)
    setLayout({ ...layout, order: o })
  }
  return (
    <ul className="grid gap-2" aria-label={t('dash.layout')}>
      {layout.order.map((id, i) => {
        const w = byId.get(id)
        if (!w) return null
        const hidden = layout.hidden.has(id)
        return (
          <li
            key={id}
            draggable
            onDragStart={(e) => {
              setDragging(id)
              e.dataTransfer.effectAllowed = 'move'
            }}
            onDragEnd={() => setDragging(null)}
            onDragOver={(e) => {
              e.preventDefault()
              if (dragging && dragging !== id) move(layout.order.indexOf(dragging), i)
            }}
            className={cn('flex items-center gap-3 rounded-lg border bg-card px-3 py-2.5 transition-[opacity,box-shadow]', dragging === id && 'opacity-50 shadow-pop', hidden && 'bg-muted/30')}
          >
            <GripVertical className="size-4 shrink-0 cursor-grab text-muted-foreground active:cursor-grabbing max-md:hidden" aria-hidden />
            <NamedIcon name={w.icon} className={cn('size-4', hidden ? 'text-muted-foreground/50' : 'text-muted-foreground')} />
            <span className={cn('min-w-0 flex-1 truncate text-sm font-medium', hidden && 'text-muted-foreground line-through decoration-muted-foreground/40')}>{w.title}</span>
            <span className="text-xs text-muted-foreground max-sm:hidden">{w.source === 'extension' ? t('dash.extension') : t('dash.builtin')}</span>
            <div className="flex items-center">
              <Button variant="ghost" size="icon-sm" onClick={() => move(i, i - 1)} disabled={i === 0} aria-label={t('dash.moveUp')}>
                <ArrowUp />
              </Button>
              <Button variant="ghost" size="icon-sm" onClick={() => move(i, i + 1)} disabled={i === layout.order.length - 1} aria-label={t('dash.moveDown')}>
                <ArrowDown />
              </Button>
              <Tooltip content={hidden ? t('dash.show') : t('dash.hide')}>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-pressed={!hidden}
                  aria-label={hidden ? t('dash.show') : t('dash.hide')}
                  onClick={() => {
                    const h = new Set(layout.hidden)
                    if (hidden) h.delete(id)
                    else h.add(id)
                    setLayout({ ...layout, hidden: h })
                  }}
                >
                  {hidden ? <EyeOff /> : <Eye />}
                </Button>
              </Tooltip>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

/** The cards slide to their new place (2-D FLIP, transform only) when the grid changes under them: notifications
 *  panel opened / closed (2 <-> 3 columns), a widget shown, hidden or moved. Children of `grid` = cards, in `ids` order. */
function useGridFlip(grid: React.RefObject<HTMLDivElement | null>, ids: string[], sig: string) {
  type Box = { left: number; top: number; width: number }
  const last = React.useRef(new Map<string, Box>())
  const idsRef = React.useRef(ids)
  idsRef.current = ids
  // Layout offsets inside the grid, not getBoundingClientRect: a scrolled page or a running slide (transform) would
  // otherwise shift every "before" position.
  const measure = React.useCallback((el: HTMLElement) => {
    const m = new Map<string, Box>()
    const own = (c: HTMLElement) => c.offsetParent === el
    Array.from(el.children).forEach((c, i) => {
      const h = c as HTMLElement
      const id = idsRef.current[i]
      if (id) m.set(id, { left: h.offsetLeft - (own(h) ? 0 : el.offsetLeft), top: h.offsetTop - (own(h) ? 0 : el.offsetTop), width: h.offsetWidth })
    })
    return m
  }, [])
  React.useLayoutEffect(() => {
    const el = grid.current
    if (!el) {
      last.current = new Map()          // edit mode: the grid comes back with its own entrance, no slide
      return
    }
    const now = measure(el)
    if (!reducedMotion())
      Array.from(el.children).forEach((c, i) => {
        const before = last.current.get(ids[i])
        const after = now.get(ids[i])
        if (!before || !after) return
        const dx = before.left - after.left
        const dy = before.top - after.top
        const sx = after.width ? before.width / after.width : 1
        if (Math.abs(dx) < 1 && Math.abs(dy) < 1 && Math.abs(sx - 1) < 0.01) return
        ;(c as HTMLElement).animate(
          [{ transformOrigin: 'top left', transform: `translate(${dx}px, ${dy}px) scaleX(${sx})` }, { transformOrigin: 'top left', transform: 'none' }],
          { duration: 340, easing: EASE_OUT },
        )
      })
    last.current = now
    // between two changes, a card that grows with its data or a resized window moves the others: keep "before" true
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => {
      if (grid.current === el) last.current = measure(el)
    })
    ro.observe(el)
    Array.from(el.children).forEach((c) => ro.observe(c))
    return () => ro.disconnect()
  }, [sig]) // eslint-disable-line react-hooks/exhaustive-deps
}

export default function DashboardPage() {
  const t = useT()
  const { data, isLoading, isError, refetch, isFetching } = useDashboard()
  const save = useSaveLayout()
  const [edit, setEdit] = React.useState<Layout | null>(null)
  const widgets = React.useMemo(() => data?.widgets || [], [data])
  useFillPendingWidgets(data?.widgets)
  const visible = widgets.filter((w) => !w.hidden)
  const gridRef = React.useRef<HTMLDivElement>(null)

  const navigate = useNavigate()
  const feedPanel = useUI((s) => s.feedPanel)
  const setFeedPanel = useUI((s) => s.setFeedPanel)
  const wideScreen = useMediaQuery('(min-width: 1280px)')
  const feed = useFeed(null, false, 30)
  const unread = feed.data?.unread ?? 0
  const panel = feedPanel && wideScreen
  const ids = visible.map((w) => w.id)
  useGridFlip(gridRef, ids, `${ids.join(',')}|${panel}|${!!edit}`)
  const startEdit = () => setEdit({ order: widgets.map((w) => w.id), hidden: new Set(widgets.filter((w) => w.hidden).map((w) => w.id)) })
  useRegisterCommands('dashboard', [{ id: 'dash:edit', title: t('dash.edit'), group: t('nav.dashboard'), icon: Pencil, perform: startEdit }], [t, widgets])

  const actions = edit ? (
    <>
      <Button variant="ghost" size="sm" onClick={() => setEdit(null)}>
        <X /> <span className="max-sm:hidden">{t('common.cancel')}</span>
      </Button>
      <Button size="sm" loading={save.isPending} onClick={() => save.mutate({ order: edit.order, hidden: [...edit.hidden] }, { onSuccess: () => setEdit(null) })}>
        <Check /> {t('common.save')}
      </Button>
    </>
  ) : (
    <>
      <Tooltip content={wideScreen ? (feedPanel ? t('feed.hidePanel') : t('feed.showPanel')) : t('feed.title')}>
        <Button
          variant={panel ? 'secondary' : 'ghost'}
          size="sm"
          className="relative gap-1.5"
          onClick={() => (wideScreen ? setFeedPanel(!feedPanel) : navigate('/feed'))}
          aria-label={t('feed.title')}
          data-testid="feed-bell"
        >
          <Bell />
          <CountBadge count={unread} title={t('feed.unreadCount', { count: unread })} />
        </Button>
      </Tooltip>
      <Tooltip content={t('dash.refreshAll')}>
        <Button variant="ghost" size="icon-sm" onClick={() => refetch()} aria-label={t('dash.refreshAll')} disabled={isFetching}>
          {isFetching && !isLoading ? <Spinner /> : <RefreshCw />}
        </Button>
      </Tooltip>
      <Button variant="outline" size="sm" onClick={startEdit} disabled={!widgets.length}>
        <Pencil /> <span className="max-sm:hidden">{t('dash.edit')}</span>
      </Button>
    </>
  )

  return (
    <Page title={t('nav.dashboard')} actions={actions} width="wide">
      <div className="flex items-start gap-4">
      <div className="min-w-0 flex-1">
      {isLoading ? (
        <SkeletonGrid />
      ) : isError ? (
        <EmptyState icon={TriangleAlert} tone="error" title={t('dash.error')} action={<Button onClick={() => refetch()}>{t('common.retry')}</Button>} />
      ) : edit ? (
        <div className="mx-auto grid max-w-2xl gap-4">
          <p className="text-sm text-muted-foreground">{t('dash.editHint')}</p>
          <EditList widgets={widgets} layout={edit} setLayout={setEdit} />
        </div>
      ) : !visible.length ? (
        <EmptyState icon={LayoutDashboard} title={t('dash.empty')} description={t('dash.emptyDesc')} action={widgets.length ? <Button onClick={startEdit}>{t('dash.edit')}</Button> : undefined} />
      ) : (
        <div ref={gridRef} className={cn('grid grid-flow-row-dense gap-4 md:grid-cols-2', panel ? '2xl:grid-cols-3' : 'xl:grid-cols-3')}>
          {visible.map((w, i) => (
            <ErrorBoundary key={w.id} variant="card" resetKey={w.card?.updated} className={cn('rounded-xl border bg-card', spanCls(w.span, panel))}>
              <WidgetCard w={w} index={i} panel={panel} />
            </ErrorBoundary>
          ))}
        </div>
      )}
      </div>
      {panel && !edit && <FeedPanel className="sticky top-4 h-[calc(100dvh-7.5rem)] w-80 shrink-0" />}
      </div>
    </Page>
  )
}
