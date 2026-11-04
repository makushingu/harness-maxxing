// One event of the notifications feed + the dashboard panel. Clicking an event marks it read and opens
// its link (inside the app, or a new tab for an outside one). An alert (an agent's request, a server problem) carries
// its buttons (Allow / Deny, Seen...), then says how it ended.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { ArrowUpRight, Bell, Check, CheckCheck, CheckCircle2, CircleAlert, Eye, Info, MoreHorizontal, Settings2, Trash2, TriangleAlert, X } from 'lucide-react'
import { useDeleteFeedEvent, useFeed, useFeedAct, useMarkFeedRead } from '@/lib/queries'
import type { FeedAction, FeedEvent, FeedLevel } from '@/lib/types'
import { fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import {
  Button,
  CountBadge,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  EmptyState,
  Sensitive,
  Skeleton,
  Tooltip,
} from '@/components/ui'

const LEVEL: Record<FeedLevel, { icon: React.ComponentType<{ className?: string }>; cls: string }> = {
  info: { icon: Info, cls: 'text-muted-foreground' },
  success: { icon: CheckCircle2, cls: 'text-success' },
  warning: { icon: TriangleAlert, cls: 'text-warning' },
  error: { icon: CircleAlert, cls: 'text-destructive' },
}

/** The buttons of an alert. `open` follows the event's link; the others go to the server in one click, like the
 *  request card of a run. A resolved alert shows how it ended instead. */
function FeedActions({ ev, onOpen }: { ev: FeedEvent; onOpen: () => void }) {
  const t = useT()
  const act = useFeedAct()
  const [busy, setBusy] = React.useState<string | null>(null)
  if (ev.resolved) {
    return ev.resolution ? (
      <span className="flex items-center gap-1 text-[11px] text-muted-foreground" data-testid="feed-resolution">
        <Check className="size-3" /> {ev.resolution}
      </span>
    ) : null
  }
  // Seen is done once the event is read; the rest stays (Open, an undecided request)
  const actions = (ev.actions ?? []).filter((a) => !(a.id === 'seen' && ev.read))
  if (!actions.length) return null
  const label = (a: FeedAction) =>
    a.id === 'allow' ? t('approval.allow') : a.id === 'deny' ? t('approval.deny') : a.id === 'seen' ? t('feed.action.seen') : a.id === 'open' ? t('feed.action.open') : a.label
  const icon = (a: FeedAction) =>
    a.id === 'allow' ? <Check className="size-3.5" /> : a.id === 'deny' ? <X className="size-3.5" /> : a.id === 'seen' ? <Eye className="size-3.5" /> : a.id === 'open' ? <ArrowUpRight className="size-3.5" /> : null
  const run = (a: FeedAction) => {
    if (a.id === 'open') return onOpen()
    setBusy(a.id)
    act.mutate({ id: ev.id, action: a.id }, { onSettled: () => setBusy(null) })
  }
  // Deny before Allow, as on the request card (Approvals.tsx); links last
  const order = (a: FeedAction) => (a.style === 'link' ? 2 : a.style === 'primary' ? 1 : 0)
  return (
    <span className="flex flex-wrap items-center gap-1.5" data-testid="feed-actions">
      {[...actions].sort((a, b) => order(a) - order(b)).map((a) => (
        <Button
          key={a.id}
          size="sm"
          variant={a.style === 'primary' ? 'default' : 'outline'}
          className={cn('md:h-7 md:px-2.5 md:text-xs', a.style === 'danger' && 'hover:border-destructive/50 hover:text-destructive')}
          loading={busy === a.id}
          disabled={!!busy}
          onClick={() => run(a)}
          data-action={a.id}
        >
          {icon(a)} {label(a)}
        </Button>
      ))}
    </span>
  )
}

export function FeedItem({ ev, compact }: { ev: FeedEvent; compact?: boolean }) {
  const t = useT()
  const lang = useLang()
  const navigate = useNavigate()
  const read = useMarkFeedRead()
  const del = useDeleteFeedEvent()
  const L = LEVEL[ev.level] || LEVEL.info
  const open = () => {
    if (!ev.read) read.mutate({ ids: [ev.id] })
    if (!ev.url) return
    if (ev.url.startsWith('/')) navigate(ev.url)
    else window.open(ev.url, '_blank', 'noopener,noreferrer')
  }
  return (
    <div className={cn('group/ev relative flex gap-2.5 rounded-lg px-2.5 py-2 hover:bg-accent/50', !ev.read && 'bg-primary/[0.04]')} data-testid="feed-item" data-level={ev.level}>
      <L.icon className={cn('mt-0.5 size-4 shrink-0', L.cls)} />
      <div className="grid min-w-0 flex-1 gap-1.5">
        <button type="button" onClick={open} className="grid min-w-0 gap-0.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <span className={cn('flex min-w-0 items-center gap-1.5 text-[13px] leading-snug', !ev.read && 'font-medium')}>
            <span className={cn('[overflow-wrap:anywhere]', compact ? 'line-clamp-1' : 'line-clamp-2')}>
              <Sensitive length={12}>{ev.title}</Sensitive>
            </span>
            {ev.count > 1 && <span className="shrink-0 rounded bg-muted px-1 text-[10px] font-medium text-muted-foreground tabular-nums">×{ev.count}</span>}
          </span>
          {ev.body && (
            <span className={cn('text-xs [overflow-wrap:anywhere] whitespace-pre-line text-muted-foreground', compact ? 'line-clamp-2' : 'line-clamp-4')}>
              <Sensitive length={16}>{ev.body}</Sensitive>
            </span>
          )}
          <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <span className="truncate">{ev.source}</span>
            <span>·</span>
            <time className="shrink-0 tabular-nums" dateTime={new Date(ev.at * 1000).toISOString()}>
              {fmtRelative(ev.at, lang)}
            </time>
          </span>
        </button>
        <FeedActions ev={ev} onOpen={open} />
      </div>
      {!ev.read && <span aria-label={t('feed.unread')} className="absolute top-3 right-2 size-1.5 rounded-full bg-primary group-hover/ev:hidden" />}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={t('common.more')} className="size-7 shrink-0 opacity-0 group-hover/ev:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100 max-md:opacity-100 pointer-coarse:opacity-100">
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-44">
          {!ev.read && (
            <DropdownMenuItem onSelect={() => read.mutate({ ids: [ev.id] })}>
              <CheckCheck /> {t('feed.markRead')}
            </DropdownMenuItem>
          )}
          <DropdownMenuItem destructive onSelect={() => del.mutate(ev.id)}>
            <Trash2 /> {t('common.delete')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

export function FeedSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="grid gap-3 p-2.5" aria-busy>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex gap-2.5">
          <Skeleton className="size-4 rounded-full" />
          <div className="grid flex-1 gap-1.5">
            <Skeleton className="h-3.5" style={{ width: `${55 + ((i * 17) % 40)}%` }} />
            <Skeleton className="h-3 w-24" />
          </div>
        </div>
      ))}
    </div>
  )
}

