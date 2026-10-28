import * as React from 'react'
import { NavLink } from 'react-router'
import { HandHeart, MessageSquareText, PanelLeftClose, PanelLeftOpen, PanelRight, Search } from 'lucide-react'
import { SIDEBAR_W, useUI } from '@/stores/ui'
import { useIsTablet } from '@/stores/media'
import { useTeam, useWorkspace } from '@/lib/queries'
import { useTeamUI } from '@/features/team/store'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { openPalette } from '@/commands/registry'
import { Button, CountBadge, CountDot, Kbd, MOD, Tooltip } from '@/components/ui'
import { navTourId, useNav } from './nav'
import { Logo } from './Logo'
import { HealthIndicator } from './HealthIndicator'
import { UsageIndicator } from './UsageIndicator'
import { UpdateIndicator } from './UpdateIndicator'
import { SidebarExtensions } from './SidebarExtensions'
import { useShowSessions } from '@/features/notify/showSessions'
import { usePrefetchLink } from '@/pages/pageData'
import { PresentationToggle, ThemeToggle, UserMenu } from './UserMenu'
import { useFeedbackDialog } from './feedback-store'
import { donationUrl, useDonationShown } from '@/features/donation/Donation'
import { useLang } from '@/i18n'

/** Unread/running counters for the Sessions nav item (from the workspace tree). */
function useSessionBadge() {
  const { data } = useWorkspace()
  let unread = 0
  let running = 0
  for (const p of data?.projects || [])
    for (const tp of p.topics) {
      unread += tp.unread
      running += tp.running
    }
  return { unread, running }
}

/** Team entry: its unread count, and (on hover) the button that opens the chats on the right of the page. */
function TeamNavExtra({ collapsed }: { collapsed: boolean }) {
  const t = useT()
  const { data } = useTeam()
  const open = useTeamUI((s) => s.open)
  const setOpen = useTeamUI((s) => s.setOpen)
  const unread = data?.chats.reduce((n, c) => n + (c.muted ? 0 : c.unread), 0) || 0
  if (collapsed) return unread ? <span className="absolute top-0.5 right-1 flex size-4 items-center justify-center"><CountDot tone="unread" /></span> : null
  return (
    <span className="flex items-center gap-1">
      <span
        role="button"
        tabIndex={-1}
        title={open ? t('nav.teamPanelClose') : t('nav.teamPanel')}
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          setOpen(!open)
        }}
        className={cn(
          'inline-flex size-6 items-center justify-center rounded text-muted-foreground transition hover:bg-background hover:text-foreground',
          open ? 'text-primary' : 'opacity-0 group-hover:opacity-100',
        )}
      >
        <PanelRight className="size-3.5" />
      </span>
      <CountBadge count={unread} />
    </span>
  )
}

/** Right edge: drag to resize the expanded sidebar (double-click: default width). */
function ResizeEdge({ side }: { side: React.RefObject<HTMLElement | null> }) {
  const t = useT()
  const setWidth = useUI((s) => s.setSidebarWidth)
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={t('shell.resize')}
      title={t('shell.resize')}
      onDoubleClick={() => setWidth(null)}
      onPointerDown={(e) => {
        const el = side.current
        if (!el || e.button !== 0) return
        e.preventDefault()
        const target = e.currentTarget
        target.setPointerCapture(e.pointerId)
        const startX = e.clientX
        const startW = el.getBoundingClientRect().width
        let w = startW
        const onMove = (ev: PointerEvent) => {
          w = Math.max(SIDEBAR_W.min, Math.min(SIDEBAR_W.max, startW + ev.clientX - startX))
          el.style.width = `${w}px`
        }
        const onUp = () => {
          target.removeEventListener('pointermove', onMove)
          target.removeEventListener('pointerup', onUp)
          target.removeEventListener('pointercancel', onUp)
          document.body.style.cursor = ''
          document.body.style.userSelect = ''
          setWidth(w)
        }
        document.body.style.cursor = 'col-resize'
        document.body.style.userSelect = 'none'
        target.addEventListener('pointermove', onMove)
        target.addEventListener('pointerup', onUp)
        target.addEventListener('pointercancel', onUp)
      }}
      className="absolute inset-y-0 -right-1 z-40 w-2 cursor-col-resize touch-none after:absolute after:inset-y-0 after:left-[3px] after:w-[3px] after:transition-colors hover:after:bg-primary/40 active:after:bg-primary/60"
    />
  )
}

