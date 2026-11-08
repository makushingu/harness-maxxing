// Desktop sidebar, unfolded: its second column is the Sessions page's own tree (same filter, chips, folding, menus,
// shared store), loaded with this chunk only when the bar unfolds. On the Sessions page a pick opens the session in
// the strip like the page's tree; anywhere else it goes to /sessions with that session open.
import * as React from 'react'
import { useLocation, useNavigate } from 'react-router'
import type { Session } from '@/lib/types'
import { useSessionSeeded } from '@/lib/queries'
import { SessionTree } from './Tree'
import { focusComposer, useSessionsUI } from './store'

export default function RailTree({ onPick, className }: { onPick?: () => void; className?: string }) {
  const navigate = useNavigate()
  const location = useLocation()
  const cols = useSessionsUI((s) => s.cols)
  const focused = useSessionsUI((s) => s.focused)
  const focusedCol = cols.find((c) => c.key === focused) || null
  const focusedId = focusedCol?.kind === 'session' ? focusedCol.id : null
  const { data: session } = useSessionSeeded(focusedId)
  const activePath = focusedCol?.kind === 'new' ? focusedCol.path : (session?.path ?? null)
  const openIds = React.useMemo(() => new Set(cols.flatMap((c) => (c.kind === 'session' ? [c.id] : []))), [cols])
  const onSessions = location.pathname === '/sessions'

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
    if (onSessions) reveal(key)
    else go(`/sessions?path=${encodeURIComponent(s.path)}&session=${encodeURIComponent(s.id)}`)
  }
  const onNew = (path: string) => {
    onPick?.()
    if (onSessions) reveal(useSessionsUI.getState().openNew(path))
    else go(`/sessions?path=${encodeURIComponent(path)}&new=1`)
  }
  return <SessionTree className={className} onOpenSession={onOpen} onNewSession={onNew} activePath={activePath} openIds={openIds} focusedId={focusedId} />
}
