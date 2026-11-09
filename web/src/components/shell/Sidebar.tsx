import * as React from 'react'
import { NavLink, useLocation } from 'react-router'
import { Bell, PanelLeftClose, PanelRight, Pin, Search } from 'lucide-react'
import { SIDEBAR_W, useUI } from '@/stores/ui'
import { useIsTablet } from '@/stores/media'
import { useAgentsAttention, useFeed, useOrderPins, useSaveSettings, useTeam, useWorkspace } from '@/lib/queries'
import { useTeamUI } from '@/features/team/store'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { openPalette } from '@/commands/registry'
import { Button, CountBadge, CountDot, KeepTooltipShape, Kbd, MOD, NamedIcon, Popover, PopoverContent, PopoverTrigger, Tooltip } from '@/components/ui'
import { FeedPanel } from '@/features/feed/FeedItems'
import { navRow, navTourId, useNavEntries, type NavEntry, type NavItem } from './nav'
import { Logo } from './Logo'
import { StatusBlock } from './HealthIndicator'
import { preloadRailTree, SessionsRail } from './SessionsRail'
import { afterBoot } from '@/lib/bootLoader'
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
  if (collapsed) return unread ? <span className={FOLDED_DOT}><CountDot tone="unread" /></span> : null
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
  if (collapsed) return n ? <span className={FOLDED_DOT}><CountDot tone="unread" /></span> : null
  return (
    <span className="empty:hidden">
      <CountBadge count={n} title={t('nav.agentsUnread', { count: n })} />
    </span>
  )
}

/** The notifications bell, at the top of the bar: folded, an icon with a dot while something is unread; unfolded, the
 *  same icon right of the search field, with its count. Opens the dashboard's notifications panel beside the bar; the bar stays open
 *  while it is (its trigger has aria-expanded), and it closes when a link of it changes the page. */
function NotificationsBell({ collapsed }: { collapsed: boolean }) {
  const t = useT()
  const { data } = useFeed()
  const unread = data?.unread ?? 0
  const [open, setOpen] = React.useState(false)
  const { pathname } = useLocation()
  React.useEffect(() => setOpen(false), [pathname])
  // the panel opens beside the whole bar (its right edge, past the sessions column when unfolded), not over it
  const trigger = React.useRef<HTMLButtonElement>(null)
  const [offset, setOffset] = React.useState(10)
  const onOpenChange = (next: boolean) => {
    const el = trigger.current
    const edge = el?.closest('[data-testid=sidebar]')?.getBoundingClientRect().right
    if (next && el && edge) setOffset(Math.max(10, Math.round(edge - el.getBoundingClientRect().right + 8)))
    setOpen(next)
  }
  const label = unread ? `${t('feed.title')} · ${t('feed.unreadCount', { count: unread })}` : t('feed.title')
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <Tooltip content={open ? null : label} side={collapsed ? 'right' : 'bottom'}>
        <PopoverTrigger
          ref={trigger}
          data-testid="sidebar-bell"
          aria-label={label}
          className={cn(
            navRow(collapsed),
            'data-[state=open]:bg-accent data-[state=open]:text-foreground',
            // folded: first icon of the bar; unfolded: right of the search field, fading in there with the field
            // (and out with it as the bar folds), then fading back in at its folded spot.
            collapsed ? 'mx-bell-in' : 'mx-side-reveal order-last w-10 shrink-0 justify-center px-0',
          )}
        >
          <Bell className="size-[18px] shrink-0" strokeWidth={1.7} />
          {unread > 0 &&
            (collapsed ? (
              <span className={FOLDED_DOT}>
                <CountDot tone="unread" />
              </span>
            ) : (
              <span className="mx-side-reveal absolute top-0 -right-1.5">
                <CountBadge count={unread} className="h-4 min-w-4 text-[10px]" />
              </span>
            ))}
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent
        side="right"
        align="start"
        sideOffset={offset}
        className="w-96 overflow-hidden p-0"
        data-testid="sidebar-feed"
        // focus the panel itself, not its first button (whose tooltip would pop up and eat the first Esc)
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          ;(e.currentTarget as HTMLElement | null)?.focus()
        }}
      >
        <FeedPanel className="max-h-[min(34rem,calc(100dvh-2rem))] rounded-none border-0 bg-transparent" />
      </PopoverContent>
    </Popover>
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

