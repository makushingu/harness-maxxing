import * as React from 'react'
import { NavLink, useLocation } from 'react-router'
import { Blocks, MessageCircle, PanelLeftClose, PanelLeftOpen, Search } from 'lucide-react'
import { SIDEBAR_W, useUI } from '@/stores/ui'
import { useIsTablet } from '@/stores/media'
import { useAgentsAttention, useFeed, useOrderPins, useSaveSettings, useTeam, useWorkspace } from '@/lib/queries'
import { useTeamUI } from '@/features/team/store'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { openPalette } from '@/commands/registry'
import { Button, CountBadge, CountDot, KeepTooltipShape, Kbd, MOD, NamedIcon, Tooltip } from '@/components/ui'
import { navRow, navTourId, useNavEntries, useUnpinnedPages, type NavEntry, type NavItem } from './nav'
import { entryPeek, SecondBar, useClosedList } from './PageList'
import { Logo } from './Logo'
import { ResizeEdge } from './ResizeEdge'
import { ActiveMark } from './ActiveMark'
import { StatusBlock } from './HealthIndicator'
import { HelpMenu } from './HelpMenu'
import { UpdateIndicator } from './UpdateIndicator'
import { useDragOrder } from './dragOrder'
import { useShowSessions } from '@/features/notify/showSessions'
import { usePrefetchLink } from '@/pages/pageData'

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

/** Team entry: its unread count, and (on hover) the button that opens the chat list in the Team bubble. */
function TeamNavExtra({ collapsed }: { collapsed: boolean }) {
  const t = useT()
  const { data } = useTeam()
  const open = useTeamUI((s) => s.list)
  const setOpen = useTeamUI((s) => s.setList)
  const onTeam = useLocation().pathname.startsWith('/team')
  const bubbles = useUI((s) => s.teamBubbles)
  const unread = data?.chats.reduce((n, c) => n + (c.muted ? 0 : c.unread), 0) || 0
  if (collapsed) return unread ? <span className={FOLDED_DOT}><CountDot tone="unread" /></span> : null
  return (
    <span className="flex items-center gap-1">
      {!onTeam && bubbles && <span
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
        <MessageCircle className="size-3.5" />
      </span>}
      <CountBadge count={unread} />
    </span>
  )
}

/** Agents entry: new results + approvals waiting, summed over the agents. */
function AgentsNavExtra({ collapsed }: { collapsed: boolean }) {
  const t = useT()
  const n = useAgentsAttention()
  if (collapsed) return n ? <span className={FOLDED_DOT}><CountDot tone="unread" /></span> : null
  return (
    <span className="empty:hidden">
      <CountBadge count={n} title={t('nav.agentsUnread', { count: n })} />
    </span>
  )
}

/** Home entry: the unread notifications (the dashboard holds their panel, its bell opens /feed). */
function HomeNavExtra({ collapsed }: { collapsed: boolean }) {
  const t = useT()
  const { data } = useFeed()
  const unread = data?.unread ?? 0
  if (collapsed) return unread ? <span className={FOLDED_DOT}><CountDot tone="unread" /></span> : null
  return (
    <span className="empty:hidden" data-testid="home-feed-count">
      <CountBadge count={unread} title={t('feed.unreadCount', { count: unread })} />
    </span>
  )
}

/** Folded bar: where a counter dot sits on a 44 px icon row (top-right corner of the icon). */
const FOLDED_DOT = 'absolute top-1 right-1 flex size-4 items-center justify-center'
/** The active page's marker on the bar's left edge (the folded rows sit 10 px from it, the unfolded ones 12 px). */
const activeMark = (collapsed: boolean) => cn('absolute top-2 bottom-2 w-[3px] rounded-r-full bg-primary', collapsed ? '-left-2.5 top-2.5 bottom-2.5' : '-left-3')

/** 'up' / 'down' / 'both' while rows of the scroller are out of sight on that side, '' when it all fits. */
function useScrollEdges(ref: React.RefObject<HTMLElement | null>): string {
  const [edges, setEdges] = React.useState('')
  React.useEffect(() => {
    const el = ref.current
    if (!el) return
    const check = () => {
      const up = el.scrollTop > 1
      const down = el.scrollTop + el.clientHeight < el.scrollHeight - 1
      setEdges(up && down ? 'both' : up ? 'up' : down ? 'down' : '')
    }
    check()
    el.addEventListener('scroll', check, { passive: true })
    const ro = new ResizeObserver(check)
    ro.observe(el)
    if (el.firstElementChild) ro.observe(el.firstElementChild)
    return () => {
      el.removeEventListener('scroll', check)
      ro.disconnect()
    }
  }, [ref])
  return edges
}

