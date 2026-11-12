// Touch layout (phones, tablets - html[data-compact], stores/media.ts): no sidebar and no tab bar. The ☰ at the top left
// of every screen opens one drawer on the left, in two levels, the same two bars as on a computer: the menu (the
// desktop sidebar itself, Sidebar.tsx `drawer`) and the list of a page (what its second-level sidebar holds,
// PageList.tsx; the sessions on the Sessions page) with ‹ before its title (back to the menu). A tap in the menu on a page with a list
// opens that page and slides to its list; any other page closes the drawer. The ☰ opens the list of the page open
// when it has one, else the menu. The search: the field atop the menu, the magnifier facing a list's title.
import * as React from 'react'
import { create } from 'zustand'
import { useLocation, useNavigationType } from 'react-router'
import { Download, Menu } from 'lucide-react'
import { useHealth, useWorkspace } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useT, withGroups } from '@/i18n'
import { openPalette } from '@/commands/registry'
import { CountBadge, CountDot } from '@/components/ui'
import { Drawer, DrawerContent, DrawerTitle } from '@/components/ui/drawer'
import { isStandalone, installApp, useInstallMode } from '@/pwa'
import { useTour } from '@/tour/store'
import { ListSlot, pageListId } from './PageList'
import { healthTone } from './HealthIndicator'
import { usePendingUpdate } from './UpdateIndicator'
import { Sidebar } from './Sidebar'

/** The drawer's level: 'app' the menu, 'list' the page's list, 'sessions' the sessions (Sessions page); null: closed. */
type Panel = 'sessions' | 'list' | 'app' | null
export const useTouchNav = create<{ panel: Panel; setPanel: (p: Panel) => void }>((set) => ({ panel: null, setPanel: (panel) => set({ panel }) }))

const topButton =
  'relative flex size-11 shrink-0 items-center justify-center rounded-xl text-foreground outline-none transition-colors hover:bg-accent active:bg-accent focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-[22px]'

const onSessions = (path: string) => path === '/sessions' || path.startsWith('/sessions/')
/** Pages whose list opens in the drawer (their PageList). */
const LISTS = ['/agents', '/team', '/infra', '/mail', '/files', '/tasks', '/feed', '/git']
const hasList = (path: string) => LISTS.some((p) => path === p || path.startsWith(p + '/'))

/** The level the ☰ opens: the list of the page open when it has one, else the menu. */
const levelHere = (): Panel => (onSessions(location.pathname) ? 'sessions' : pageListId() ? 'list' : 'app')
export const openTouchMenu = () => useTouchNav.getState().setPanel(levelHere())

/** ☰ - the drawer. The counter: sessions with an unread answer (a dot when one is running); else a dot when an update
 *  waits or the server needs attention. */
function MenuButton({ className }: { className?: string }) {
  const t = useT()
  const { data } = useWorkspace()
  const pending = usePendingUpdate()
  const { data: h } = useHealth()
  const tone = healthTone(h)
  let unread = 0
  let running = 0
  for (const p of data?.projects || [])
    for (const tp of p.topics) {
      unread += tp.unread
      running += tp.running
    }
  const alert = pending || tone === 'error' || tone === 'warn'
  return (
    <button type="button" className={cn(topButton, '-ml-1', className)} aria-label={t('shell.openApp')} onClick={openTouchMenu} data-tour="touch-sessions" data-testid="touch-menu-button">
      <Menu />
      {unread > 0 ? (
        <CountBadge count={unread} className="absolute top-0.5 right-0 ring-2 ring-background" title={t('sessions.showUnread', { count: unread })} />
      ) : running > 0 ? (
        <CountDot tone="running" className="absolute top-1.5 right-1.5" />
      ) : alert ? (
        <span aria-hidden className={cn('absolute top-2 right-2 size-2 rounded-full ring-2 ring-background', pending ? 'bg-primary' : tone === 'error' ? 'bg-destructive' : 'bg-warning')} />
      ) : null}
    </button>
  )
}
/** ☰ of the Sessions screens. */
export const TouchSessionsButton = MenuButton
/** ☰ of every other page (Page.tsx). */
export const TouchListButton = MenuButton

let keepOnce = false
/** The next navigation leaves the page's list open (a step inside the list, not a pick). */
export const keepPageListOpen = () => {
  keepOnce = true
}

/** Opens the page's list (touch: its level of the drawer), from a button of the page (an empty state's "Open the list"). */
export const openPageList = () => useTouchNav.getState().setPanel('list')

/** Closes the drawer and opens the search (the palette). */
export const searchNow = () => {
  useTouchNav.getState().setPanel(null)
  openPalette()
}

const SessionsPanel = React.lazy(withGroups(['files'], () => import('@/pages/sessions/SessionsPanel')))

/** A tap on a link of the menu opens a page: set before the navigation, read by the drawer once the URL changed. */
let fromMenu = false
/** The page just opened from the menu (and when): the redirect it may make at once (Sessions -> the last session) keeps
 *  the drawer where it settled. */
let settled = { path: '', at: 0 }

