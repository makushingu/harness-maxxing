import * as React from 'react'
import { ErrorBoundary } from '@/components/ui/error-boundary'
import { RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { onUnauthorized, ApiError } from '@/lib/api'
import { isLiveKey, qk } from '@/lib/queries/keys'
import { ConfirmHost, Toaster, TooltipProvider } from '@/components/ui'
import { createAppRouter } from './routes'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      gcTime: 10 * 60_000,
      refetchOnWindowFocus: (q) => !isLiveKey(q.queryKey),
      retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
    },
    mutations: { retry: false },
  },
})

const router = createAppRouter(queryClient)

// 401 on any protected call: the session expired → back to /login, keeping where we were.
let redirecting = false
onUnauthorized(() => {
  if (redirecting) return
  const loc = window.location
  if (loc.pathname === '/login' || loc.pathname === '/setup') return
  redirecting = true
  queryClient.setQueryData(qk.authState, (old: object | undefined) => (old ? { ...old, authenticated: false } : old))
  const next = encodeURIComponent(loc.pathname + loc.search)
  router.navigate(`/login?next=${next}`, { replace: true }).finally(() => {
    redirecting = false
  })
})

export function App() {
  return (
    <React.StrictMode>
      {/* last resort: an error outside the pages (dialogs, toasts) shows a reload screen, never a blank page */}
      <ErrorBoundary variant="page">
        <QueryClientProvider client={queryClient}>
          <TooltipProvider delayDuration={350} skipDelayDuration={150}>
            <RouterProvider router={router} />
            <ConfirmHost />
            <Toaster />
          </TooltipProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </React.StrictMode>
  )
}
