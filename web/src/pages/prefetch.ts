// Warm-up of the lazy page chunks (the same modules routes.tsx loads on navigation): in the background once the
// shell is idle (most used first, one at a time, see AppShell), and for one page when its nav link is hovered.
const PAGE_LOADERS: Record<string, () => Promise<unknown>> = {
  sessions: () => import('./sessions'),
  '': () => import('./dashboard'),
  files: () => import('./files'),
  tasks: () => import('./tasks'),
  crons: () => import('./crons'),
  settings: () => import('./settings'),
  feed: () => import('./feed'),
  docs: () => import('./docs'),
  x: () => import('./ext/hub'),
}

export function prefetchPages() {
  let chain: Promise<void> = Promise.resolve()
  for (const load of Object.values(PAGE_LOADERS))
    chain = chain
      .then(() => new Promise<void>((r) => setTimeout(r, 150)))
      .then(() => load())
      .then(
        () => undefined,
        () => undefined,
      )
}

/** The chunk of the page at `pathname` (the browser and Vite dedupe repeated imports). */
export function prefetchPageChunk(pathname: string) {
  const top = pathname.split('/')[1] ?? ''
  const load = top === 'x' && pathname.split('/').length > 2 ? () => import('./ext') : PAGE_LOADERS[top]
  load?.().catch(() => undefined)
}
