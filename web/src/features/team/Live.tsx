// Team in the background of every page (Settings -> Features -> team_page on): the user's presence for their
// contacts while Harness is open and visible, and a new message of a chat that is not on screen: a system
// notification when Harness is in the background, else the message itself in a popup to read and answer (MessagePopup).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { teamPresence, useTeam } from '@/lib/queries'
import { useUI } from '@/stores/ui'
import { isCompact } from '@/stores/media'
import { playChime, showSystemNotification } from '@/features/notify/useDoneNotifier'
import { chatTitle, personOf } from './people'
import { useTeamUI } from './store'
import { dropMessagePopup, messagePopupChats, showMessagePopup } from './MessagePopup'

const PRESENCE_MS = 150_000 // the server sends it on at most every 2 min anyway

function usePresencePing() {
  React.useEffect(() => {
    const ping = () => document.visibilityState === 'visible' && void teamPresence()
    ping()
    const timer = window.setInterval(ping, PRESENCE_MS)
    document.addEventListener('visibilitychange', ping)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', ping)
    }
  }, [])
}

function useMessageNotifier() {
  const navigate = useNavigate()
  const enabled = useUI((s) => s.notifyTeam)
  const { data: team } = useTeam()
  const prev = React.useRef<Map<string, number> | null>(null)
  React.useEffect(() => {
    if (!team) return
    // A popup leaves with its unread messages (chat opened here or on another device, muted, deleted).
    for (const id of messagePopupChats()) {
      const c = team.chats.find((x) => x.id === id)
      if (!c || !c.unread || c.muted) dropMessagePopup(id)
    }
    const before = prev.current
    prev.current = new Map(team.chats.map((c) => [c.id, c.last?.at || 0]))
    if (!before) return
    const fresh = team.chats.filter(
      (c) => c.last && c.unread > 0 && !c.muted && c.last.author !== team.me && c.last.kind !== 'info' && c.last.at > (before.get(c.id) ?? Infinity),
    )
    if (!fresh.length) return
    const ui = useTeamUI.getState()
    // The chat's bubble comes up even with notifications off (it is the unread mark of the bubbles).
    const bubbles = useUI.getState().teamBubbles && !isCompact() && !location.pathname.startsWith('/team')
    if (bubbles) for (const c of fresh) ui.bump(c.id)
    if (!enabled) return
    const away = document.hidden || !document.hasFocus()
    const onScreen = (id: string) =>
      (location.pathname.startsWith('/team') && new URLSearchParams(location.search).get('chat') === id) || (bubbles && !ui.hidden && ui.docked.includes(id))
    let rang = false
    for (const c of fresh) {
      if (!away && onScreen(c.id)) continue
      const title = chatTitle(team, c)
      const who = c.kind === 'group' ? `${personOf(team, c.last!.author).name.split(' ')[0]} : ` : ''
      const body = who + (c.last!.kind === 'poll' ? `📊 ${c.last!.text}` : `${c.last!.files ? '📎 ' : ''}${c.last!.text}`).slice(0, 160)
      const open = () => (bubbles && !location.pathname.startsWith('/team') ? useTeamUI.getState().openChat(c.id) : navigate(`/team?chat=${encodeURIComponent(c.id)}`))
      rang = true
      if (away && showSystemNotification(title, body, open, `mx-team-${c.id}`)) continue
      showMessagePopup(c.id, { at: c.last!.at, text: body }, open)
    }
    if (rang && useUI.getState().notifySound) playChime()
  }, [team, enabled, navigate])
}

export function TeamLive() {
  usePresencePing()
  useMessageNotifier()
  return null
}
