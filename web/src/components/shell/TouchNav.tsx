// Touch layout (phones, tablets - html[data-compact], stores/media.ts): no sidebar and no tab bar. Two buttons at the
// top of every screen open two drawers: the sessions on the left, the rest of the app on the right (every entry of the
// desktop sidebar: pages, extensions, notifications, feedback, settings, update and the status card).
import * as React from 'react'
import { create } from 'zustand'
import { NavLink, useLocation } from 'react-router'
import { Blocks, Bell, ChevronRight, Download, LayoutGrid, Menu, MessageSquareText, Search, Settings } from 'lucide-react'
import { useAgentsAttention, useExtensions, useFeed, useHealth, useWorkspace } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useT, withGroups } from '@/i18n'
import { openPalette } from '@/commands/registry'
import { CountBadge, CountDot, NamedIcon } from '@/components/ui'
import { Drawer, DrawerContent, DrawerTitle } from '@/components/ui/drawer'
import { isStandalone, installApp, useInstallMode } from '@/pwa'
import { useTour } from '@/tour/store'
import { navTourId, useNav } from './nav'
import { Logo } from './Logo'
import { healthTone, StatusFooter } from './HealthIndicator'
import { UpdateIndicator, usePendingUpdate } from './UpdateIndicator'
import { useFeedbackDialog } from './feedback-store'

type Panel = 'sessions' | 'app' | null
export const useTouchNav = create<{ panel: Panel; setPanel: (p: Panel) => void }>((set) => ({ panel: null, setPanel: (panel) => set({ panel }) }))

const topButton =
  'relative flex size-11 shrink-0 items-center justify-center rounded-xl text-foreground outline-none transition-colors hover:bg-accent active:bg-accent focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-[22px]'

/** ☰ - opens the sessions. The counter: sessions with an unread answer; a dot when one is running. */
export function TouchSessionsButton({ className }: { className?: string }) {
  const t = useT()
  const { data } = useWorkspace()
  let unread = 0
  let running = 0
  for (const p of data?.projects || [])
    for (const tp of p.topics) {
      unread += tp.unread
      running += tp.running
    }
  return (
    <button type="button" className={cn(topButton, '-ml-1', className)} aria-label={t('shell.openSessions')} onClick={() => useTouchNav.getState().setPanel('sessions')} data-tour="touch-sessions">
      <Menu />
      {unread > 0 ? (
        <CountBadge count={unread} className="absolute top-0.5 right-0 ring-2 ring-background" title={t('sessions.showUnread', { count: unread })} />
      ) : running > 0 ? (
        <CountDot tone="running" className="absolute top-1.5 right-1.5" />
      ) : null}
    </button>
  )
}

/** ⊞ - opens the rest of the app. A dot: an update is waiting or the server needs attention. */
export function TouchAppButton({ className }: { className?: string }) {
  const t = useT()
  const pending = usePendingUpdate()
  const { data: h } = useHealth()
  const tone = healthTone(h)
  const dot = pending || tone === 'error' || tone === 'warn'
  return (
    <button type="button" className={cn(topButton, '-mr-1', className)} aria-label={t('shell.openApp')} onClick={() => useTouchNav.getState().setPanel('app')} data-tour="nav">
      <LayoutGrid />
      {dot && <span aria-hidden className={cn('absolute top-2 right-2 size-2 rounded-full ring-2 ring-background', pending ? 'bg-primary' : tone === 'error' ? 'bg-destructive' : 'bg-warning')} />}
    </button>
  )
}

const SessionsPanel = React.lazy(withGroups(['files'], () => import('@/pages/sessions/SessionsPanel')))

