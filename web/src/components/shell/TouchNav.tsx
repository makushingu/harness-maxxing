// Touch layout (phones, tablets - html[data-compact], stores/media.ts): no sidebar and no tab bar. Two buttons at the
// top of every screen open two drawers: on the left the list of the page open - what the second-level sidebar holds on
// a computer (PageList.tsx), the sessions on the Sessions page; no ☰ on a page without a list -, on the right the rest
// of the app (every entry of the desktop sidebar: pages and pinned extension pages, help, settings, update and the
// status line).
import * as React from 'react'
import { create } from 'zustand'
import { NavLink, useLocation } from 'react-router'
import { ChevronDown, ChevronRight, CircleHelp, LayoutGrid, Menu, Search } from 'lucide-react'
import { useAgentsAttention, useFeed, useHealth, useWorkspace } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useT, withGroups } from '@/i18n'
import { openPalette } from '@/commands/registry'
import { CountBadge, CountDot, NamedIcon, Sensitive, StatusDot } from '@/components/ui'
import { Drawer, DrawerContent, DrawerTitle } from '@/components/ui/drawer'
import { isStandalone, installApp, useInstallMode } from '@/pwa'
import { useTour } from '@/tour/store'
import { navTourId, useNavEntries } from './nav'
import { ListSlot, pageListId, usePageListId } from './PageList'
import { Logo } from './Logo'
import { healthTone, StatusPanel, useStatusLine } from './HealthIndicator'
import { useHelpActions } from './HelpMenu'
import { UpdateIndicator, usePendingUpdate } from './UpdateIndicator'

type Panel = 'sessions' | 'list' | 'app' | null
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

/** ☰ of a page with a list (PageList): opens it in the left drawer. Nothing on a page without one. */
export function TouchListButton({ className }: { className?: string }) {
  const t = useT()
  const list = usePageListId()
  if (!list) return null
  return (
    <button type="button" className={cn(topButton, '-ml-1', className)} aria-label={t('shell.openList')} onClick={() => useTouchNav.getState().setPanel('list')} data-testid="touch-list-button">
      <Menu />
    </button>
  )
}

let keepOnce = false
/** The next navigation leaves the page's list drawer open (a step inside the list, not a pick). */
export const keepPageListOpen = () => {
  keepOnce = true
}

/** Opens the page's list (touch: its drawer), from a button of the page (an empty state's "Open the list"). */
export const openPageList = () => useTouchNav.getState().setPanel('list')

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
  // Any navigation closes them (a page, a session picked in the list), but a step inside the page's list (a folder of
  // Files, a mailbox of E-mail: keepPageListOpen) keeps it.
  React.useEffect(() => {
    const keep = keepOnce && useTouchNav.getState().panel === 'list'
    keepOnce = false
    if (!keep) setPanel(null)
  }, [location.pathname, location.search, setPanel])
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
      <Drawer open={panel === 'list'} onOpenChange={(o) => setPanel(o ? 'list' : null)} modal={!tour}>
        <DrawerContent side="left" aria-describedby={undefined} data-testid="touch-list" onInteractOutside={keep}>
          <DrawerTitle className="sr-only">{t('shell.openList')}</DrawerTitle>
          {/* the page's list comes in here (PageList) */}
          <ListSlot className="flex min-h-0 flex-1 flex-col" />
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

