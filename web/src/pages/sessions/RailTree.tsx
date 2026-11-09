// Desktop sidebar, unfolded: its second column is the Sessions page's own tree (same filter, chips, folding, menus,
// shared store), loaded with this chunk on idle after the first page load (or at the first unfold) and kept. On the
// Sessions page a pick opens the session in the strip like the page's tree; anywhere else it goes to /sessions with
// that session open.
// The agents listed under their topic get their own preview card (features/agents/AgentPreview.tsx: the agent in its
// Office), delegated on their links like the session card is on its rows (components/shell/SessionsRail.tsx).
import * as React from 'react'
import { useNavigate } from 'react-router'
import type { Session } from '@/lib/types'
import { useSessionSeeded } from '@/lib/queries'
import { AgentHover } from '@/features/agents/AgentHover'
import { SessionTree } from './Tree'
import { focusComposer, useSessionsUI } from './store'

export default function RailTree({ onPick, className, frozen }: { onPick?: () => void; className?: string; frozen?: boolean }) {
  const navigate = useNavigate()
  // Folded (`frozen`), the column is kept but out of sight: the open / focused sessions it marks stay as they were
  // (a tab switch on the Sessions page must not render this whole tree again), and catch up when it is shown.
  const seen = React.useRef<{ cols: unknown; focused: unknown } | null>(null)
  const cols = useSessionsUI((s) => (frozen && seen.current ? (seen.current.cols as typeof s.cols) : s.cols))
  const focused = useSessionsUI((s) => (frozen && seen.current ? (seen.current.focused as typeof s.focused) : s.focused))
  seen.current = { cols, focused }
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
