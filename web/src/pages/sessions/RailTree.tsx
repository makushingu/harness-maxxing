// Desktop sidebar, unfolded: its second column is the Sessions page's own tree (same filter, chips, folding, menus,
// shared store), loaded with this chunk on idle after the first page load (or at the first unfold) and kept. On the
// Sessions page a pick opens the session in the strip like the page's tree; anywhere else it goes to /sessions with
// that session open.
// The agents listed under their topic get their own preview card (features/agents/AgentPreview.tsx: the agent in its
// Office), delegated on their links like the session card is on its rows (components/shell/SessionsRail.tsx).
import * as React from 'react'
import { useNavigate } from 'react-router'
import type { Agent, Session } from '@/lib/types'
import { agentRoute, useAgents, useSessionSeeded, useSettings } from '@/lib/queries'
import { withGroups } from '@/i18n'
import { cn } from '@/lib/utils'
import { SessionTree } from './Tree'
import { focusComposer, useSessionsUI } from './store'

export default function RailTree({ onPick, className }: { onPick?: () => void; className?: string }) {
  const navigate = useNavigate()
  const cols = useSessionsUI((s) => s.cols)
  const focused = useSessionsUI((s) => s.focused)
  const focusedCol = cols.find((c) => c.key === focused) || null
  const focusedId = focusedCol?.kind === 'session' ? focusedCol.id : null
  const { data: session } = useSessionSeeded(focusedId)
  const activePath = focusedCol?.kind === 'new' ? focusedCol.path : (session?.path ?? null)
  const openIds = React.useMemo(() => new Set(cols.flatMap((c) => (c.kind === 'session' ? [c.id] : []))), [cols])
  // Read when a session is picked, not subscribed: the column stays mounted (hidden) while the bar is folded, and
  // would otherwise render the whole tree again on every navigation.
  const onSessions = () => window.location.pathname === '/sessions'

  /** Same as the page's tree: the column opens (or is focused), scrolls into view, its composer takes the focus. */
  const reveal = (key: string) =>
    requestAnimationFrame(() => {
      document.querySelector(`[data-col="${key}"]`)?.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: 'smooth' })
      focusComposer(key)
    })
  // "Open all" of a chip calls onOpen once per session: one navigation, to the last one (the page opens the others
  // from the store, where they were just added).
  const pending = React.useRef<string | null>(null)
  const go = (href: string) => {
    const first = pending.current === null
    pending.current = href
    if (first)
      queueMicrotask(() => {
        const to = pending.current
        pending.current = null
        if (to) navigate(to)
      })
  }
  const onOpen = (s: Pick<Session, 'id' | 'path'>) => {
    onPick?.()
    const key = useSessionsUI.getState().openSession(s.id)
    if (onSessions()) reveal(key)
    else go(`/sessions?path=${encodeURIComponent(s.path)}&session=${encodeURIComponent(s.id)}`)
  }
  const onNew = (path: string) => {
    onPick?.()
    if (onSessions()) reveal(useSessionsUI.getState().openNew(path))
    else go(`/sessions?path=${encodeURIComponent(path)}&new=1`)
  }
  return (
    <AgentHover className={className}>
      <SessionTree className="h-full min-h-0 flex-1" onOpenSession={onOpen} onNewSession={onNew} activePath={activePath} openIds={openIds} focusedId={focusedId} />
    </AgentHover>
  )
}

// ---- the agent preview card ---------------------------------------------------------------------------------------

const loadAgentPreview = withGroups(['agents'], () => import('@/features/agents/AgentPreview'))
let agentPreview: ReturnType<typeof loadAgentPreview> | undefined
/** The card's chunk (the Office art) and the "agents" texts, fetched once: the first time the pointer enters a rail
 *  that lists agents. A failed download is tried again next time. */
const preloadAgentPreview = () =>
  (agentPreview ??= loadAgentPreview().catch((e: unknown) => {
    agentPreview = undefined
    throw e
  }))
const AgentPreviewCard = React.lazy(preloadAgentPreview)