/** Width of the folded icon bar. */
const FOLDED_W = 64

/** Memoized: the shell re-renders on every URL change (a session switched in the Sessions page's tabs too), and the
 *  bar has nothing to redo then (its links follow the URL by themselves). */
export const Sidebar = React.memo(function Sidebar() {
  const prefetchLink = usePrefetchLink()
  const t = useT()
  const { entries, end } = useNavEntries()
  const unpinned = useUnpinnedPages()
  const userCollapsed = useUI((s) => s.sidebarCollapsed)
  const toggle = useUI((s) => s.toggleSidebar)
  const tablet = useIsTablet()
  // Folded (the default): an icon bar. Pinned: the labelled sidebar. Only the pin changes it.
  const pinned = !tablet && !userCollapsed
  const collapsed = !pinned
  const badge = useSessionBadge()
  const showSessions = useShowSessions()
  const width = useUI((s) => s.sidebarWidth) ?? SIDEBAR_W.default
  const setWidth = useUI((s) => s.setSidebarWidth)
  const barW = pinned ? width : FOLDED_W
  const slot = React.useRef<HTMLDivElement>(null)
  const saveSettings = useSaveSettings()
  const orderPins = useOrderPins()

  // the page open has a list and the second-level sidebar is closed: resting on its entry shows the list over the page
  const closedList = useClosedList()
  const navItem = (item: NavItem, idx: number, drag?: object) => {
    const label = t(item.label)
    const list = item.to.slice(1)
    const peek = closedList === list
    // Unfolded: the counters stay mounted so they can animate out when they reach 0.
    const showBadge = item.to === '/sessions' && (!collapsed || badge.unread > 0 || badge.running > 0)
    return (
      // folded: a tooltip, but not over the page's own list showing
      <Tooltip key={item.to} content={collapsed && !peek ? label : null} side="right">
        <NavLink
          to={item.to}
          {...prefetchLink(item.to)}
          {...drag}
          end={item.end}
          data-tour={navTourId(item)}
          {...(peek ? entryPeek : undefined)}
          data-list-entry={peek || undefined}
          aria-label={collapsed ? label : undefined}
          style={{ '--i': idx } as React.CSSProperties}
          className={({ isActive }) => cn('mx-boot-item', navRow(collapsed, isActive))}
        >
          {({ isActive }) => (
            <>
              {isActive && <ActiveMark className={activeMark(collapsed)} collapsed={collapsed} />}
              <item.icon className={cn('size-[18px] shrink-0', isActive && 'text-primary')} strokeWidth={isActive ? 2 : 1.7} />
              {!collapsed && <span className="flex-1 truncate">{label}</span>}
              {item.to === '/' && <HomeNavExtra collapsed={collapsed} />}
              {item.to === '/team' && <TeamNavExtra collapsed={collapsed} />}
              {item.to === '/agents' && <AgentsNavExtra collapsed={collapsed} />}
              {showBadge &&
                (collapsed ? (
                  badge.unread ? (
                    <span data-badge onClick={showSessions('unread')} title={t('sessions.showUnread', { count: badge.unread })} className={cn(FOLDED_DOT, 'cursor-pointer')}>
                      <CountDot tone="unread" />
                    </span>
                  ) : (
                    <span data-badge onClick={showSessions('running')} title={t('sessions.showRunning', { count: badge.running })} className={cn(FOLDED_DOT, 'cursor-pointer')}>
                      <CountDot tone="running" />
                    </span>
                  )
                ) : (
                  <span className="flex items-center gap-1">
                    <span data-badge onClick={showSessions('running')} className="cursor-pointer rounded-full transition-transform empty:hidden hover:scale-110">
                      <CountBadge count={badge.running} tone="running" title={t('sessions.showRunning', { count: badge.running })} />
                    </span>
                    <span data-badge onClick={showSessions('unread')} className="cursor-pointer rounded-full transition-transform empty:hidden hover:scale-110">
                      <CountBadge count={badge.unread} title={t('sessions.showUnread', { count: badge.unread })} />
                    </span>
                  </span>
                ))}
            </>
          )}
        </NavLink>
      </Tooltip>
    )
  }
  /** A pinned extension page: a row like the pages. */
  const extItem = (e: Extract<NavEntry, { ext: object }>, idx: number, drag: object) => (
    <Tooltip key={e.to} content={collapsed ? e.ext.name : null} side="right">
      <NavLink
        to={e.to}
        {...prefetchLink(e.to)}
        {...drag}
        data-ext={e.ext.id}
        aria-label={collapsed ? e.ext.name : undefined}
        style={{ '--i': idx } as React.CSSProperties}
        className={({ isActive }) => cn('mx-boot-item', navRow(collapsed, isActive))}
      >
        {({ isActive }) => (
          <>
            {isActive && <ActiveMark className={activeMark(collapsed)} collapsed={collapsed} />}
            <NamedIcon name={e.ext.icon} className={cn('size-[18px] shrink-0', isActive && 'text-primary')} strokeWidth={isActive ? 2 : 1.7} />
            {!collapsed && <span className="flex-1 truncate">{e.ext.name}</span>}
          </>
        )}
      </NavLink>
    </Tooltip>
  )
  /** The Extensions page, after the pages: only while an extension page is not pinned (a direct way to it). */
  const hubItem = (idx: number) => (
    <Tooltip key="/x" content={collapsed ? t('ext.hubTitle') : null} side="right">
      <NavLink
        to="/x"
        end
        {...prefetchLink('/x')}
        data-tour="nav-extensions"
        aria-label={collapsed ? t('ext.hubTitle') : undefined}
        style={{ '--i': idx } as React.CSSProperties}
        className={({ isActive }) => cn('mx-boot-item', navRow(collapsed, isActive))}
      >
        {({ isActive }) => (
          <>
            {isActive && <ActiveMark className={activeMark(collapsed)} collapsed={collapsed} />}
            <Blocks className={cn('size-[18px] shrink-0', isActive && 'text-primary')} strokeWidth={isActive ? 2 : 1.7} />
            {!collapsed && <span className="flex-1 truncate">{t('ext.hubTitle')}</span>}
          </>
        )}
      </NavLink>
    </Tooltip>
  )
  // Dragging saves the whole order (pages and pinned pages) in `sidebar_order`; the pin order follows, so the
  // other lists of pinned pages (Extensions) show them in the same order.
  const drag = useDragOrder(
    entries.map((e) => e.to),
    (order) => {
      saveSettings.mutate({ sidebar_order: order })
      const pins = order.filter((to) => to.startsWith('/x/')).map((to) => to.slice(3))
      const before = entries.flatMap((e) => (e.ext ? [e.ext.id] : []))
      if (pins.join('\n') !== before.join('\n')) orderPins.mutate(pins)
    },
    'nav',
  )
  // rows hidden above or below in a short window: the list fades on that edge, so it shows it scrolls
  const navScroll = React.useRef<HTMLDivElement>(null)
  const more = useScrollEdges(navScroll)
  const block = (cls?: string) => cn('grid gap-0.5 px-3 py-2', collapsed && 'px-2.5', cls)
  const pinLabel = pinned ? t('shell.collapse') : t('shell.pin')

  return (
    <div className="mx-boot-side relative z-30 flex shrink-0">
      <div ref={slot} className="relative flex shrink-0" style={{ width: barW }}>
        <aside
          data-testid="sidebar"
          data-unfold={pinned ? 'pinned' : 'folded'}
          data-side-expanded={collapsed ? 'false' : 'true'}
          className="mx-side relative flex min-h-0 w-full flex-col overflow-x-clip overflow-y-auto overscroll-contain [scrollbar-width:none] border-r border-sidebar-border bg-sidebar pt-[var(--safe-top)] pl-[var(--safe-left)]"
          aria-label={t('shell.navigation')}
        >
          <KeepTooltipShape.Provider value>
            {/* First row: the logo (a link to the dashboard), and the pin button when pinned or wide enough. */}
            <div className="flex shrink-0 items-center gap-1.5 px-3 pt-2">
              <NavLink
                to="/"
                data-side-logo="folded"
                className={cn(
                  'flex h-11 items-center rounded-md px-1.5 outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring',
                  collapsed ? 'w-10 flex-none' : 'min-w-0 flex-1',
                )}
                aria-label="Harness Maxxing"
              >
                <Logo collapsed={collapsed} boot />
              </NavLink>
              {!collapsed && (
                <Tooltip content={<>{pinLabel} <Kbd className="border-background/20 bg-background/15 text-background">{MOD} \</Kbd></>} side="right">
                  <Button variant="ghost" size="icon-sm" data-testid="sidebar-pin" aria-pressed={pinned} className="size-8 shrink-0 text-muted-foreground" onClick={toggle} aria-label={pinLabel}>
                    <PanelLeftClose strokeWidth={1.7} />
                  </Button>
                </Tooltip>
              )}
            </div>
            {/* Folded: a search icon (Ctrl K); pinned: the search field. The notifications count sits on Home. */}
            <div data-boot-rv className={cn('flex items-center gap-1.5 px-3 pt-2', collapsed && 'px-2.5')}>
              {collapsed && (
                <Tooltip content={<>{t('palette.search')} <Kbd className="border-background/20 bg-background/15 text-background">{MOD} K</Kbd></>} side="right">
                  <button type="button" onClick={openPalette} data-tour="palette" aria-label={t('palette.open')} className={navRow(true)}>
                    <Search className="size-[18px] shrink-0" strokeWidth={1.7} />
                  </button>
                </Tooltip>
              )}
              {!collapsed && (
                <button
                  type="button"
                  onClick={openPalette}
                  data-tour="palette"
                  className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border bg-background/60 px-2.5 text-sm text-muted-foreground shadow-xs transition hover:border-ring/40 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none dark:bg-input/20"
                  aria-label={t('palette.open')}
                >
                  <Search className="size-4 shrink-0" strokeWidth={1.7} />
                  <span className="flex-1 truncate text-left">{t('palette.search')}</span>
                  <Kbd>{MOD} K</Kbd>
                </button>
              )}
            </div>

            {/* The pages and the pinned extension pages (drag to reorder; one scroll when the window is short). */}
            <div ref={navScroll} data-tour="nav" data-more={more || undefined} className="mx-nav-scroll min-h-[76px] overflow-y-auto overscroll-contain [scrollbar-width:none]">
              <nav aria-label={t('shell.navigation')} className={block()}>
                {drag.order.map((to, idx) => {
                  const e = entries.find((x) => x.to === to)
                  if (!e) return null // switched off or unpinned in another tab during a drag
                  return e.page ? navItem(e.page, idx, drag.props(to)) : extItem(e, idx, drag.props(to))
                })}
                {unpinned > 0 && hubItem(entries.length)}
              </nav>
            </div>

            <div className="flex-1" />

            <div className={block('border-t border-sidebar-border')}>
              {/* folded: a 44 px target and a bigger icon, like the rows (UpdateIndicator keeps its own small look) */}
              <div className={cn('empty:hidden', '[&_svg]:[stroke-width:1.7]', collapsed && '[&>*]:h-11 [@media(max-height:820px)]:[&>*]:h-9 [&_svg]:size-[18px] [&>*>span:first-child]:size-5')}>
                <UpdateIndicator collapsed={collapsed} />
              </div>
              <HelpMenu collapsed={collapsed} />
              {end.map((item) => navItem(item, entries.length + 1))}
              {/* folded: the way to pin the bar (pinned, the button sits beside the logo) */}
              {collapsed && !tablet && (
                <Tooltip content={<>{pinLabel} <Kbd className="border-background/20 bg-background/15 text-background">{MOD} \</Kbd></>} side="right">
                  <button type="button" data-testid="sidebar-pin" aria-label={pinLabel} aria-pressed={false} onClick={toggle} className={navRow(true)}>
                    <PanelLeftOpen className="size-[18px] shrink-0" />
                  </button>
                </Tooltip>
              )}
            </div>

            <StatusBlock collapsed={collapsed} />
          </KeepTooltipShape.Provider>
        </aside>
        {pinned && <ResizeEdge side={slot} min={SIDEBAR_W.min} max={SIDEBAR_W.max} onWidth={setWidth} />}
      </div>
      {/* the second-level sidebar: the list of the page open (components/shell/PageList.tsx) */}
      <SecondBar left={barW} />
    </div>
  )
})
