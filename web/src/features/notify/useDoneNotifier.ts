// "Claude finished" notifications (Settings -> Notifications, stored per browser in the UI store).
// Watches the live sessions list (kept fresh by the global bus) and fires when a session goes from
// running to idle/error:
// - tab hidden or window not focused → a system notification (click = open the session);
// - tab visible → a toast with "Open", unless that session is already open on screen.
// Cron sessions never notify (their reports go to Telegram).
import * as React from 'react'
import { appIconSrc } from '@/lib/accent'
import { useNavigate } from 'react-router'
import { useSessions } from '@/lib/queries'
import type { Session } from '@/lib/types'
import { useUI } from '@/stores/ui'
import { useT } from '@/i18n'
import { toast } from '@/components/ui'
import { useSessionsUI } from '@/pages/sessions/store'

export function notificationsSupported(): boolean {
  return typeof window !== 'undefined' && 'Notification' in window
}

/** Two soft notes (Web Audio, no file to download). */
export function playChime() {
  try {
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctx) return
    const ctx = new Ctx()
    const now = ctx.currentTime
    for (const [i, f] of [880, 1318.5].entries()) {
      const o = ctx.createOscillator()
      const g = ctx.createGain()
      o.type = 'sine'
      o.frequency.value = f
      const t0 = now + i * 0.13
      g.gain.setValueAtTime(0.0001, t0)
      g.gain.exponentialRampToValueAtTime(0.12, t0 + 0.02)
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.35)
      o.connect(g).connect(ctx.destination)
      o.start(t0)
      o.stop(t0 + 0.4)
    }
    setTimeout(() => void ctx.close().catch(() => {}), 1000)
  } catch {
    /* audio blocked: silent */
  }
}

export function showSystemNotification(title: string, body: string, onClick?: () => void, tag?: string) {
  if (!notificationsSupported() || Notification.permission !== 'granted') return false
  try {
    const icon = appIconSrc(useUI.getState().accent)
    const n = new Notification(title, { body, tag, icon, badge: icon })
    n.onclick = () => {
      window.focus()
      onClick?.()
      n.close()
    }
    return true
  } catch {
    return false // e.g. Android Chrome requires a service worker notification: the toast covers it
  }
}

export function useDoneNotifier() {
  const t = useT()
  const navigate = useNavigate()
  const enabled = useUI((s) => s.notifyDone)
  const { data } = useSessions(undefined, false, enabled)
  const prev = React.useRef<Map<string, Session['state']> | null>(null)

  React.useEffect(() => {
    if (!enabled) {
      prev.current = null // turned back on later: start from the current states, never from stale ones
      return
    }
    if (!data) return
    const before = prev.current
    prev.current = new Map(data.map((s) => [s.id, s.state]))
    if (!before) return
    const finished = data.filter((s) => before.get(s.id) === 'running' && s.state !== 'running' && s.source !== 'cron')
    if (!finished.length) return
    const { notifySound } = useUI.getState()
    const away = document.hidden || !document.hasFocus()
    const onScreen = (id: string) => location.pathname.startsWith('/sessions') && useSessionsUI.getState().cols.some((c) => c.kind === 'session' && c.id === id)
    let rang = false
    for (const s of finished) {
      const open = () => navigate(`/sessions?path=${encodeURIComponent(s.path)}&session=${s.id}`)
      const title = s.state === 'error' ? t('notify.failedTitle') : t('notify.doneTitle')
      const body = `${s.title}${s.last_text ? ` - ${s.last_text.slice(0, 120)}` : ''}`
      if (away) {
        if (!showSystemNotification(title, body, open, `mx-session-${s.id}`)) toast.action(title, s.title, { label: t('notify.open'), onClick: open })
        rang = true
      } else if (!onScreen(s.id)) {
        toast.action(title, s.title, { label: t('notify.open'), onClick: open })
        rang = true
      }
    }
    if (rang && notifySound) playChime()
  }, [data, enabled, navigate, t])
}