/** Folded bar: where a counter dot sits on a 44 px icon row (top-right corner of the icon). */
const FOLDED_DOT = 'absolute top-1 right-1 flex size-4 items-center justify-center'
/** The active page's marker on the bar's left edge (the folded rows sit 10 px from it, the unfolded ones 12 px). */
const activeMark = (collapsed: boolean) => cn('absolute top-2 bottom-2 w-[3px] rounded-r-full bg-primary', collapsed ? '-left-2.5 top-2.5 bottom-2.5' : '-left-3')

/** Width of the folded icon bar (the page always keeps this room when the bar is not pinned; same 64 px in globals.css `.mx-side`). */
const FOLDED_W = 64
/** Width of the second column (the sessions) shown beside the unfolded bar. */
const RAIL_W = 304
/** Fold animation (keep in sync with the CSS of `.mx-side` in globals.css: 300 ms to unfold, 220 ms to fold). */
const FOLD_MS = 220
/** Delay before folding back once the pointer (or the keyboard focus) left the bar. */
const FOLD_DELAY_MS = 250

/** closed = icon bar; open = unfolded over the page; closing = folding back (labels still there, clipped). */
export type UnfoldPhase = 'closed' | 'open' | 'closing'

const reducedMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

/** The folded bar unfolds over the page on hover or keyboard focus, and folds back 250 ms after the pointer / focus
 *  left (Esc folds at once). A menu opened from the bar (Help, status) keeps it open until it closes. */
