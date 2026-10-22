// Click on a badge (sidebar running / finished counters, collapsed sidebar dot, mobile tab bar): the session tree
// shows only those sessions, unfolded (`/sessions?show=running|unread`, see Tree.tsx); the open columns stay.
// The badge sits inside the Sessions link: it takes the click instead of the link.
import * as React from 'react'
import { useNavigate } from 'react-router'
import type { SessionShow } from '@/pages/sessions/store'

export function useShowSessions() {
  const navigate = useNavigate()
  return React.useCallback(
    (show: SessionShow) => (e: React.SyntheticEvent) => {
      e.preventDefault()
      e.stopPropagation()
      navigate(`/sessions?show=${show}`)
    },
    [navigate],
  )
}