export function Sidebar() {
  const prefetchLink = usePrefetchLink()
  const t = useT()
  const nav = useNav()
  const userCollapsed = useUI((s) => s.sidebarCollapsed)
  const toggle = useUI((s) => s.toggleSidebar)
  const tablet = useIsTablet()
  const collapsed = tablet || userCollapsed
  const badge = useSessionBadge()
  const showSessions = useShowSessions()
  const width = useUI((s) => s.sidebarWidth) ?? SIDEBAR_W.default
  const side = React.useRef<HTMLElement>(null)

  return (
    <aside
      ref={side}
      className={cn(
        'mx-boot-side relative z-30 hidden shrink-0 flex-col border-r border-sidebar-border bg-sidebar pt-[var(--safe-top)] pl-[var(--safe-left)] md:flex',
        collapsed && 'w-[60px]',
      )}
      style={collapsed ? undefined : { width }}
      aria-label={t('shell.navigation')}
    >
      {!collapsed && <ResizeEdge side={side} />}
      <div className={cn('flex h-14 items-center gap-2 px-3', collapsed && 'justify-center px-0')}>
        <NavLink to="/" className="min-w-0 flex-1 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="Harness Maxxing">
          <Logo collapsed={collapsed} className={cn(collapsed && 'justify-center')} />
        </NavLink>
      </div>

      <div className={cn('px-3 pb-2', collapsed && 'px-2.5')}>
        <Tooltip content={collapsed ? t('palette.open') : null} side="right">
          <button
            type="button"
            onClick={openPalette}
            data-tour="palette"
            className={cn(
              'flex h-9 w-full items-center gap-2 rounded-md border bg-background/60 px-2.5 text-sm text-muted-foreground shadow-xs transition hover:border-ring/40 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none dark:bg-input/20',
              collapsed && 'justify-center px-0',
            )}
            aria-label={t('palette.open')}
          >
            <Search className="size-4 shrink-0" />
            {!collapsed && (
              <>
                <span className="flex-1 text-left">{t('palette.search')}</span>
                <Kbd>{MOD} K</Kbd>
              </>
            )}
          </button>
        </Tooltip>
      </div>

      <nav data-tour="nav" className={cn('grid gap-0.5 px-3 py-2', collapsed && 'px-2.5')}>
        {nav.map((item, idx) => {
          const label = t(item.label)
          // Expanded: the counters stay mounted so they can animate out when they reach 0.
          const showBadge = item.to === '/sessions' && (!collapsed || badge.unread > 0 || badge.running > 0)
          return (
            <Tooltip key={item.to} content={collapsed ? label : null} side="right">
              <NavLink
                to={item.to}
                {...prefetchLink(item.to)}
                end={item.end}
                data-tour={navTourId(item)}
                style={{ '--i': idx } as React.CSSProperties}
                className={({ isActive }) =>
                  cn(
                    'mx-boot-item group relative flex h-9 items-center gap-3 rounded-md px-2.5 text-sm font-medium text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
                    isActive && 'bg-accent text-foreground',
                    collapsed && 'justify-center px-0',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && <span aria-hidden className="absolute top-2 bottom-2 -left-3 w-[3px] rounded-r-full bg-primary" />}
                    <item.icon className={cn('size-[18px] shrink-0', isActive && 'text-primary')} strokeWidth={isActive ? 2.2 : 1.9} />
                    {!collapsed && <span className="flex-1 truncate">{label}</span>}
                    {item.to === '/team' && <TeamNavExtra collapsed={collapsed} />}
                    {showBadge &&
                      (collapsed ? (
                        badge.unread ? (
                          <span onClick={showSessions('unread')} title={t('sessions.showUnread', { count: badge.unread })} className="absolute top-0.5 right-1 flex size-4 cursor-pointer items-center justify-center">
                            <CountDot tone="unread" />
                          </span>
                        ) : (
                          <span onClick={showSessions('running')} title={t('sessions.showRunning', { count: badge.running })} className="absolute top-0.5 right-1 flex size-4 cursor-pointer items-center justify-center">
                            <CountDot tone="running" />
                          </span>
                        )
                      ) : (
                        <span className="flex items-center gap-1">
                          <span onClick={showSessions('running')} className="cursor-pointer rounded-full transition-transform empty:hidden hover:scale-110">
                              <CountBadge count={badge.running} tone="running" title={t('sessions.showRunning', { count: badge.running })} />
                            </span>
                          <span onClick={showSessions('unread')} className="cursor-pointer rounded-full transition-transform empty:hidden hover:scale-110">
                              <CountBadge count={badge.unread} title={t('sessions.showUnread', { count: badge.unread })} />
                            </span>
                        </span>
                      ))}
                  </>
                )}
              </NavLink>
            </Tooltip>
          )
        })}
      </nav>

      <SidebarExtensions collapsed={collapsed} />

      <div className="flex-1" />

      <div className={cn('grid gap-1 border-t border-sidebar-border p-3 pb-[calc(0.75rem+var(--safe-bottom))]', collapsed && 'px-2.5')}>
        <UpdateIndicator collapsed={collapsed} />
        <HealthIndicator collapsed={collapsed} />
        <UsageIndicator collapsed={collapsed} />
        <FeedbackButton collapsed={collapsed} />
        <div className={cn('flex items-center gap-1', collapsed ? 'flex-col' : 'justify-between')}>
          <div className={cn('flex items-center gap-1', collapsed && 'flex-col')}>
            <PresentationToggle />
            <ThemeToggle collapsed={collapsed} />
            <UserMenu collapsed={collapsed} />
            <DonateLink />
          </div>
          {/* Fold / unfold: always at the bottom, in the same place in both states. */}
          {!tablet && (
            <Tooltip content={<>{collapsed ? t('shell.expand') : t('shell.collapse')} <Kbd className="border-background/20 bg-background/15 text-background">{MOD} \</Kbd></>} side="right">
              <Button variant="ghost" size="icon-sm" className="size-8 text-muted-foreground" onClick={toggle} aria-label={collapsed ? t('shell.expand') : t('shell.collapse')}>
                {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
              </Button>
            </Tooltip>
          )}
        </div>
      </div>
    </aside>
  )
}