function useUnfold(enabled: boolean, side: React.RefObject<HTMLElement | null>) {
  // React only knows open / closed: `closing` (labels still there, the edge moving back) is written on the bar's own
  // element, so folding costs one render (at the end) instead of two. React never writes `data-unfold` back while it
  // stays 'open' (it only patches what changed since its last render).
  const [phase, setPhase] = React.useState<'open' | 'closed'>('closed')
  const phaseRef = React.useRef(phase) // the committed phase (a sliced render may still be thrown away)
  React.useLayoutEffect(() => {
    phaseRef.current = phase
  }, [phase])
  const setClosing = (on: boolean) => {
    const el = side.current
    if (!el || el.dataset.unfold === 'pinned') return
    if (on) el.dataset.unfold = 'closing'
    else if (el.dataset.unfold === 'closing') el.dataset.unfold = 'open' // React's own value ('closed' is React's)
  }
  const timer = React.useRef<number | undefined>(undefined)
  const hover = React.useRef(false)
  const focus = React.useRef(false)
  // After Esc or un-pinning: stay folded until the pointer leaves and comes back, or the focus moves.
  const blocked = React.useRef(false)
  // Focus we move or Radix gives back (a menu closing, Esc) must not unfold the bar again.
  const ignoreFocusUntil = React.useRef(0)
  // Esc folded the bar from the keyboard: once folded, put the focus back on the bar if its element went away (pin).
  const refocus = React.useRef(false)
  // Last pointer position: after a menu closes with Esc, is the pointer still over the bar?
  const pointer = React.useRef<{ x: number; y: number } | null>(null)

  const clear = () => {
    window.clearTimeout(timer.current)
    timer.current = undefined
  }
  const open = () => {
    clear()
    if (!enabled || blocked.current) return
    setClosing(false) // back over the bar while it folds: it unfolds again from where it is
    setPhase('open')
  }
  const fold = (delay: number) => {
    clear()
    const tick = () => {
      if (hover.current || focus.current) return
      if (side.current?.querySelector('[aria-haspopup][aria-expanded="true"]')) {
        timer.current = window.setTimeout(tick, FOLD_DELAY_MS) // a menu of the bar is open: wait for it
        return
      }
      if (phaseRef.current !== 'open') return
      const done = () => {
        // The folded bar looks the same before this render (labels faded out, edge at 64 px): React may slice it
        // (no long task); the pointer coming back meanwhile wins (an urgent update).
        React.startTransition(() => setPhase('closed'))
      }
      if (reducedMotion()) return done()
      setClosing(true)
      timer.current = window.setTimeout(done, FOLD_MS)
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

  React.useEffect(() => {
    if (!enabled) return
    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== 'touch') pointer.current = { x: e.clientX, y: e.clientY }
    }
    // Esc closing a menu the bar opened (Help, status panel: rendered in a portal): Radix gives the focus back to
    // its button, which must not keep the bar open; fold unless the pointer is still over the bar.
    const onKey = (e: KeyboardEvent) => {
      const el = side.current
      if (e.key !== 'Escape' || !el || el.contains(e.target as Node) || !el.querySelector('[aria-haspopup][aria-expanded="true"]')) return
      const r = el.getBoundingClientRect()
      const p = pointer.current
      hover.current = !!p && p.x >= r.left && p.x <= r.right && p.y >= r.top && p.y <= r.bottom
      focus.current = false
      ignoreFocusUntil.current = performance.now() + 400
      if (!hover.current) fold(0) // waits for the menu to be closed, then folds
    }
    document.addEventListener('pointermove', onMove, { passive: true })
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('pointermove', onMove)
      document.removeEventListener('keydown', onKey, true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled])

  React.useEffect(() => {
    if (phase !== 'closed' || !refocus.current) return
    refocus.current = false
    const el = side.current
    const a = document.activeElement
    if (!el || (a && a !== document.body && el.contains(a))) return
    // the focused element only exists unfolded (search, pin, top logo): the folded logo at the bottom takes the focus
    ignoreFocusUntil.current = performance.now() + 400
    el.querySelector<HTMLElement>('[data-side-logo="folded"]')?.focus()
  }, [phase, side])

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
      if (!side.current?.contains(el) || !el.matches(':focus-visible') || performance.now() < ignoreFocusUntil.current) return
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
      // stays folded until the pointer leaves and comes back, if it is over the bar (else the next visit unfolds it)
      blocked.current = hover.current
      hover.current = false
      focus.current = false
      if (side.current?.contains(document.activeElement)) refocus.current = true
      fold(0)
    },
  }
  /** A session was picked in the second column: fold now, stay folded until the pointer comes back. */
  const dismiss = () => {
    if (!enabled) return
    blocked.current = hover.current // a pick from the keyboard, pointer elsewhere: the next visit unfolds it
    hover.current = false
    focus.current = false
    ;(document.activeElement as HTMLElement | null)?.blur?.()
    fold(0)
  }
  // stable for the sessions column (kept mounted: a new function would re-render its whole tree on every unfold)
  const dismissRef = React.useRef(dismiss)
  dismissRef.current = dismiss
  const stableDismiss = React.useCallback(() => dismissRef.current(), [])
  return { phase: enabled ? phase : 'closed', props, dismiss: stableDismiss } as const
}

/** The sessions column is mounted ahead of the first unfold (on idle, a desktop with a mouse) and then kept, so no
 *  unfold pays for its chunk, its data and its first render while the bar moves. */
function useKeptRail(enabled: boolean, unfolded: boolean) {
  const [kept, setKept] = React.useState(false)
  if (unfolded && !kept) setKept(true)
  React.useEffect(() => {
    if (!enabled || kept || typeof matchMedia !== 'function' || !matchMedia('(min-width: 768px) and (hover: hover)').matches) return
    const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (id: number) => void }
    // after the page's own first load (its requests and renders), then on idle, as a transition: React renders the
    // tree in small slices (no long task), and an unfold meanwhile takes over at once (the render-time set above)
    let idle: number | undefined
    let live = true
    const keep = () => live && React.startTransition(() => setKept(true))
    // its chunk first, so the column mounts with the tree (not a skeleton) and is laid out once before it is hidden
    const load = () => void preloadRailTree().then(keep, keep)
    let t: number | undefined
    // never while the boot loader plays: its chunk and render would compete with the logo's end
    const stop = afterBoot(() => {
      t = window.setTimeout(() => {
        idle = w.requestIdleCallback ? w.requestIdleCallback(load, { timeout: 1500 }) : window.setTimeout(load, 0)
      }, 500)
    })
    return () => {
      live = false
      stop()
      window.clearTimeout(t)
      if (idle !== undefined) (w.cancelIdleCallback ?? window.clearTimeout)(idle)
    }
  }, [enabled, kept])
  return kept
}

