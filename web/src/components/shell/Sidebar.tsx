import type * as React from 'react'
import { NavLink } from 'react-router'
import { PanelLeftClose, PanelLeftOpen, Search } from 'lucide-react'
import { useUI } from '@/stores/ui'
import { useIsTablet } from '@/stores/media'
import { useWorkspace } from '@/lib/queries'
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

  return (
    <aside
      className={cn(
        'mx-boot-side z-30 hidden shrink-0 flex-col border-r border-sidebar-border bg-sidebar pt-[var(--safe-top)] pl-[var(--safe-left)] md:flex',
        collapsed ? 'w-[60px]' : 'w-[232px]',
      )}
      aria-label={t('shell.navigation')}
    >
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
        <div className={cn('flex items-center gap-1', collapsed ? 'flex-col' : 'justify-between')}>
          <div className={cn('flex items-center gap-1', collapsed && 'flex-col')}>
            <PresentationToggle />
            <ThemeToggle collapsed={collapsed} />
            <UserMenu collapsed={collapsed} />
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
