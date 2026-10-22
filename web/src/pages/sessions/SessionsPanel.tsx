// Touch layout: the sessions drawer (left). The same tree as the desktop Sessions page, laid out for fingers; a
// session picked here opens full screen on /sessions.
import * as React from 'react'
import { useLocation, useNavigate } from 'react-router'
import type { Session } from '@/lib/types'
import { useTouchNav } from '@/components/shell/TouchNav'
import { SessionTree } from './Tree'
import { useSessionsUI } from './store'
import { useSessionSeeded } from '@/lib/queries'

export default function SessionsPanel() {
  const navigate = useNavigate()
  const location = useLocation()
  const cols = useSessionsUI((s) => s.cols)
  const focused = useSessionsUI((s) => s.focused)
  const focusedCol = cols.find((c) => c.key === focused) || null
  const focusedId = focusedCol?.kind === 'session' ? focusedCol.id : null
  const { data: session } = useSessionSeeded(focusedId)
  const activePath = focusedCol?.kind === 'new' ? focusedCol.path : (session?.path ?? null)
  const openIds = React.useMemo(() => new Set(focusedId ? [focusedId] : []), [focusedId])
  // Switching sessions replaces the history entry: Back leaves the app's sessions instead of walking through them.
  const go = (search: string) => {
    useTouchNav.getState().setPanel(null)
    navigate(`/sessions?${search}`, { replace: location.pathname === '/sessions' })
  }
  const onOpen = (s: Pick<Session, 'id' | 'path'>) => go(`path=${encodeURIComponent(s.path)}&session=${s.id}`)
  const onNew = (path: string) => go(`path=${encodeURIComponent(path)}&new=1`)
  return <SessionTree touch className="min-h-0 flex-1" onOpenSession={onOpen} onNewSession={onNew} activePath={activePath} openIds={openIds} focusedId={focusedId} />
}
