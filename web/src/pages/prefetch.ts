// Warm-up of the lazy page chunks (the same modules routes.tsx loads on navigation): in the background once the
// shell is idle (most used first, one at a time, see AppShell), and for one page when its nav link is hovered.
import { withGroups } from '@/i18n'

// Each with the dictionary groups its route waits for (routes.tsx), so a warmed page opens without a fetch.
const PAGE_LOADERS: Record<string, () => Promise<unknown>> = {
  sessions: withGroups(['files'], () => import('./sessions')),
  '': () => import('./dashboard'),
  files: withGroups(['files', 'media'], () => import('./files')),
  tasks: withGroups(['tasks'], () => import('./tasks')),
  settings: withGroups(['settings', 'auth', 'show', 'tasks'], () => import('./settings')),
  feed: () => import('./feed'),
  docs: () => import('./docs'),
  // optional pages (Settings -> Features): warmed only when switched on (see lib/prefetchIdle.ts)
  agents: withGroups(['agents', 'tasks', 'files'], () => import('../features/agents/AgentsLayout')),
  team: withGroups(['team'], () => import('../features/team/TeamPage')),
  jarvis: withGroups(['jarvis', 'files'], () => import('./jarvis')),
  infra: withGroups(['infra'], () => import('../features/infra/InfraPage')),
  mail: withGroups(['mail'], () => import('../features/mail/MailPage')),
  git: withGroups(['git'], () => import('../features/git/GitPage')),
}
/** The pages every install has, warmed when no list is given. */
const ALWAYS = ['sessions', '', 'files', 'tasks', 'settings', 'feed', 'docs']

/** `tops`: the pages to warm, by their first path segment ('' = dashboard, 'x/' = an extension page), in order.
 *  `stop()` is asked before each page (stopped, a slow connection now): the chain ends there. Resolves at its end. */
export function prefetchPages(tops: string[] = ALWAYS, stop: () => boolean = () => false): Promise<void> {
  let chain: Promise<void> = Promise.resolve()
  const loads = tops.map((t) => (t === 'x/' ? () => import('./ext') : PAGE_LOADERS[t])).filter((l): l is () => Promise<unknown> => !!l)
  for (const load of loads)
    chain = chain
      .then(() => new Promise<void>((r) => setTimeout(r, 150)))
      .then(() => (stop() ? undefined : load()))
      .then(
        () => undefined,
        () => undefined,
      )
  return chain
}

/** The chunk of the page at `pathname` (the browser and Vite dedupe repeated imports). */
export function prefetchPageChunk(pathname: string) {
  const top = pathname.split('/')[1] ?? ''
  const load = top === 'x' && pathname.split('/').length > 2 ? () => import('./ext') : PAGE_LOADERS[top]
  load?.().catch(() => undefined)
}
