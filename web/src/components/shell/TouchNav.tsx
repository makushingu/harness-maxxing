// Touch layout (phones, tablets - html[data-compact], stores/media.ts): no sidebar and no tab bar. Two buttons at the
// top of every screen open two drawers: the sessions on the left, the rest of the app on the right (every entry of the
// desktop sidebar: pages, extensions, notifications, update, server health, plan usage, look, settings, help).
import * as React from 'react'
import { create } from 'zustand'
import { NavLink, useLocation, useNavigate } from 'react-router'
import { BookOpen, Blocks, Bell, ChevronRight, Compass, Download, Eye, GraduationCap, Heart, Keyboard, LayoutGrid, LogOut, Menu, MessageSquareText, Search, Settings } from 'lucide-react'
import { useExtensions, useFeed, useHealth, useLogout, useWorkspace } from '@/lib/queries'
import { useUI, type Theme } from '@/stores/ui'
import { cn } from '@/lib/utils'
import { useLang, useT, withGroups } from '@/i18n'
import { openPalette } from '@/commands/registry'
import { CountBadge, CountDot, NamedIcon, Segmented, Switch } from '@/components/ui'
import { Drawer, DrawerContent, DrawerTitle } from '@/components/ui/drawer'
import { isStandalone, installApp, useInstallMode } from '@/pwa'
import { startTour, useTour, useTutorialHref } from '@/tour/store'
import { navTourId, useNav } from './nav'
import { Logo } from './Logo'
import { HealthSummary, healthTone } from './HealthIndicator'
import { UpdateIndicator, usePendingUpdate } from './UpdateIndicator'
import { UsageIndicator } from './UsageIndicator'
import { useShortcutsDialog } from './shortcuts-store'
import { useFeedbackDialog } from './feedback-store'
import { DONATE_TONE, donationUrl, useDonationShown } from '@/features/donation/Donation'

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

/** Right drawer: everything the desktop sidebar holds. */
function AppPanel() {
  const t = useT()
  const lang = useLang()
  const donate = useDonationShown()
  const navigate = useNavigate()
  const nav = useNav()
  const { data: ext } = useExtensions()
  const pages = (ext || []).filter((e) => e.type === 'page' && e.enabled && !e.error)
  const feed = useFeed()
  const unreadFeed = feed.data?.unread ?? 0
  const theme = useUI((s) => s.theme)
  const setTheme = useUI((s) => s.setTheme)
  const presentation = useUI((s) => s.presentation)
  const setPresentation = useUI((s) => s.setPresentation)
  const install = useInstallMode()
  const tutorial = useTutorialHref()
  const logout = useLogout()
  const openShortcuts = useShortcutsDialog((s) => s.setOpen)
  const keyboard = typeof window !== 'undefined' && window.matchMedia('(any-pointer: fine)').matches
  const [helpOpen, setHelpOpen] = React.useState(false)
  // the help list folds away instead of vanishing: kept 140 ms after it closes, playing animate-out
  const [helpShown, setHelpShown] = React.useState(helpOpen)
  React.useEffect(() => {
    if (helpOpen) return setHelpShown(true)
    const id = setTimeout(() => setHelpShown(false), 140)
    return () => clearTimeout(id)
  }, [helpOpen])
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
          </NavLink>
        ))}
        <NavLink to="/feed" className={linkCls} onClick={close}>
          <Bell strokeWidth={1.9} />
          <span className="max-w-full truncate">{t('feed.title')}</span>
          <CountBadge count={unreadFeed} className="absolute top-2 right-2" title={t('feed.unreadCount', { count: unreadFeed })} />
        </NavLink>
        {pages.length > 0 && (
          <NavLink to="/x" end className={linkCls} onClick={close}>
            <Blocks strokeWidth={1.9} />
            <span className="max-w-full truncate">{t('ext.hubTitle')}</span>
          </NavLink>
        )}
        {pages
          .filter((x) => x.pinned)
          .map((x) => (
            <NavLink key={x.id} to={`/x/${x.id}`} className={linkCls} onClick={close}>
              <NamedIcon name={x.icon} strokeWidth={1.9} />
              <span className="max-w-full truncate">{x.name}</span>
            </NavLink>
          ))}
      </nav>

      <div className="mx-3 mt-4 grid gap-1 rounded-xl border bg-card p-2" data-tour="health">
        <UpdateIndicator />
        <div className="px-1.5 py-1">
          <HealthSummary compact />
        </div>
        <UsageIndicator visible />
      </div>

      <div className="grid gap-0.5 px-2 pt-3">
        <div className="flex min-h-12 items-center justify-between gap-3 px-3">
          <span className="text-[15px]">{t('shell.theme')}</span>
          <Segmented<Theme>
            value={theme}
            onChange={setTheme}
            aria-label={t('shell.theme')}
            options={[
              { value: 'dark', label: t('theme.dark') },
              { value: 'light', label: t('theme.light') },
              { value: 'system', label: t('theme.auto') },
            ]}
          />
        </div>
        <label className="flex min-h-12 items-center justify-between gap-3 px-3">
          <span className="flex items-center gap-3 text-[15px]">
            <Eye className="size-5 text-muted-foreground" /> {t('presentation.label')}
          </span>
          <Switch checked={presentation} onCheckedChange={setPresentation} />
        </label>
        <NavLink to="/settings" className={row} onClick={close} data-tour="nav-settings">
          <Settings /> <span className="flex-1">{t('nav.settings')}</span>
          <ChevronRight />
        </NavLink>
        <button type="button" className={row} onClick={() => setHelpOpen(!helpOpen)} aria-expanded={helpOpen}>
          <BookOpen />
          <span className="grid flex-1">
            <span>{t('shell.help')}</span>
            <span className="text-[13px] text-muted-foreground">{t('shell.helpHint')}</span>
          </span>
          <ChevronRight className={cn('transition-transform', helpOpen && 'rotate-90')} />
        </button>
        {(helpOpen || helpShown) && (
          <div className={cn('grid gap-0.5 pl-6', helpOpen ? 'animate-in' : 'pointer-events-none animate-[mx-out_140ms_ease-in_forwards]')}>
            <button
              type="button"
              className={row}
              onClick={() => {
                close()
                startTour()
              }}
            >
              <Compass /> {t('tour.take')}
            </button>
            {tutorial && (
              <button type="button" className={row} onClick={() => navigate(tutorial)}>
                <GraduationCap /> {t('tour.tutorial')}
              </button>
            )}
            <button type="button" className={row} onClick={() => navigate('/docs')}>
              <BookOpen /> {t('nav.docs')}
            </button>
            {keyboard && (
              <button
                type="button"
                className={row}
                onClick={() => {
                  close()
                  openShortcuts(true)
                }}
              >
                <Keyboard /> {t('shortcuts.title')}
              </button>
            )}
          </div>
        )}
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
        {donate && (
          <a href={donationUrl(lang)} target="_blank" rel="noopener" className={cn(row, DONATE_TONE, 'font-semibold [&>svg]:fill-current [&>svg]:text-current')} onClick={close}>
            <Heart />
            <span className="grid flex-1">
              <span>{t('donation.donate')}</span>
              <span className="text-[13px] font-normal opacity-80">{t('settings.support.desc')}</span>
            </span>
          </a>
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
        <button type="button" className={cn(row, 'text-destructive [&>svg]:text-destructive')} onClick={() => logout.mutate()}>
          <LogOut /> {t('auth.signOut')}
        </button>
      </div>
      <div className="h-4 shrink-0" />
    </div>
  )
}
