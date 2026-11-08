import * as React from 'react'
import { NavLink } from 'react-router'
import { PanelLeftClose, PanelRight, Pin, Search } from 'lucide-react'
import { SIDEBAR_W, useUI } from '@/stores/ui'
import { useIsTablet } from '@/stores/media'
import { useAgentsAttention, useOrderPins, useSaveSettings, useTeam, useWorkspace } from '@/lib/queries'
import { useTeamUI } from '@/features/team/store'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { openPalette } from '@/commands/registry'
import { Button, CountBadge, CountDot, KeepTooltipShape, Kbd, MOD, NamedIcon, Tooltip } from '@/components/ui'
import { navRow, navTourId, useNavEntries, type NavEntry, type NavItem } from './nav'
import { Logo } from './Logo'
import { StatusLine } from './HealthIndicator'
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

/** Agents entry: new results + approvals waiting, summed over the agents. */
function AgentsNavExtra({ collapsed }: { collapsed: boolean }) {
  const t = useT()
  const n = useAgentsAttention()
  if (collapsed) return n ? <span className="absolute top-0.5 right-1 flex size-4 items-center justify-center"><CountDot tone="unread" /></span> : null
  return (
    <span className="empty:hidden">
      <CountBadge count={n} title={t('nav.agentsUnread', { count: n })} />
    </span>
  )
}