/** The sessions column's box. Mounted ahead (on idle), it stays rendered for a moment, clipped by the folded bar
 *  (out of sight), so its styles and layout are computed then and kept while it is skipped: even the first unfold
 *  only reveals it. */
function RailSlot({ shown, children }: { shown: boolean; children: React.ReactNode }) {
  const [warm, setWarm] = React.useState(true)
  React.useEffect(() => {
    let raf = 0
    const t = window.setTimeout(() => (raf = requestAnimationFrame(() => setWarm(false))), 600)
    return () => {
      window.clearTimeout(t)
      cancelAnimationFrame(raf)
    }
  }, [])
  return (
    <div
      data-testid="sessions-rail"
      data-shown={shown || undefined}
      data-warm={(warm && !shown) || undefined}
      className="mx-side-rail h-full min-h-0 shrink-0 border-l border-sidebar-border"
      style={{ width: RAIL_W }}
    >
      {children}
    </div>
  )
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
              {isActive && <span aria-hidden className={activeMark(collapsed)} />}
              <item.icon className={cn('size-[18px] shrink-0', isActive && 'text-primary')} strokeWidth={isActive ? 2 : 1.7} />
              {!collapsed && <span className="flex-1 truncate">{label}</span>}
              {item.to === '/team' && <TeamNavExtra collapsed={collapsed} />}
              {item.to === '/agents' && <AgentsNavExtra collapsed={collapsed} />}
              {showBadge &&
                (collapsed ? (
                  badge.unread ? (
                    <span onClick={showSessions('unread')} title={t('sessions.showUnread', { count: badge.unread })} className={cn(FOLDED_DOT, 'cursor-pointer')}>
                      <CountDot tone="unread" />
                    </span>
                  ) : (
                    <span onClick={showSessions('running')} title={t('sessions.showRunning', { count: badge.running })} className={cn(FOLDED_DOT, 'cursor-pointer')}>
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
            {isActive && <span aria-hidden className={activeMark(collapsed)} />}
            <NamedIcon name={e.ext.icon} className={cn('size-[18px] shrink-0', isActive && 'text-primary')} strokeWidth={isActive ? 2 : 1.7} />
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
  const railKept = useKeptRail(!pinned, unfolded)
  const pinLabel = pinned ? t('shell.collapse') : t('shell.pin')

  return (
    // The slot keeps the layout width (folded: 60 px, so the page never moves when the bar unfolds over it).
    <div
      ref={side}
      className={cn('mx-boot-side relative hidden shrink-0 md:block', unfolded ? 'z-40' : 'z-30')}
      // `--mx-side-open`: the unfolded width (bar + sessions column), read by globals.css (`.mx-side`)
      style={pinned ? { width } : ({ width: FOLDED_W, '--mx-side-open': `${width + RAIL_W}px` } as React.CSSProperties)}
    >
      <aside
        ref={bar}
        {...unfold.props}
        data-testid="sidebar"
        data-unfold={pinned ? 'pinned' : unfold.phase}
        // not `data-expanded`: sonner's toast CSS has a `[data-expanded=false]…>*` rule, so flipping that attribute
        // restyled the whole bar on every unfold / fold
        data-side-expanded={collapsed ? 'false' : 'true'}
        className={cn(
          // the edge and the shadow move in globals.css (`.mx-side[data-unfold]`): soft, a bit longer to open than to fold
          'mx-side absolute inset-y-0 left-0 flex border-r border-sidebar-border bg-sidebar pt-[var(--safe-top)] pl-[var(--safe-left)]',
          // `clip`, not `hidden`: not a scroll container, so a row of the kept sessions column scrolled into view
          // (Tree.tsx, the active topic) can never shift the folded bar sideways
          !pinned && 'overflow-clip',
        )}
        // not pinned: width and position by `data-unfold` (globals.css), so the fold can start without a render
        style={pinned ? { width: '100%' } : undefined}
        aria-label={t('shell.navigation')}
      >
       <KeepTooltipShape.Provider value>
        {/* The bar slides in from the left while this layer slides the other way: the content stays still and the
            moving edge reveals it, with transforms only (composited: no layout, paint or style per frame). */}
        <div className="mx-side-inner flex h-full min-h-0 w-full">
        {/* Laid out at its final width while the bar unfolds or folds: the edge of the bar reveals it, nothing wraps. */}
        <div className="mx-side-body flex h-full min-h-0 shrink-0 flex-col" style={{ width: pinned ? '100%' : collapsed ? FOLDED_W : width }}>
      {pinned && <ResizeEdge side={side} />}
      {/* First row, in every state: the logo (a link to the dashboard). Folded, the mark alone, centred; unfolded or
          pinned, the mark stays where it is, the name fades in beside it and the pin button sits on the right. Same
          height both ways, so nothing below moves. `data-side-logo` = where the focus goes back after Escape folds. */}
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
        {!collapsed && !tablet && (
          <Tooltip content={<>{pinLabel} <Kbd className="border-background/20 bg-background/15 text-background">{MOD} \</Kbd></>} side="right">
            <Button
              variant="ghost"
              size="icon-sm"
              data-testid="sidebar-pin"
              aria-pressed={pinned}
              className="mx-side-reveal size-8 shrink-0 text-muted-foreground"
              onClick={toggle}
              aria-label={pinLabel}
            >
              {pinned ? <PanelLeftClose strokeWidth={1.7} /> : <Pin strokeWidth={1.7} />}
            </Button>
          </Tooltip>
        )}
      </div>
      {/* Top row: folded, the notifications bell alone; unfolded, the search field (Ctrl K) with the bell on its right
          (the same element, moved by `order`, so its focus survives). The rows below sit at the same height in both
          states. */}
      <div data-boot-rv className={cn('flex items-center gap-1.5 px-3 pt-2', collapsed && 'px-2.5')}>
        <NotificationsBell collapsed={collapsed} />
        {!collapsed && (
          <button
            type="button"
            onClick={openPalette}
            data-tour="palette"
            className="mx-side-reveal flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border bg-background/60 px-2.5 text-sm text-muted-foreground shadow-xs transition hover:border-ring/40 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none dark:bg-input/20"
            aria-label={t('palette.open')}
          >
            <Search className="size-4 shrink-0" strokeWidth={1.7} />
            <span className="flex-1 truncate text-left">{t('palette.search')}</span>
            <Kbd>{MOD} K</Kbd>
          </button>
        )}
      </div>

      {/* The pages and the pinned extension pages (drag to reorder; one scroll when the window is short); Help and
          Settings stay at the bottom, then CPU / RAM / disk and the Claude quota. */}
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
        {/* folded: a 44 px target and a bigger icon, like the rows (UpdateIndicator keeps its own small look) */}
        <div className={cn('empty:hidden', '[&_svg]:[stroke-width:1.7]', collapsed && '[&>*]:h-11 [&_svg]:size-[18px] [&>*>span:first-child]:size-5')}>
          <UpdateIndicator collapsed={collapsed} />
        </div>
        <HelpMenu collapsed={collapsed} />
        {end.map((item) => navItem(item, entries.length))}
      </div>

      <StatusBlock collapsed={collapsed} />

        </div>
        {/* Unfolded over the page: a second column with the sessions (running, unread, recent), one click away. */}
        {/* Mounted once (on idle after load, or at the first unfold) and kept: folded, `content-visibility: hidden`
            (globals.css) skips it, keeps its layout and takes it out of the tab order and the accessibility tree
            (cheaper than `inert`, which restyles the whole tree each time), so every unfold only reveals it. */}
        {!pinned && (unfolded || railKept) && (
          <RailSlot shown={unfolded}>
            <SessionsRail onPick={unfold.dismiss} shown={unfolded} />
          </RailSlot>
        )}
        </div>
       </KeepTooltipShape.Provider>
      </aside>
      {/* The unfolded bar's shadow: its own layer behind the bar, sliding with it and fading (globals.css). */}
      {!pinned && <div aria-hidden className="mx-side-shadow" />}
    </div>
  )
}