/** Same rhythm as the session card (components/shell/SessionsRail.tsx): hover intent, switch, grace to cross. */
const PREVIEW_DELAY_MS = 250
const PREVIEW_SWITCH_MS = 70
const PREVIEW_CLOSE_MS = 140

const canHover = () => typeof window !== 'undefined' && window.matchMedia('(hover: hover) and (pointer: fine)').matches
/** An agent link of the tree (TopicAgents in Tree.tsx). */
const agentOf = (t: EventTarget | null) => (t instanceof Element ? t.closest<HTMLAnchorElement>('a[data-testid="topic-agent"]') : null)

/** The tree in a box that shows the card of the agent under the pointer (or focused from the keyboard). */
function AgentHover({ className, children }: { className?: string; children: React.ReactNode }) {
  const box = React.useRef<HTMLDivElement>(null)
  const { data: settings } = useSettings()
  const on = !!settings?.agents_page
  const { data } = useAgents(on)
  const [at, setAt] = React.useState<{ href: string; el: HTMLAnchorElement } | null>(null)
  const openTimer = React.useRef<number | undefined>(undefined)
  const closeTimer = React.useRef<number | undefined>(undefined)
  const stop = () => {
    window.clearTimeout(openTimer.current)
    window.clearTimeout(closeTimer.current)
    openTimer.current = undefined
  }
  React.useEffect(() => stop, [])
  // The link's native tooltip (its `title`) would show over the card: set aside while the card is up.
  React.useEffect(() => {
    const el = at?.el
    const title = el?.getAttribute('title')
    if (!el || title == null) return
    el.removeAttribute('title')
    return () => el.setAttribute('title', title)
  }, [at])
  const show = (el: HTMLAnchorElement, delay: number) => {
    stop()
    const next = { href: el.getAttribute('href') || '', el }
    if (!delay) setAt(next)
    // card already up: follow the pointer after a short beat (links only crossed on the way are not loaded)
    else openTimer.current = window.setTimeout(() => setAt(next), at ? PREVIEW_SWITCH_MS : delay)
  }
  const hide = (delay = PREVIEW_CLOSE_MS) => {
    stop()
    if (delay) closeTimer.current = window.setTimeout(() => setAt(null), delay)
    else setAt(null)
  }
  const inBox = (t: EventTarget | null) => t instanceof Node && !!box.current?.contains(t)
  const agent: Agent | undefined = at ? data?.agents.find((a) => agentRoute(a) === decodeURI(at.href)) : undefined
  return (
    <div
      ref={box}
      className={cn('flex min-h-0 flex-col', className)}
      onPointerEnter={(e) => {
        if (e.pointerType === 'mouse' && on && data?.agents.length && canHover()) preloadAgentPreview().catch(() => {})
      }}
      // Pointer events of the card (a portal, React child of this div) bubble here too: only links inside count.
      onPointerOver={(e) => {
        if (e.pointerType !== 'mouse' || !inBox(e.target)) return
        const link = agentOf(e.target)
        if (link && on && canHover()) {
          if (at?.el !== link) show(link, PREVIEW_DELAY_MS)
          else stop()
        } else if (at || openTimer.current) hide()
      }}
      onPointerLeave={(e) => e.pointerType !== 'touch' && hide()}
      onFocus={(e) => {
        const link = inBox(e.target) ? agentOf(e.target) : null
        if (link && on && link.matches(':focus-visible')) show(link, 0)
      }}
      onBlur={(e) => agentOf(e.target) && hide(0)}
      onClickCapture={() => at && hide(0)}
      onScrollCapture={() => at && hide(0)}
      onContextMenuCapture={() => at && hide(0)}
    >
      {children}
      {agent && at && box.current && (
        <React.Suspense fallback={null}>
          <AgentPreviewCard agent={agent} anchor={at.el} rail={box.current} onPointerEnter={stop} onPointerLeave={() => hide()} />
        </React.Suspense>
      )}
    </div>
  )
}