/** Donate (features/donation): a small icon next to the eye, the theme and the account, in the accent colour; the
 *  donation page of the website in a new tab; hidden with `donation_hidden`. */
function DonateLink() {
  const t = useT()
  const lang = useLang()
  if (!useDonationShown()) return null
  return (
    <Tooltip content={<>{t('donation.donate')} · {t('settings.support.desc')}</>} side="right">
      <Button asChild variant="ghost" size="icon-sm" className="size-8 text-primary hover:bg-primary/10 hover:text-primary">
        <a href={donationUrl(lang)} target="_blank" rel="noopener" aria-label={t('donation.donate')} data-testid="sidebar-donate">
          <HandHeart />
        </a>
      </Button>
    </Tooltip>
  )
}

/** Feedback to the authors (bug, idea): opens the Feedback dialog (FeedbackDialog.tsx). */
function FeedbackButton({ collapsed }: { collapsed: boolean }) {
  const t = useT()
  const open = useFeedbackDialog((s) => s.setOpen)
  return (
    <Tooltip content={t('shell.feedbackHint')} side="right">
      <button
        type="button"
        onClick={() => open(true)}
        aria-label={collapsed ? t('shell.feedback') : undefined}
        className={cn(
          'flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
          collapsed && 'justify-center px-0',
        )}
      >
        <MessageSquareText className="size-4 shrink-0" />
        {!collapsed && <span className="truncate">{t('shell.feedback')}</span>}
      </button>
    </Tooltip>
  )
}