/** Right edge: drag to resize the expanded sidebar (double-click: default width). */
function ResizeEdge({ side }: { side: React.RefObject<HTMLDivElement | null> }) {
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

/** Width of the folded icon bar (the page always keeps this room when the bar is not pinned). */
const FOLDED_W = 60
/** Unfold / fold animation (keep in sync with the `duration-200` of the aside and the CSS of `.mx-side`). */
const UNFOLD_MS = 200
/** Delay before folding back once the pointer (or the keyboard focus) left the bar. */
const FOLD_DELAY_MS = 250

/** closed = icon bar; open = unfolded over the page; closing = folding back (labels still there, clipped). */
export type UnfoldPhase = 'closed' | 'open' | 'closing'

const reducedMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

/** The folded bar unfolds over the page on hover or keyboard focus, and folds back 250 ms after the pointer / focus
 *  left (Esc folds at once). A menu opened from the bar (Help, status) keeps it open until it closes. */
function useUnfold(enabled: boolean, side: React.RefObject<HTMLElement | null>) {
  const [phase, setPhase] = React.useState<UnfoldPhase>('closed')
  const timer = React.useRef<number | undefined>(undefined)
  const hover = React.useRef(false)
  const focus = React.useRef(false)
  // After Esc or un-pinning: stay folded until the pointer leaves and comes back, or the focus moves.
  const blocked = React.useRef(false)

  const clear = () => {
    window.clearTimeout(timer.current)
    timer.current = undefined
  }
  const open = () => {
    clear()
    if (enabled && !blocked.current) setPhase('open')
  }
  const fold = (delay: number) => {
    clear()
    const tick = () => {
      if (hover.current || focus.current) return
      if (side.current?.querySelector('[aria-expanded="true"]')) {
        timer.current = window.setTimeout(tick, FOLD_DELAY_MS) // a menu of the bar is open: wait for it
        return
      }
      if (reducedMotion()) return setPhase('closed')
      setPhase((p) => (p === 'open' ? 'closing' : p))
      timer.current = window.setTimeout(() => setPhase((p) => (p === 'closing' ? 'closed' : p)), UNFOLD_MS)
    }
    if (delay) timer.current = window.setTimeout(tick, delay)
    else tick()
  }

  const was = React.useRef(enabled)
  React.useEffect(() => {
    if (was.current === enabled) return
    was.current = enabled
    clear()
    setPhase('closed')
    // Just un-pinned with the pointer on it: fold now (the user sees the click did something), unfold on next visit.
    if (enabled) blocked.current = true
  }, [enabled])
  React.useEffect(() => clear, [])

  const props = {
    onPointerEnter: (e: React.PointerEvent) => {
      if (e.pointerType === 'touch') return
      hover.current = true
      open()
    },
    onPointerLeave: (e: React.PointerEvent) => {
      if (e.pointerType === 'touch') return
      hover.current = false
      blocked.current = false
      if (enabled) fold(FOLD_DELAY_MS)
    },
    onFocus: (e: React.FocusEvent) => {
      // Keyboard focus only: a mouse click on a row must not keep the bar open once the pointer leaves.
      const el = e.target as HTMLElement
      if (!side.current?.contains(el) || !el.matches(':focus-visible')) return
      focus.current = true
      blocked.current = false
      open()
    },
    onBlur: (e: React.FocusEvent) => {
      const next = e.relatedTarget as Node | null
      if (next && side.current?.contains(next)) return
      focus.current = false
      if (enabled) fold(FOLD_DELAY_MS)
    },
    onKeyDown: (e: React.KeyboardEvent) => {
      // Only keys pressed in the bar itself (not in a menu it opened, rendered in a portal).
      if (e.key !== 'Escape' || !enabled || phase === 'closed' || !side.current?.contains(e.target as Node)) return
      e.preventDefault()
      blocked.current = true
      hover.current = false
      focus.current = false
      fold(0)
    },
  }
  return { phase: enabled ? phase : 'closed', props } as const
}

export function Sidebar() {
  const prefetchLink = usePrefetchLink()
  const t = useT()
  const { entries, end } = useNavEntries()
  const userCollapsed = useUI((s) => s.sidebarCollapsed)
  const toggle = useUI((s) => s.toggleSidebar)
  const tablet = useIsTablet()
  // Not pinned (the default): an icon bar that unfolds over the page. Pinned: the full sidebar takes its room.
  const pinned = !tablet && !userCollapsed
  const bar = React.useRef<HTMLElement>(null)
  const unfold = useUnfold(!pinned, bar)
  /** What the bar looks like right now: folded icons, or the labelled sidebar (pinned or unfolded). */
  const collapsed = !pinned && unfold.phase === 'closed'
  const badge = useSessionBadge()
  const showSessions = useShowSessions()
  const width = useUI((s) => s.sidebarWidth) ?? SIDEBAR_W.default
  const side = React.useRef<HTMLDivElement>(null)
  const saveSettings = useSaveSettings()
  const orderPins = useOrderPins()

  const navItem = (item: NavItem, idx: number, drag?: object) => {
    const label = t(item.label)
    // Expanded: the counters stay mounted so they can animate out when they reach 0.
    const showBadge = item.to === '/sessions' && (!collapsed || badge.unread > 0 || badge.running > 0)
    return (
      <Tooltip key={item.to} content={collapsed ? label : null} side="right">
        <NavLink
          to={item.to}
          {...prefetchLink(item.to)}
          {...drag}
          end={item.end}
          data-tour={navTourId(item)}
          style={{ '--i': idx } as React.CSSProperties}
          className={({ isActive }) => cn('mx-boot-item', navRow(collapsed, isActive))}
        >
          {({ isActive }) => (
            <>
              {isActive && <span aria-hidden className="absolute top-2 bottom-2 -left-3 w-[3px] rounded-r-full bg-primary" />}
              <item.icon className={cn('size-[18px] shrink-0', isActive && 'text-primary')} strokeWidth={isActive ? 2.2 : 1.9} />
              {!collapsed && <span className="flex-1 truncate">{label}</span>}
              {item.to === '/team' && <TeamNavExtra collapsed={collapsed} />}
              {item.to === '/agents' && <AgentsNavExtra collapsed={collapsed} />}
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
  }
  /** A pinned extension page: a row like the pages. */
  const extItem = (e: Extract<NavEntry, { ext: object }>, idx: number, drag: object) => (
    <Tooltip key={e.to} content={collapsed ? e.ext.name : null} side="right">
      <NavLink
        to={e.to}
        {...drag}
        data-ext={e.ext.id}
        style={{ '--i': idx } as React.CSSProperties}
        className={({ isActive }) => cn('mx-boot-item', navRow(collapsed, isActive))}
      >
        {({ isActive }) => (
          <>
            {isActive && <span aria-hidden className="absolute top-2 bottom-2 -left-3 w-[3px] rounded-r-full bg-primary" />}
            <NamedIcon name={e.ext.icon} className={cn('size-[18px] shrink-0', isActive && 'text-primary')} strokeWidth={isActive ? 2.2 : 1.9} />
            {!collapsed && <span className="flex-1 truncate">{e.ext.name}</span>}
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
  const block = (cls?: string) => cn('grid gap-0.5 px-3 py-2', collapsed && 'px-2.5', cls)

  const unfolded = !pinned && unfold.phase !== 'closed'
  const pinLabel = pinned ? t('shell.collapse') : t('shell.pin')

  return (
    // The slot keeps the layout width (folded: 60 px, so the page never moves when the bar unfolds over it).
    <div
      ref={side}
      className={cn('mx-boot-side relative hidden shrink-0 md:block', unfolded ? 'z-40' : 'z-30')}
      style={{ width: pinned ? width : FOLDED_W }}
    >
      <aside
        ref={bar}
        {...unfold.props}
        data-testid="sidebar"
        data-unfold={pinned ? 'pinned' : unfold.phase}
        data-expanded={collapsed ? 'false' : 'true'}
        className={cn(
          'mx-side absolute inset-y-0 left-0 flex flex-col border-r border-sidebar-border bg-sidebar pt-[var(--safe-top)] pl-[var(--safe-left)]',
          !pinned && 'overflow-hidden transition-[width,box-shadow] duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none',
          unfold.phase === 'open' && !pinned && 'shadow-2xl',
        )}
        style={{ width: pinned ? '100%' : unfold.phase === 'open' ? width : FOLDED_W }}
        aria-label={t('shell.navigation')}
      >
       <KeepTooltipShape.Provider value>
        {/* Laid out at its final width while the bar unfolds or folds: the edge of the bar reveals it, nothing wraps. */}
        <div className="mx-side-body flex h-full min-h-0 flex-col" style={{ width: pinned ? '100%' : collapsed ? FOLDED_W : width }}>
      {pinned && <ResizeEdge side={side} />}
      {/* Logo + pin button (shown once the bar is unfolded or pinned). */}
      <div className={cn('flex h-14 items-center gap-2 px-3', collapsed && 'justify-center px-0')}>
        <NavLink
          to="/"
          className="min-w-0 flex-1 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Harness Maxxing"
        >
          <Logo collapsed={collapsed} className={cn(collapsed && 'justify-center')} />
        </NavLink>
        {!tablet && !collapsed && (
          <Tooltip content={<>{pinLabel} <Kbd className="border-background/20 bg-background/15 text-background">{MOD} \</Kbd></>} side="right">
            <Button
              variant="ghost"
              size="icon-sm"
              data-testid="sidebar-pin"
              aria-pressed={pinned}
              className="size-8 shrink-0 text-muted-foreground"
              onClick={toggle}
              aria-label={pinLabel}
            >
              {pinned ? <PanelLeftClose /> : <Pin />}
            </Button>
          </Tooltip>
        )}
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
                <span className="flex-1 truncate text-left">{t('palette.search')}</span>
                <Kbd>{MOD} K</Kbd>
              </>
            )}
          </button>
        </Tooltip>
      </div>

      {/* The pages and the pinned extension pages (drag to reorder; one scroll when the window is short); Help and
          Settings stay at the bottom, then the status line. */}
      <div data-tour="nav" className="min-h-0 overflow-y-auto overscroll-contain [scrollbar-width:none]">
        <nav aria-label={t('shell.navigation')} className={block()}>
          {drag.order.map((to, idx) => {
            const e = entries.find((x) => x.to === to)
            if (!e) return null // switched off or unpinned in another tab during a drag
            return e.page ? navItem(e.page, idx, drag.props(to)) : extItem(e, idx, drag.props(to))
          })}
        </nav>
      </div>

      <div className="flex-1" />

      <div className={block('border-t border-sidebar-border')}>
        <UpdateIndicator collapsed={collapsed} />
        <HelpMenu collapsed={collapsed} />
        {end.map((item) => navItem(item, entries.length))}
      </div>

      <StatusLine collapsed={collapsed} />
        </div>
       </KeepTooltipShape.Provider>
      </aside>
    </div>
  )
}
