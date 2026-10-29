// The main API calls of each page, started before the page's code is there: at boot (lib/boot.ts), when a
// navigation starts (the AppShell route loader) and when a nav link is hovered or focused (prefetchPage).
// Same query keys and fetchers as the pages' hooks: the page finds its data in the cache (or in flight) instead
// of asking for it after its chunk downloaded and rendered once. prefetchQuery skips fresh data, so calling
// this often is cheap.
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import {
  backupQuery,
  claudeStatusQuery,
  cronRunsQuery,
  cronsQuery,
  dashboardQuery,
  docQuery,
  docsQuery,
  extensionsQuery,
  feedPagesQuery,
  feedQuery,
  fileKindQuery,
  healthQuery,
  prefetchTail,
  secretsQuery,
  servicesQuery,
  sessionQuery,
  sessionsQuery,
  settingsQuery,
  tasksQuery,
  telegramQuery,
  tokenStatsQuery,
  trashQuery,
  versionQuery,
  workspaceQuery,
} from '@/lib/queries'
import { prefetchPageChunk } from './prefetch'

type Q = { queryKey: readonly unknown[]; queryFn: (...a: never[]) => Promise<unknown>; staleTime?: number }

const SETTINGS: Record<string, () => Q[]> = {
  stats: () => [tokenStatsQuery()],
  claude: () => [claudeStatusQuery()],
  system: () => [healthQuery(), servicesQuery(), versionQuery()],
  keys: () => [secretsQuery()],
  backup: () => [backupQuery()],
  telegram: () => [telegramQuery()],
  trash: () => [trashQuery()],
}

/** Starts the requests of the page at `pathname` (+ `search`). Unknown pages: nothing. */
export function prefetchPageData(qc: QueryClient, pathname: string, search = '') {
  const params = new URLSearchParams(search)
  const queries: Q[] = []
  const [, top = '', sub = ''] = pathname.split('/')
  switch (top) {
    case '':
      queries.push(dashboardQuery(), feedQuery(null, false, 30))
      break
    case 'sessions': {
      // The tree (its archived folds load their list when opened), the columns' header data, and the open sessions
      // with their thread.
      queries.push(sessionsQuery(undefined, false), claudeStatusQuery(), telegramQuery())
      const ids = [params.get('session'), ...(params.get('open') || '').split(',')].filter((x): x is string => !!x)
      for (const id of new Set(ids).values()) {
        queries.push(sessionQuery(id))
        prefetchTail(id)
      }
      break
    }
    case 'files':
      queries.push(fileKindQuery(qc, (params.get('path') || '').replace(/(.)\/+$/, '$1')))
      break
    case 'tasks':
      queries.push(tasksQuery())
      break
    case 'crons':
      queries.push(cronsQuery(), cronRunsQuery(null, 8))
      break
    case 'feed':
      void qc.prefetchInfiniteQuery(feedPagesQuery(null, false))
      break
    case 'settings':
      queries.push(...(SETTINGS[sub]?.() ?? []))
      break
    case 'docs':
      queries.push(docsQuery())
      if (sub) queries.push(docQuery(sub))
      break
    case 'x':
      queries.push(extensionsQuery())
      break
  }
  for (const q of queries) void qc.prefetchQuery(q as Parameters<QueryClient['prefetchQuery']>[0])
}

/** The shell's own data (sidebar, header indicators, language sync), on every page. */
export function prefetchShell(qc: QueryClient) {
  for (const q of [workspaceQuery(), healthQuery(), extensionsQuery(), versionQuery(), settingsQuery()]) void qc.prefetchQuery(q as Parameters<QueryClient['prefetchQuery']>[0])
}

/** A nav link is about to be clicked (hover, focus, touch): load the page's code and its data. */
export function prefetchPage(qc: QueryClient, to: string) {
  const url = new URL(to, window.location.origin)
  prefetchPageChunk(url.pathname)
  prefetchPageData(qc, url.pathname, url.search)
}

/** Props for a nav link: hovering, focusing or touching it prefetches its page (see prefetchPage). */
export function usePrefetchLink() {
  const qc = useQueryClient()
  return (to: string) => {
    const go = () => prefetchPage(qc, to)
    return { onPointerEnter: go, onFocus: go, onTouchStart: go }
  }
}
