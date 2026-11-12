// /feed - every notification of the last 30 days. The second-level sidebar (PageList; touch: the left drawer) picks
// what to see: all, the alerts to handle, or one source, each with its unread count; the page shows them by day, All /
// Unread at the top right. The choice is in the URL (?source=<name>, ?pending=1, ?unread=1).
import * as React from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { Bell, Bot, CheckCheck, Clock, Hand, HeartPulse, type LucideIcon, Rss, Server, Settings2, ShieldCheck, Webhook } from 'lucide-react'
import { useFeedPages, useFeedSettings, useMarkFeedRead } from '@/lib/queries'
import type { FeedEvent } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Button, Card, CountBadge, EmptyState } from '@/components/ui'
import { Page } from '@/components/shell/Page'
import { ListChips, PageList } from '@/components/shell/PageList'
import { FeedItem, FeedSkeleton } from '@/features/feed/FeedItems'

/** The icon of a source in the list (the built-in ones; a webhook or a script gets the generic one). */
const SOURCE_ICON: Record<string, LucideIcon> = { crons: Clock, system: Server, agents: Bot, health: HeartPulse, security: ShieldCheck, stripe: Webhook, shopify: Webhook, github: Webhook }

/** A source's name as people read it: its label in the settings, else the id with spaces and a capital. */
const pretty = (id: string) => (id.charAt(0).toUpperCase() + id.slice(1)).replace(/[-_]+/g, ' ')

