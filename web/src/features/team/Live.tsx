// Team in the background of every page (Settings -> Features -> team_page on): the user's presence for their
// contacts while Harness is open and visible, and a notification for a new message in a chat that is not on screen.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { teamPresence, useTeam } from '@/lib/queries'
import { useUI } from '@/stores/ui'
import { useT } from '@/i18n'
import { toast } from '@/components/ui'
import { playChime, showSystemNotification } from '@/features/notify/useDoneNotifier'
import { chatTitle, personOf } from './people'
import { useTeamUI } from './store'

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
  const t = useT()
  const navigate = useNavigate()
  const enabled = useUI((s) => s.notifyTeam)
  const { data: team } = useTeam()
  const prev = React.useRef<Map<string, number> | null>(null)
  React.useEffect(() => {
    if (!team) return
    const before = prev.current
    prev.current = new Map(team.chats.map((c) => [c.id, c.last?.at || 0]))
    if (!before || !enabled) return
    const fresh = team.chats.filter(
      (c) => c.last && c.unread > 0 && !c.muted && c.last.author !== team.me && c.last.kind !== 'info' && c.last.at > (before.get(c.id) ?? Infinity),
    )
    if (!fresh.length) return
    const ui = useTeamUI.getState()
    const away = document.hidden || !document.hasFocus()
    const onScreen = (id: string) =>
      (location.pathname.startsWith('/team') && new URLSearchParams(location.search).get('chat') === id) || (ui.open && ui.chat === id && !location.pathname.startsWith('/team'))
    let rang = false
    for (const c of fresh) {
      if (!away && onScreen(c.id)) continue
      const title = chatTitle(team, c)
      const who = c.kind === 'group' ? `${personOf(team, c.last!.author).name.split(' ')[0]} : ` : ''
      const body = who + (c.last!.kind === 'poll' ? `📊 ${c.last!.text}` : `${c.last!.files ? '📎 ' : ''}${c.last!.text}`).slice(0, 160)
      const open = () => navigate(`/team?chat=${encodeURIComponent(c.id)}`)
      if (!away || !showSystemNotification(title, body, open, `mx-team-${c.id}`)) toast.action(title, body, { label: t('notify.open'), onClick: open })
      rang = true
    }
    if (rang && useUI.getState().notifySound) playChime()
  }, [team, enabled, navigate, t])
}

export function TeamLive() {
  usePresencePing()
  useMessageNotifier()
  return null
}
