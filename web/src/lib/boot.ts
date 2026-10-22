// App boot: start the API calls of the first screen while the JS still downloads and runs.
// Without this they only start after the first React render (the hooks' effects), i.e. once every chunk is there,
// parsed and rendered once. Same query keys and fetchers as the hooks (they find the data in the cache), so this
// changes when the requests start, not what is shown. Only for a signed-in user (the early auth check of
// index.html says so); a login / setup / onboarding screen prefetches nothing.
import type { QueryClient } from '@tanstack/react-query'
import { prefetchPageData, prefetchShell } from '@/pages/pageData'

export function bootPrefetch(qc: QueryClient) {
  const early = window.__mxAuth // read, not consumed (fetchAuthState takes it)
  if (!early) return
  void early.then((auth) => {
    if (!auth?.authenticated || auth.setup_required || !auth.onboarding_completed) return
    const { pathname, search } = window.location
    if (pathname === '/login' || pathname === '/setup' || pathname === '/welcome') return
    prefetchShell(qc)
    prefetchPageData(qc, pathname, search)
  })
}