/** The drawer and its edge gesture. Mounted by AppShell in the touch layout. */
export function TouchDrawers() {
  const t = useT()
  const panel = useTouchNav((s) => s.panel)
  const setPanel = useTouchNav((s) => s.setPanel)
  const location = useLocation()
  const navType = useNavigationType()
  const install = useInstallMode()
  // During the guided tour its cards sit above the drawer: no focus trap, a tap on a card does not close it.
  const tour = useTour((s) => s.active)
  const keep = (e: Event) => tour && e.preventDefault()
  // After a page picked in the menu: its list when it has one, else closed. Any other navigation closes the drawer (a
  // session picked in the list), but a step inside the page's list (a folder of Files, a mailbox: keepPageListOpen)
  // keeps it.
  const settle = React.useCallback(
    (path: string) => {
      settled = { path, at: Date.now() }
      setPanel(onSessions(path) ? 'sessions' : hasList(path) ? 'list' : null)
    },
    [setPanel],
  )
  React.useEffect(() => {
    if (fromMenu) {
      fromMenu = false
      settle(location.pathname)
      return
    }
    if (navType === 'REPLACE' && location.pathname === settled.path && Date.now() - settled.at < 1500) return
    const keepIt = keepOnce && useTouchNav.getState().panel === 'list'
    keepOnce = false
    if (!keepIt) setPanel(null)
  }, [location.pathname, location.search, navType, setPanel, settle])
  useEdgeOpen()
  // the menu's links: a page with a list slides to it, the page already open too (no navigation then)
  const onMenuClick = (e: React.MouseEvent) => {
    const el = e.target as Element
    if (el.closest('[data-tour="palette"]')) return setPanel(null) // the search opens above
    const a = el.closest('a[href]') as HTMLAnchorElement | null
    if (!a || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || a.target === '_blank') return
    const url = new URL(a.href, window.location.href)
    if (url.origin !== window.location.origin) return
    if (url.pathname + url.search === window.location.pathname + window.location.search) settle(url.pathname)
    else fromMenu = true
  }
  const open = panel !== null
  // a level slides in only when the other one leads to it (a page picked, ‹ Menu), not when the drawer opens on it
  const was = React.useRef<Panel>(null)
  const back = panel === 'app' && (was.current === 'list' || was.current === 'sessions')
  const forth = panel !== 'app' && was.current === 'app'
  React.useEffect(() => {
    was.current = panel
  }, [panel])
  return (
    <Drawer open={open} onOpenChange={(o) => setPanel(o ? levelHere() : null)} modal={!tour}>
      <DrawerContent side="left" aria-describedby={undefined} data-testid="touch-drawer" data-level={panel || undefined} onInteractOutside={keep}>
        <DrawerTitle className="sr-only">{t('shell.navigation')}</DrawerTitle>
        {panel === 'app' ? (
          <div key="menu" className={cn(back && 'mx-level-back', 'flex min-h-0 flex-1 flex-col')} data-testid="touch-app" onClickCapture={onMenuClick}>
            <Sidebar drawer />
            {install && (
              <button
                type="button"
                onClick={() => {
                  setPanel(null)
                  void installApp()
                }}
                className="flex h-11 shrink-0 items-center gap-2.5 border-t border-sidebar-border px-5 text-sm text-muted-foreground outline-none active:bg-accent"
              >
                <Download className="size-[18px]" /> {t('pwa.install')}
              </button>
            )}
          </div>
        ) : (
          <div key="list" className={cn(forth && 'mx-level-in', 'flex min-h-0 flex-1 flex-col')} data-testid={panel === 'sessions' ? 'touch-sessions' : 'touch-list'}>
            {panel === 'sessions' ? (
              <React.Suspense fallback={null}>
                <SessionsPanel />
              </React.Suspense>
            ) : (
              // the page's list comes in here (PageList)
              <ListSlot className="flex min-h-0 flex-1 flex-col" />
            )}
          </div>
        )}
      </DrawerContent>
    </Drawer>
  )
}

/** Installed app (no browser gesture to protect): a swipe from the left edge opens the drawer (as the ☰). In a browser
 *  tab the edges keep the browser's back / forward gestures. */
function useEdgeOpen() {
  React.useEffect(() => {
    if (!isStandalone()) return
    const EDGE = 24
    let armed = false
    let x0 = 0
    let y0 = 0
    const start = (e: TouchEvent) => {
      armed = false
      if (e.touches.length !== 1 || useTouchNav.getState().panel || document.querySelector('[role="dialog"]:not([data-touch-layer])')) return
      const x = e.touches[0].clientX
      armed = x <= EDGE
      x0 = x
      y0 = e.touches[0].clientY
    }
    const move = (e: TouchEvent) => {
      if (!armed) return
      const dx = e.touches[0].clientX - x0
      const dy = e.touches[0].clientY - y0
      if (Math.abs(dy) > Math.abs(dx) && Math.abs(dy) > 10) {
        armed = false
        return
      }
      if (dx > 40) {
        openTouchMenu()
        if (navigator.vibrate) navigator.vibrate(8)
        armed = false
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