/** Dashboard panel: latest events, unread count, mark all read, links to the full list and the settings. */
export function FeedPanel({ className }: { className?: string }) {
  const t = useT()
  const navigate = useNavigate()
  const { data, isPending } = useFeed(null, false, 30)
  const read = useMarkFeedRead()
  const unread = data?.unread ?? 0
  return (
    <aside className={cn('flex min-h-0 flex-col rounded-xl border bg-card', className)} aria-label={t('feed.title')} data-testid="feed-panel">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
        <Bell className="size-4 text-muted-foreground" />
        <h2 className="text-sm font-medium">{t('feed.title')}</h2>
        <CountBadge count={unread} title={t('feed.unreadCount', { count: unread })} />
        <span className="flex-1" />
        {!!data?.pending && (
          <button
            type="button"
            onClick={() => navigate('/feed?pending=1')}
            className="rounded-full bg-warning/15 px-2 py-0.5 text-[11px] font-medium text-warning tabular-nums hover:bg-warning/25"
            data-testid="feed-panel-pending"
          >
            {t('feed.pendingCount', { count: data.pending })}
          </button>
        )}
        <Tooltip content={t('feed.markAllRead')}>
          <Button variant="ghost" size="icon-sm" className="size-7" disabled={!unread} onClick={() => read.mutate({ all: true })} aria-label={t('feed.markAllRead')}>
            <CheckCheck />
          </Button>
        </Tooltip>
        <Tooltip content={t('feed.settings')}>
          <Button variant="ghost" size="icon-sm" className="size-7" onClick={() => navigate('/settings/notifications')} aria-label={t('feed.settings')}>
            <Settings2 />
          </Button>
        </Tooltip>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-1.5">
        {isPending ? (
          <FeedSkeleton />
        ) : !data?.events.length ? (
          <EmptyState compact icon={Bell} title={t('feed.empty')} description={t('feed.emptyDesc')} className="py-10" />
        ) : (
          data.events.map((ev) => <FeedItem key={ev.id} ev={ev} compact />)
        )}
      </div>
      <button type="button" onClick={() => navigate('/feed')} className="h-10 shrink-0 border-t text-[13px] font-medium text-muted-foreground hover:bg-accent/50 hover:text-foreground">
        {t('feed.seeAll')}
      </button>
    </aside>
  )
}
