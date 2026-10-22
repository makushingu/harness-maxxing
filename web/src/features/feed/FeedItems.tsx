// One event of the notifications feed + the dashboard panel. Clicking an event marks it read and opens
// its link (inside the app, or a new tab for an outside one).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Bell, CheckCheck, CheckCircle2, CircleAlert, Info, MoreHorizontal, Settings2, Trash2, TriangleAlert } from 'lucide-react'
import { useDeleteFeedEvent, useFeed, useMarkFeedRead } from '@/lib/queries'
import type { FeedEvent, FeedLevel } from '@/lib/types'
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
      <button type="button" onClick={open} className="grid min-w-0 flex-1 gap-0.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span className={cn('flex min-w-0 items-center gap-1.5 text-[13px] leading-snug', !ev.read && 'font-medium')}>
          <span className={cn(compact ? 'line-clamp-1' : 'line-clamp-2')}>
            <Sensitive length={12}>{ev.title}</Sensitive>
          </span>
          {ev.count > 1 && <span className="shrink-0 rounded bg-muted px-1 text-[10px] font-medium text-muted-foreground tabular-nums">×{ev.count}</span>}
        </span>
        {ev.body && (
          <span className={cn('text-xs break-words whitespace-pre-line text-muted-foreground', compact ? 'line-clamp-2' : 'line-clamp-4')}>
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