export default function FeedPage() {
  const t = useT()
  const lang = useLang()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const source = params.get('source')
  const pendingOnly = params.get('pending') === '1'
  const unreadOnly = params.get('unread') === '1'
  const pick = (next: { source?: string | null; pending?: boolean; unread?: boolean }) => {
    const p = new URLSearchParams(params)
    const set = (k: string, v: string | null) => (v ? p.set(k, v) : p.delete(k))
    if (next.source !== undefined) set('source', next.source)
    if (next.pending !== undefined) set('pending', next.pending ? '1' : null)
    if (next.unread !== undefined) set('unread', next.unread ? '1' : null)
    setParams(p, { replace: true })
  }
  const pages = useFeedPages(pendingOnly ? null : source, unreadOnly, pendingOnly)
  const read = useMarkFeedRead()
  const events = pages.data?.pages.flatMap((p) => p.events) ?? []
  // Every page carries the totals of all sources (whatever the filter): keep the last ones while a filter loads.
  const head = pages.data?.pages[0]
  const [summary, setSummary] = React.useState(head)
  if (head && head !== summary) setSummary(head)
  const sources = summary?.sources ?? []
  const unread = summary?.unread ?? 0
  const pending = summary?.pending ?? 0
  const days = React.useMemo(() => byDay(events), [events])
  const { data: settings } = useFeedSettings()
  const nameOf = (id: string) => {
    const label = settings?.sources.find((x) => x.source === id)?.label
    return label && label !== id ? label : pretty(id)
  }
  const shownUnread = pendingOnly ? 0 : source ? sources.find((s) => s.source === source)?.unread ?? 0 : unread

  const row = (active: boolean) =>
    cn(
      'flex h-9 w-full min-w-0 items-center gap-2.5 rounded-md px-2.5 text-left text-sm transition-colors pointer-coarse:h-11',
      active ? 'bg-accent font-medium text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
    )
  return (
    <Page
      title={pendingOnly ? t('feed.pending') : source ? nameOf(source) : t('feed.everySource')}
      sensitiveTitle={t('feed.title')}
      description={t('feed.pageDesc')}
      actions={
        <>
          <Button variant="outline" size="sm" disabled={!shownUnread} onClick={() => read.mutate(source && !pendingOnly ? { source } : { all: true })}>
            <CheckCheck /> <span className="max-lg:sr-only">{t('feed.markAllRead')}</span>
          </Button>
          <Button variant="ghost" size="icon-sm" className="max-md:hidden" onClick={() => navigate('/settings/notifications')} aria-label={t('feed.settings')}>
            <Settings2 />
          </Button>
        </>
      }
    >
      {/* the list: reached from Home (its count) on a computer when the second bar is closed */}
      <PageList id="feed" entry="" label={t('feed.title')}>
        <div className="shrink-0 px-2 pt-2">
          <ListChips
            label={t('feed.unreadOnly')}
            value={unreadOnly ? 'unread' : 'all'}
            onChange={(v) => pick({ unread: v === 'unread' })}
            items={[
              { key: 'all', label: t('feed.allSources') },
              { key: 'unread', label: t('feed.unreadShort'), count: unread },
            ]}
          />
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto p-2" aria-label={t('feed.sources')} data-testid="feed-nav">
          <button type="button" className={row(!source && !pendingOnly)} onClick={() => pick({ source: null, pending: false })}>
            <Bell className={cn('size-4 shrink-0', !source && !pendingOnly && 'text-primary')} />
            <span className="min-w-0 flex-1 truncate">{t('feed.everySource')}</span>
            <CountBadge count={unread} />
          </button>
          {(pending > 0 || pendingOnly) && (
            <button type="button" className={cn(row(pendingOnly), 'mt-0.5')} onClick={() => pick({ source: null, pending: true })} data-testid="feed-pending">
              <Hand className="size-4 shrink-0" />
              <span className="min-w-0 flex-1 truncate">{t('feed.pending')}</span>
              {pending > 0 && <span className="rounded-full bg-warning/15 px-1.5 text-[11px] font-semibold text-warning tabular-nums">{pending}</span>}
            </button>
          )}
          {sources.length > 0 && <div className="mt-4 mb-1 px-2.5 text-[11px] font-semibold tracking-wider text-muted-foreground/80 uppercase">{t('feed.sources')}</div>}
          {sources.map((s) => {
            const Icon = SOURCE_ICON[s.source] || Rss
            const on = source === s.source && !pendingOnly
            return (
              <button key={s.source} type="button" className={cn(row(on), 'mt-0.5')} onClick={() => pick({ source: s.source, pending: false })} title={s.source} data-testid="feed-chip">
                <Icon className={cn('size-4 shrink-0', on && 'text-primary')} />
                <span className="min-w-0 flex-1 truncate">{nameOf(s.source)}</span>
                {s.unread > 0 ? <CountBadge count={s.unread} /> : <span className="text-xs text-muted-foreground/70 tabular-nums">{s.total}</span>}
              </button>
            )
          })}
        </nav>
      </PageList>
      <div className="mx-auto grid w-full max-w-3xl grid-cols-[minmax(0,1fr)] gap-5">
        {pages.isPending ? (
          <Card className="gap-0 p-2">
            <FeedSkeleton rows={8} />
          </Card>
        ) : !events.length ? (
          <EmptyState icon={Bell} title={t('feed.empty')} description={t('feed.emptyDesc')} className="py-16" />
        ) : (
          days.map((d) => (
            <section key={d.key} className="grid gap-2" data-testid="feed-day">
              <h2 className="px-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{dayLabel(d.at, lang, t)}</h2>
              <div className="divide-y border-y">
                {d.events.map((ev) => (
                  <FeedItem key={ev.id} ev={ev} roomy />
                ))}
              </div>
            </section>
          ))
        )}
        {pages.hasNextPage && (
          <div className="flex justify-center pb-6">
            <Button variant="outline" size="sm" loading={pages.isFetchingNextPage} onClick={() => pages.fetchNextPage()}>
              {t('feed.more')}
            </Button>
          </div>
        )}
      </div>
    </Page>
  )
}

/** The events in days (newest first, as they come). */
function byDay(events: FeedEvent[]) {
  const out: { key: string; at: number; events: FeedEvent[] }[] = []
  for (const ev of events) {
    const key = new Date(ev.at * 1000).toDateString()
    const last = out.at(-1)
    if (last?.key === key) last.events.push(ev)
    else out.push({ key, at: ev.at, events: [ev] })
  }
  return out
}

function dayLabel(at: number, lang: string, t: ReturnType<typeof useT>) {
  const d = new Date(at * 1000)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) return t('team.today')
  if (d.toDateString() === new Date(now.getTime() - 86400_000).toDateString()) return t('team.yesterday')
  return d.toLocaleDateString(lang, { weekday: 'long', day: 'numeric', month: 'long' })
}
