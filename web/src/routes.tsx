// THE route table. To add a page:
//   1. create src/pages/<name>/index.tsx with `export default function XxxPage()` rendering <Page …>
//   2. add an entry below with `lazy: page(() => import('./pages/<name>'))` (code-split chunk); add the dictionary
//      groups it shows (i18n/groups.ts) as a 2nd argument, e.g. `page(() => import('./pages/tasks'), ['tasks'])`
//   3. if it belongs in the primary nav, add it to components/shell/nav.ts (sidebar, tab bar, palette, g-shortcut)
// Feature pages own their sub-paths (`sessions/*`): use nested <Routes> inside the page or add `children` here.
import { createBrowserRouter, Navigate, type RouteObject } from 'react-router'
import type { QueryClient } from '@tanstack/react-query'
import { AppShell } from '@/components/shell/AppShell'
import { RouteError, NotFound } from '@/components/shell/RouteError'
import { Root, AuthLayoutFallback } from '@/pages/Root'
import { prefetchPageData } from '@/pages/pageData'
import { withGroups } from '@/i18n'
import type { Group } from '@/i18n/groups'

type PageModule = { default: React.ComponentType }
const page = (load: () => Promise<PageModule>, groups: Group[] = []) => async () => ({ Component: (await withGroups(groups, load)()).default })

let client: QueryClient | null = null

export const routes: RouteObject[] = [
  {
    Component: Root,
    errorElement: <RouteError />,
    HydrateFallback: AuthLayoutFallback,
    children: [
      { path: 'setup', lazy: page(() => import('./pages/auth/Setup'), ['auth']) },
      { path: 'login', lazy: page(() => import('./pages/auth/Login'), ['auth']) },
      { path: 'welcome', lazy: page(() => import('./pages/onboarding'), ['auth', 'settings']) },
      {
        Component: AppShell,
        errorElement: <RouteError />,
        // Starts the page's requests with its chunk download (not after it): see pages/pageData.ts.
        loader: ({ request }) => {
          const url = new URL(request.url)
          if (client) prefetchPageData(client, url.pathname, url.search)
          return null
        },
        // Again on a page change, or on a new file path (other query changes are the page's own business).
        shouldRevalidate: ({ currentUrl, nextUrl }) =>
          currentUrl.pathname !== nextUrl.pathname || (nextUrl.pathname === '/files' && currentUrl.search !== nextUrl.search),
        children: [
          { index: true, lazy: page(() => import('./pages/dashboard')) },
          // Feature pages — implemented in src/pages/<name>/index.tsx
          { path: 'sessions/*', lazy: page(() => import('./pages/sessions'), ['files']) },
          { path: 'files/*', lazy: page(() => import('./pages/files'), ['files']) },
          { path: 'tasks/*', lazy: page(() => import('./pages/tasks'), ['tasks']) },
          { path: 'crons/*', lazy: page(() => import('./pages/crons'), ['tasks']) },
          { path: 'feed', lazy: page(() => import('./pages/feed')) },
          // Optional feature pages (Settings -> Features)
          { path: 'git', lazy: page(() => import('./features/git/GitPage'), ['git']) },
          { path: 'team', lazy: page(() => import('./features/team/TeamPage'), ['team']) },
          { path: 'infra', lazy: page(() => import('./features/infra/InfraPage'), ['infra']) },
          // Settings & docs
          { path: 'settings', element: <Navigate to="/settings/general" replace /> },
          { path: 'settings/docs', element: <Navigate to="/docs" replace /> },
          { path: 'settings/:section', lazy: page(() => import('./pages/settings'), ['settings', 'auth', 'show']) },
          { path: 'docs', lazy: page(() => import('./pages/docs')) },
          { path: 'docs/:slug', lazy: page(() => import('./pages/docs')) },
          // Extension pages: /x/<id> loads /ext/<id>/page.js
          { path: 'x', lazy: page(() => import('./pages/ext/hub')) },
          { path: 'x/:id/*', lazy: page(() => import('./pages/ext')) },
          { path: '*', Component: NotFound },
        ],
      },
    ],
  },
]

export function createAppRouter(qc: QueryClient) {
  client = qc
  return createBrowserRouter(routes)
}
