// The agent preview card on hover (features/agents/AgentPreview.tsx: the agent in its Office), delegated on the agent
// links of a sidebar column: the sessions tree (TopicAgents in Tree.tsx) and the Agents column (AgentsRail.tsx).
import * as React from 'react'
import type { Agent } from '@/lib/types'
import { agentRoute, useAgents, useSettings } from '@/lib/queries'
import { withGroups } from '@/i18n'
import { cn } from '@/lib/utils'

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
const agentOf = (t: EventTarget | null) => (t instanceof Element ? t.closest<HTMLAnchorElement>('a[data-testid="topic-agent"], a[data-rail-agent]') : null)

/** The tree in a box that shows the card of the agent under the pointer (or focused from the keyboard). */
export function AgentHover({ className, children }: { className?: string; children: React.ReactNode }) {
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