/** The two drawers and their edge gestures. Mounted by AppShell in the touch layout. */
export function TouchDrawers() {
  const t = useT()
  const panel = useTouchNav((s) => s.panel)
  const setPanel = useTouchNav((s) => s.setPanel)
  const location = useLocation()
  // During the guided tour its cards sit above the drawers: no focus trap, a tap on a card does not close them.
  const tour = useTour((s) => s.active)
  const keep = (e: Event) => tour && e.preventDefault()
  // Any navigation closes them (a page, a session picked in the list).
  React.useEffect(() => setPanel(null), [location.pathname, location.search, setPanel])
  useEdgeOpen()
  return (
    <>
      <Drawer open={panel === 'sessions'} onOpenChange={(o) => setPanel(o ? 'sessions' : null)} modal={!tour}>
        <DrawerContent side="left" aria-describedby={undefined} data-testid="touch-sessions" onInteractOutside={keep}>
          <DrawerTitle className="sr-only">{t('nav.sessions')}</DrawerTitle>
          <React.Suspense fallback={null}>
            <SessionsPanel />
          </React.Suspense>
        </DrawerContent>
      </Drawer>
      <Drawer open={panel === 'app'} onOpenChange={(o) => setPanel(o ? 'app' : null)} modal={!tour}>
        <DrawerContent side="right" aria-describedby={undefined} data-testid="touch-app" onInteractOutside={keep}>
          <DrawerTitle className="sr-only">{t('shell.openApp')}</DrawerTitle>
          <AppPanel />
        </DrawerContent>
      </Drawer>
    </>
  )
}

/** Installed app (no browser gesture to protect): a swipe from the left edge opens the sessions, from the right
 *  edge the app menu. In a browser tab the edges keep the browser's back / forward gestures. */
function useEdgeOpen() {
  React.useEffect(() => {
    if (!isStandalone()) return
    const EDGE = 24
    let from: Panel = null
    let x0 = 0
    let y0 = 0
    const start = (e: TouchEvent) => {
      from = null
      if (e.touches.length !== 1 || useTouchNav.getState().panel || document.querySelector('[role="dialog"]:not([data-touch-layer])')) return
      const x = e.touches[0].clientX
      if (x <= EDGE) from = 'sessions'
      else if (x >= window.innerWidth - EDGE) from = 'app'
      x0 = x
      y0 = e.touches[0].clientY
    }
    const move = (e: TouchEvent) => {
      if (!from) return
      const dx = e.touches[0].clientX - x0
      const dy = e.touches[0].clientY - y0
      if (Math.abs(dy) > Math.abs(dx) && Math.abs(dy) > 10) {
        from = null
        return
      }
      if ((from === 'sessions' && dx > 40) || (from === 'app' && dx < -40)) {
        useTouchNav.getState().setPanel(from)
        if (navigator.vibrate) navigator.vibrate(8)
        from = null
      }
    }
    document.addEventListener('touchstart', start, { passive: true })
    document.addEventListener('touchmove', move, { passive: true })
    return () => {
      document.removeEventListener('touchstart', start)
      document.removeEventListener('touchmove', move)
    }
  }, [])
}

const tile =
  'relative flex h-[76px] min-w-0 flex-col items-center justify-center gap-1.5 rounded-xl border bg-card px-1 text-[13px] font-medium text-foreground outline-none transition-colors active:bg-accent focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-[22px]'
const row =
  'flex min-h-12 w-full items-center gap-3 rounded-lg px-3 text-left text-[15px] outline-none transition-colors active:bg-accent hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring [&>svg]:size-5 [&>svg]:shrink-0 [&>svg]:text-muted-foreground'

/** The Agents tile: new results + approvals waiting. */
function AgentsTileBadge() {
  const t = useT()
  const n = useAgentsAttention()
  return <CountBadge count={n} className="absolute top-2 right-2" title={t('nav.agentsUnread', { count: n })} />
}

