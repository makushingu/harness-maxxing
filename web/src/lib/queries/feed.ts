import { useInfiniteQuery, useQuery, type InfiniteData } from '@tanstack/react-query'
import { api, withQuery } from '../api'
import type { FeedEvent, FeedHook, FeedHookKind, FeedList, FeedRule, FeedSettings } from '../types'
import { qk } from './keys'
import { useMut } from './util'

const inv = [qk.feed.all] as const

export const feedQuery = (source: string | null = null, unread = false, limit = 30) => ({
  queryKey: qk.feed.list(source, unread, limit),
  queryFn: () => api.get<FeedList>(withQuery('/api/feed', { source: source || undefined, unread: unread || undefined, limit })),
})
/** Latest events (dashboard panel). Live: the bus topic "feed" refreshes it (new events are watched every 3 s);
 *  the slow interval only catches read marks made elsewhere (Telegram buttons). */
export function useFeed(source: string | null = null, unread = false, limit = 30) {
  return useQuery({ ...feedQuery(source, unread, limit), refetchInterval: 5 * 60_000 })
}

export const feedPagesQuery = (source: string | null = null, unread = false) => ({
  queryKey: qk.feed.pages(source, unread),
  initialPageParam: 0,
  queryFn: ({ pageParam }: { pageParam: number }) =>
    api.get<FeedList>(withQuery('/api/feed', { source: source || undefined, unread: unread || undefined, limit: 50, before: pageParam || undefined })),
  getNextPageParam: (last: FeedList) => (last.more && last.events.length ? last.events[last.events.length - 1].id : undefined),
})
/** Every event, page by page (the "See all" page). */
export function useFeedPages(source: string | null = null, unread = false) {
  return useInfiniteQuery(feedPagesQuery(source, unread))
}

export function useMarkFeedRead() {
  return useMut((b: { ids?: number[]; source?: string; all?: boolean }) => api.post<{ unread: number }>('/api/feed/read', b), {
    // Shown as read at once; the refetch (invalidate) brings the server's counts.
    optimistic: ({ ids, source, all }) => {
      const hit = (e: FeedEvent) => all || (source ? e.source === source : !!ids?.includes(e.id))
      const mark = (l: FeedList): FeedList => {
        const n = l.events.filter((e) => !e.read && hit(e)).length
        return {
          ...l,
          events: l.events.map((e) => (hit(e) ? { ...e, read: true } : e)),
          unread: all ? 0 : Math.max(0, l.unread - n),
          sources: l.sources.map((x) => (all || x.source === source ? { ...x, unread: 0 } : x)),
        }
      }
      return [
        { key: ['feed', 'list'], update: mark },
        { key: ['feed', 'pages'], update: (d: InfiniteData<FeedList>) => ({ ...d, pages: d.pages.map(mark) }) },
      ]
    },
    invalidate: inv,
    errorToast: false,
  })
}
export function useDeleteFeedEvent() {
  return useMut((id: number) => api.del<{ ok: boolean }>(`/api/feed/${id}`), { invalidate: inv })
}
export function useFeedSettings() {
  return useQuery({ queryKey: qk.feed.settings, queryFn: () => api.get<FeedSettings>('/api/feed/settings') })
}
export function useSaveFeedSettings() {
  return useMut((b: { telegram?: boolean; rules?: Record<string, FeedRule> }) => api.put<FeedSettings>('/api/feed/settings', b), {
    optimistic: (b) => [
      {
        key: qk.feed.settings,
        update: (f: FeedSettings) => ({
          ...f,
          telegram: b.telegram ?? f.telegram,
          sources: f.sources.map((x) => (b.rules?.[x.source] ? { ...x, rule: b.rules[x.source] } : x)),
        }),
      },
    ],
    invalidate: inv,
  })
}
export function useCreateHook() {
  return useMut((b: { name: string; kind: FeedHookKind; secret?: string }) => api.post<FeedHook>('/api/feed/hooks', b), { invalidate: inv })
}
export function usePatchHook() {
  return useMut(({ id, ...b }: { id: string; secret?: string; regenerate?: boolean }) => api.patch<FeedHook>(`/api/feed/hooks/${encodeURIComponent(id)}`, b), { invalidate: inv })
}
export function useDeleteHook() {
  return useMut((id: string) => api.del<{ ok: boolean }>(`/api/feed/hooks/${encodeURIComponent(id)}`), { invalidate: inv })
}
export function useTestHook() {
  return useMut((id: string) => api.post<{ event: FeedEvent | null }>(`/api/feed/hooks/${encodeURIComponent(id)}/test`), { invalidate: inv })
}
