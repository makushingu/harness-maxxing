// /feed - every notification of the last 30 days: filter by source or unread, mark read, load more.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Bell, CheckCheck, Settings2 } from 'lucide-react'
import { useFeedPages, useMarkFeedRead } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Button, Card, EmptyState, Switch } from '@/components/ui'
import { Page } from '@/components/shell/Page'
import { FeedItem, FeedSkeleton } from '@/features/feed/FeedItems'

export default function FeedPage() {
  const t = useT()
  const navigate = useNavigate()
  const [source, setSource] = React.useState<string | null>(null)
  const [unreadOnly, setUnreadOnly] = React.useState(false)
  const pages = useFeedPages(source, unreadOnly)
  const read = useMarkFeedRead()
  const events = pages.data?.pages.flatMap((p) => p.events) ?? []
  // Every page carries the totals of all sources (whatever the filter): keep the last ones while a filter loads.
  const head = pages.data?.pages[0]
  const [summary, setSummary] = React.useState(head)
  if (head && head !== summary) setSummary(head)
  const sources = summary?.sources ?? []
  const unread = summary?.unread ?? 0
  const chip = (active: boolean) =>
    cn('inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-xs transition-colors max-md:h-10 pointer-coarse:h-10', active ? 'border-primary bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground')
  return (
    <Page
      title={t('feed.title')}
      description={t('feed.pageDesc')}
      actions={
        <>
          <Button variant="outline" size="sm" disabled={!unread} onClick={() => read.mutate(source ? { source } : { all: true })}>
            <CheckCheck /> <span className="max-sm:hidden">{t('feed.markAllRead')}</span>
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => navigate('/settings/notifications')} aria-label={t('feed.settings')}>
            <Settings2 />
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t('feed.sources')}>
          <button type="button" className={chip(source === null)} onClick={() => setSource(null)}>
            {t('feed.allSources')}
          </button>
          {sources.map((s) => (
            <button key={s.source} type="button" className={chip(source === s.source)} onClick={() => setSource(s.source)} data-testid="feed-chip">
              {s.source}
              {s.unread > 0 && <span className="rounded-full bg-primary px-1.5 text-[10px] text-primary-foreground tabular-nums">{s.unread}</span>}
            </button>
          ))}
          <label className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
            <Switch checked={unreadOnly} onCheckedChange={setUnreadOnly} aria-label={t('feed.unreadOnly')} />
            {t('feed.unreadOnly')}
          </label>
        </div>
        <Card className="gap-0 p-1.5">
          {pages.isPending ? (
            <FeedSkeleton rows={8} />
          ) : !events.length ? (
            <EmptyState compact icon={Bell} title={t('feed.empty')} description={t('feed.emptyDesc')} className="py-12" />
          ) : (
            events.map((ev) => <FeedItem key={ev.id} ev={ev} />)
          )}
          {pages.hasNextPage && (
            <div className="flex justify-center p-2">
              <Button variant="ghost" size="sm" loading={pages.isFetchingNextPage} onClick={() => pages.fetchNextPage()}>
                {t('feed.more')}
              </Button>
            </div>
          )}
        </Card>
      </div>
    </Page>
  )
}