/** Right drawer: everything the desktop sidebar holds. */
function AppPanel() {
  const t = useT()
  const nav = useNav()
  const { data: ext } = useExtensions()
  const pages = (ext || []).filter((e) => e.type === 'page' && e.enabled && !e.error)
  const feed = useFeed()
  const unreadFeed = feed.data?.unread ?? 0
  const install = useInstallMode()
  const close = () => useTouchNav.getState().setPanel(null)
  const linkCls = ({ isActive }: { isActive: boolean }) => cn(tile, isActive && 'border-primary/60 text-primary')
  // Settings is a row at the bottom, like the sidebar's account area; every other page is a tile.
  const tiles = nav.filter((n) => n.to !== '/settings')
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain" data-testid="touch-app-panel">
      <div className="flex items-center justify-between gap-2 px-4 pt-3 pb-1">
        <Logo />
      </div>
      <div className="px-3 pt-2">
        <button
          type="button"
          onClick={() => {
            close()
            openPalette()
          }}
          className="flex h-11 w-full items-center gap-2.5 rounded-xl bg-muted px-3 text-[15px] text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          data-tour="palette"
        >
          <Search className="size-[18px]" /> {t('shell.searchAll')}
        </button>
      </div>

      <h3 className="px-4 pt-4 pb-2 text-xs font-semibold text-muted-foreground">{t('shell.goTo')}</h3>
      <nav aria-label={t('shell.navigation')} className="grid grid-cols-3 gap-2 px-3">
        {tiles.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end} className={linkCls} data-tour={navTourId(n)} onClick={close}>
            <n.icon strokeWidth={1.9} />
            <span className="max-w-full truncate">{t(n.short ?? n.label)}</span>
            {n.to === '/agents' && <AgentsTileBadge />}
          </NavLink>
        ))}
        <NavLink to="/feed" className={linkCls} onClick={close}>
          <Bell strokeWidth={1.9} />
          <span className="max-w-full truncate">{t('feed.title')}</span>
          <CountBadge count={unreadFeed} className="absolute top-2 right-2" title={t('feed.unreadCount', { count: unreadFeed })} />
        </NavLink>
      </nav>

      {/* The extension pages apart from the app's pages, as in the sidebar. */}
      {pages.length > 0 && (
        <>
          <h3 className="px-4 pt-4 pb-2 text-xs font-semibold text-muted-foreground">{t('ext.hubTitle')}</h3>
          <div className="grid grid-cols-3 gap-2 px-3">
            <NavLink to="/x" end className={linkCls} onClick={close}>
              <Blocks strokeWidth={1.9} />
              <span className="max-w-full truncate">{t('ext.allPages')}</span>
            </NavLink>
            {pages
              .filter((x) => x.pinned)
              .sort((a, b) => (a.pin_order ?? 1e9) - (b.pin_order ?? 1e9))   // the order dragged in the sidebar
              .map((x) => (
                <NavLink key={x.id} to={`/x/${x.id}`} className={linkCls} onClick={close}>
                  <NamedIcon name={x.icon} strokeWidth={1.9} />
                  <span className="max-w-full truncate">{x.name}</span>
                </NavLink>
              ))}
          </div>
        </>
      )}

      <div className="grid gap-0.5 px-2 pt-3">
        {install && (
          <button
            type="button"
            className={row}
            onClick={() => {
              close()
              void installApp()
            }}
          >
            <Download /> {t('pwa.install')}
          </button>
        )}
        <button
          type="button"
          className={row}
          onClick={() => {
            close()
            useFeedbackDialog.getState().setOpen(true)
          }}
        >
          <MessageSquareText />
          <span className="grid flex-1">
            <span>{t('shell.feedback')}</span>
            <span className="text-[13px] text-muted-foreground">{t('shell.feedbackHint')}</span>
          </span>
        </button>
        <NavLink to="/settings" className={row} onClick={close} data-tour="nav-settings">
          <Settings /> <span className="flex-1">{t('nav.settings')}</span>
          <ChevronRight />
        </NavLink>
      </div>

      {/* The sidebar's status footer: health, CPU / RAM / disk, Claude plan, eye, theme, General settings. */}
      <div className="mx-3 mt-3 grid gap-1 rounded-xl border bg-card p-2" data-tour="health">
        <UpdateIndicator />
        <StatusFooter touch />
      </div>
      <div className="h-4 shrink-0" />
    </div>
  )
}
