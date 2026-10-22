import * as React from 'react'
import { store as lsStore } from '@/lib/utils'
import { ErrorBoundary } from '@/components/ui/error-boundary'
import { useFileViewer } from '@/features/files/viewerStore'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { useGlobalBus } from '@/lib/sse'
import { api } from '@/lib/api'
import { prefetchSessions } from '@/lib/queries'
import { prefetchPages } from '@/pages/prefetch'
import { ConnectionBanner } from './ConnectionBanner'
import { useAuthState, useSettings } from '@/lib/queries'
import { useDoneNotifier } from '@/features/notify/useDoneNotifier'
import { checkVersion, useWhatsNew } from '@/features/whatsnew/store'
import { useUI } from '@/stores/ui'
import { withGroups } from '@/i18n'
import { useHotkey } from '@/commands/shortcuts'
import { useCommandStore } from '@/commands/registry'
import { Sidebar } from './Sidebar'
import { TouchDrawers } from './TouchNav'
import { useCompact } from '@/stores/media'
import { useMobileViewport } from '@/lib/mobile-viewport'
import { useShortcutsDialog } from './shortcuts-store'
import { useNav } from './nav'
import { RouteProgress } from './RouteProgress'

// Rarely-used overlays are separate chunks: they are fetched when the browser is idle (or at first use),
// not before the first paint.
const CommandPalette = React.lazy(() => import('./CommandPalette').then((m) => ({ default: m.CommandPalette })))
const ShortcutsDialog = React.lazy(() => import('./ShortcutsDialog').then((m) => ({ default: m.ShortcutsDialog })))
const TourHost = React.lazy(() => import('@/tour/Tour').then((m) => ({ default: m.TourHost })))
const InstallDialog = React.lazy(() => import('@/pwa/InstallDialog').then((m) => ({ default: m.InstallDialog })))

/** Mounts its children once the browser is idle (or after 2.5 s), so they never compete with the first paint. */
function WhenIdle({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = React.useState(false)
  React.useEffect(() => {
    const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (h: number) => void }
    if (w.requestIdleCallback) {
      const h = w.requestIdleCallback(() => setReady(true), { timeout: 2500 })
      return () => w.cancelIdleCallback?.(h)
    }
    const h = setTimeout(() => setReady(true), 1200)
    return () => clearTimeout(h)
  }, [])
  return ready ? <React.Suspense fallback={null}>{children}</React.Suspense> : null
}

/** Once idle: warm the page chunks (navigation becomes instant) and the sessions list. Needs a fast connection. */
function usePrefetch() {
  const qc = useQueryClient()
  React.useEffect(() => {
    const conn = (navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } }).connection
    if (conn?.saveData || /(^|-)2g$/.test(conn?.effectiveType || '')) return
    const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (h: number) => void }
    const run = () => {
      prefetchSessions(qc)
      prefetchPages()
    }
    if (w.requestIdleCallback) {
      const h = w.requestIdleCallback(run, { timeout: 4000 })
      return () => w.cancelIdleCallback?.(h)
    }
    const h = setTimeout(run, 2000)
    return () => clearTimeout(h)
  }, [qc])
}

/** First load only: the entrance animations of the shell are driven by html[data-boot] (index.html). */
function useBootEntrance() {
  React.useEffect(() => {
    const id = setTimeout(() => document.documentElement.removeAttribute('data-boot'), 1300)
    return () => clearTimeout(id)
  }, [])
}

const WhatsNewDialog = React.lazy(withGroups(['show'], () => import('@/features/whatsnew/WhatsNewDialog')))
const FileViewerHost = React.lazy(withGroups(['files'], () => import('@/features/files/Viewer')))

/** The file viewer: its code loads the first time a file is opened. */
function FileViewer() {
  const open = useFileViewer((s) => s.open)
  const [loaded, setLoaded] = React.useState(false)
  React.useEffect(() => {
    if (open) setLoaded(true)
  }, [open])
  return loaded ? (
    <React.Suspense fallback={null}>
      <ErrorBoundary className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 bg-popover">
        <FileViewerHost />
      </ErrorBoundary>
    </React.Suspense>
  ) : null
}

/** "What's new" after an update: decided from the running version, the dialog (Markdown) loads only when shown. */
function WhatsNew() {
  const { data } = useAuthState()
  const open = useWhatsNew((s) => s.open)
  const [loaded, setLoaded] = React.useState(false)
  React.useEffect(() => checkVersion(data?.version), [data?.version])
  React.useEffect(() => {
    if (open) setLoaded(true)
  }, [open])
  return loaded ? (
    <React.Suspense fallback={null}>
      <WhatsNewDialog />
    </React.Suspense>
  ) : null
}