/** Installed app (no browser gesture to protect): a swipe from the left edge opens the page's list (the sessions on
 *  the Sessions page), from the right
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
      if (x <= EDGE) from = pageListId() ? 'list' : location.pathname.startsWith('/sessions') ? 'sessions' : null
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
      if (((from === 'sessions' || from === 'list') && dx > 40) || (from === 'app' && dx < -40)) {
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
  const { entries, end } = useNavEntries()
  const feed = useFeed()
  const unreadFeed = feed.data?.unread ?? 0
  const install = useInstallMode()
  const close = () => useTouchNav.getState().setPanel(null)
  const linkCls = ({ isActive }: { isActive: boolean }) => cn(tile, isActive && 'border-primary/60 text-primary')
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden overflow-y-auto overscroll-contain" data-testid="touch-app-panel">
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
          <Search className="size-[18px] shrink-0" /> <span className="truncate">{t('shell.searchAll')}</span>
        </button>
      </div>

      {/* The pages and the pinned extension pages, in the sidebar's order. */}
      <h3 className="px-4 pt-4 pb-2 text-xs font-semibold text-muted-foreground">{t('shell.goTo')}</h3>
      <nav aria-label={t('shell.navigation')} className="grid grid-cols-3 gap-2 px-3">
        {entries.map((e) =>
          e.page ? (
            <NavLink key={e.to} to={e.to} end={e.page.end} className={linkCls} data-tour={navTourId(e.page)} onClick={close}>
              <e.page.icon strokeWidth={1.9} />
              <span className="max-w-full truncate">{t(e.page.short ?? e.page.label)}</span>
              {e.to === '/agents' && <AgentsTileBadge />}
              {e.to === '/' && <CountBadge count={unreadFeed} className="absolute top-2 right-2" title={t('feed.unreadCount', { count: unreadFeed })} />}
            </NavLink>
          ) : (
            <NavLink key={e.to} to={e.to} className={linkCls} data-ext={e.ext.id} onClick={close}>
              <NamedIcon name={e.ext.icon} strokeWidth={1.9} />
              <span className="max-w-full truncate">{e.ext.name}</span>
            </NavLink>
          ),
        )}
      </nav>

      <div className="grid gap-0.5 px-2 pt-3">
        <UpdateIndicator />
        <HelpRows close={close} />
        {end.map((n) => (
          <NavLink key={n.to} to={n.to} className={row} onClick={close} data-tour={navTourId(n)}>
            <n.icon /> <span className="min-w-0 flex-1 truncate">{t(n.label)}</span>
            <ChevronRight />
          </NavLink>
        ))}
      </div>

      <StatusCard
        onInstall={
          install
            ? () => {
                close()
                void installApp()
              }
            : undefined
        }
      />
      <div className="h-4 shrink-0" />
    </div>
  )
}

/** Help: a row that unfolds the Help entries (docs, shortcuts with a keyboard, the tour, Feedback). */
function HelpRows({ close }: { close: () => void }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const actions = useHelpActions()
  return (
    <>
      <button type="button" className={row} aria-expanded={open} onClick={() => setOpen(!open)} data-testid="touch-help">
        <CircleHelp /> <span className="min-w-0 flex-1 truncate">{t('shell.help')}</span>
        <ChevronDown className={cn('transition-transform', open && 'rotate-180')} />
      </button>
      {open &&
        actions.map((a) => (
          <button
            key={a.id}
            type="button"
            className={cn(row, 'min-h-11 pl-11 text-[14px]')}
            data-help={a.id}
            onClick={() => {
              close()
              a.run()
            }}
          >
            <a.icon /> <span className="min-w-0 flex-1 truncate">{a.label}</span>
          </button>
        ))}
    </>
  )
}

/** The sidebar's status line as a card: "All good · Claude 47 %", a tap unfolds the status panel in place. */
function StatusCard({ onInstall }: { onInstall?: () => void }) {
  const [open, setOpen] = React.useState(false)
  const s = useStatusLine(true)
  const alert = s.tone === 'error' || s.tone === 'warn'
  return (
    <div className="mx-3 mt-3 grid min-w-0 gap-1 rounded-xl border bg-card p-1.5" data-tour="health">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        data-testid="touch-status"
        className={cn(
          'flex min-h-11 w-full min-w-0 items-center gap-2.5 rounded-lg px-2.5 text-left text-[15px] outline-none transition-colors active:bg-accent focus-visible:ring-2 focus-visible:ring-ring',
          alert && (s.tone === 'error' ? 'text-destructive' : 'text-warning'),
        )}
      >
        <span className="flex size-4 shrink-0 items-center justify-center">
          <StatusDot tone={s.tone} pulse={s.tone === 'error'} />
        </span>
        <span className="min-w-0 flex-1 truncate">
          {s.health}
          {s.plan && <span className="text-muted-foreground"> · <Sensitive length={3}>{s.plan}</Sensitive></span>}
        </span>
        <ChevronDown className={cn('size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="min-w-0 px-1 pb-1" data-testid="touch-status-panel">
          <StatusPanel touch onInstall={onInstall} />
        </div>
      )}
    </div>
  )
}