/** The look chosen here (theme, accent, tint) goes to the server: the sign-in page and new browsers show it. */
function useShareLook() {
  const { data: auth } = useAuthState()
  const serverLook = auth?.look
  React.useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const send = () => {
      const { theme, accent, tint, lookChosen } = useUI.getState()
      if (lookChosen) void api.put('/api/settings/look', { theme, accent, tint }).catch(() => {})
    }
    // Once, if the server never got one (servers updated to this version keep the look of the first browser).
    if (serverLook === null) send()
    const unsub = useUI.subscribe((s, prev) => {
      if (s.theme === prev.theme && s.accent === prev.accent && s.tint === prev.tint) return
      clearTimeout(timer)
      timer = setTimeout(send, 600)
    })
    return () => {
      clearTimeout(timer)
      unsub()
    }
  }, [serverLook])
}

/** Keeps the local language in sync with the server settings (source of truth once signed in). */
function useSyncLanguage() {
  const { data } = useSettings()
  const setLanguage = useUI((s) => s.setLanguage)
  React.useEffect(() => {
    if (data?.language) setLanguage(data.language)
  }, [data?.language, setLanguage])
  // "Presentation mode by default": applied once per browser, the first time settings are read.
  React.useEffect(() => {
    if (!data || lsStore.get('mx-presentation-init')) return
    lsStore.set('mx-presentation-init', '1')
    if (data.presentation_default) useUI.getState().setPresentation(true)
  }, [data])
}

function GlobalHotkeys() {
  const navigate = useNavigate()
  const setPalette = useCommandStore((s) => s.setOpen)
  const toggleSidebar = useUI((s) => s.toggleSidebar)
  const setShortcuts = useShortcutsDialog((s) => s.setOpen)
  const nav = useNav()
  useHotkey('mod+k', () => setPalette(!useCommandStore.getState().open), { allowInInput: true })
  useHotkey('mod+\\', toggleSidebar, { allowInInput: true })
  useHotkey('?', () => setShortcuts(true))
  useHotkey('shift+p', () => useUI.getState().setPresentation(!useUI.getState().presentation))
  return (
    <>
      {nav.map((n) => (
        <NavHotkey key={n.to} combo={`g ${n.key}`} onFire={() => navigate(n.to)} />
      ))}
    </>
  )
}
function NavHotkey({ combo, onFire }: { combo: string; onFire: () => void }) {
  useHotkey(combo, onFire)
  return null
}

/** Touch layout: the app opened on `/` goes straight to the last session (Settings -> General -> When the app opens),
 *  before the dashboard is drawn. Only the first screen of a load: the dashboard stays one tap away in the app menu. */
function useTouchHome(touch: boolean): boolean {
  const { pathname, search } = useLocation()
  const [entry] = React.useState(() => touch && pathname === '/' && !search && useUI.getState().touchHome === 'session')
  const left = React.useRef(false)
  if (pathname !== '/') left.current = true
  return entry && !left.current
}

/** Scroll the main region to top on page change (not on search-param changes). */
function useScrollReset(ref: React.RefObject<HTMLElement | null>) {
  const { pathname } = useLocation()
  React.useLayoutEffect(() => {
    ref.current?.scrollTo({ top: 0 })
  }, [pathname, ref])
}

export function AppShell() {
  const bus = useGlobalBus(true)
  useSyncLanguage()
  useShareLook()
  useBootEntrance()
  usePrefetch()
  useDoneNotifier()
  const main = React.useRef<HTMLElement>(null)
  useScrollReset(main)
  useMobileViewport()
  const touch = useCompact()
  const goSessions = useTouchHome(touch)
  return (
    <div className="flex h-dvh w-full overflow-hidden bg-background">
      <RouteProgress />
      <ConnectionBanner status={bus} />
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:rounded-md focus:bg-popover focus:px-3 focus:py-2 focus:shadow-pop">
        Skip to content
      </a>
      {!touch && <Sidebar />}
      <main
        id="main"
        ref={main}
        tabIndex={-1}
        className="relative flex min-w-0 flex-1 flex-col overflow-y-auto pr-[var(--safe-right)] outline-none [scrollbar-gutter:stable] max-md:pb-[var(--safe-bottom-ui)] max-md:pl-[var(--safe-left)]"
      >
        {goSessions ? <Navigate to="/sessions" replace /> : <Outlet />}
      </main>
      {touch && <TouchDrawers />}
      <GlobalHotkeys />
      <FileViewer />
      <WhenIdle>
        <CommandPalette />
        <ShortcutsDialog />
        <InstallDialog />
        <WhatsNew />
        <TourHost />
      </WhenIdle>
    </div>
  )
}
