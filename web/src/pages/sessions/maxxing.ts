// Maxxing mode (Sessions page, per browser): many sessions run at once and, as soon as one finishes, it comes to
// the front - alone on the strip, full width (full screen on a phone) - so the user types its next prompt at once.
// Never in the middle of a prompt: while the session in front waits for its answer, or while the user types in
// a composer, the next finished session waits in the queue; it comes to the front right after the prompt is sent.
// Sessions that stopped on an error queue too: the next prompt starts them again.
// Beta, off by default: shown only when Settings -> Features -> Maxxing mode (config `maxxing_mode`) is on.
import * as React from 'react'
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Session } from '@/lib/types'
import { prefetchTail, useSettings } from '@/lib/queries'
import { reducedMotion, EASE_OUT } from '@/lib/presence'
import { focusComposer, useSessionsUI, type Col } from './store'
import * as stats from './maxxingStats'

type Saved = { cols: Col[]; widths: Record<string, number> }

type MaxxingState = {
  on: boolean
  /** Finished sessions waiting for their turn in front, oldest first. */
  queue: string[]
  /** The session in front, waiting for the user's prompt. */
  current: string | null
  /** Brought back by "Back" (a prompt sent by mistake): it stays in front, even running, until the user sends to it
   *  again, it finishes, or the user moves on. */
  pinned: boolean
  /** The session shown in front last (it stays there after its prompt is sent, until the next one comes). */
  shown: string | null
  /** The sessions shown in front before, most recent last (for "Back"). */
  history: string[]
  /** The arrangement of the strip before Maxxing mode, put back when it ends. */
  saved: Saved | null
  setOn: (on: boolean) => void
  enqueue: (id: string) => void
  drop: (id: string) => void
  setCurrent: (id: string | null) => void
  /** The session in front is left as it is: the next one comes. */
  skip: () => void
  /** The session shown before comes back in front; the one in front goes back to the head of the queue. */
  back: () => void
}

/** After a prompt is sent, the next session comes this soon (the send settles on screen first). */
const CALM_MS = 40
/** The next session's thread is loaded in the background while the user types (a prefetched tail is used for
 *  15 s: refreshed every 12 s). */
const PREFETCH_EVERY_MS = 12_000

/** Shows a session in front (set by the Sessions page: a column on a computer, full screen on a phone). */
let showSession: ((id: string) => void) | null = null
const HISTORY = 20

export const useMaxxing = create<MaxxingState>()(
  persist(
    (set, get) => ({
      on: false,
      queue: [],
      current: null,
      pinned: false,
      shown: null,
      history: [],
      saved: null,
      setOn: (on) => {
        if (on === get().on) return
        if (on) {
          const ui = useSessionsUI.getState()
          set({ on, queue: [], current: null, pinned: false, shown: null, history: [], saved: { cols: ui.cols, widths: ui.widths } })
        } else {
          const saved = get().saved
          if (saved) useSessionsUI.getState().restoreLayout(saved)
          set({ on, queue: [], current: null, pinned: false, shown: null, history: [], saved: null })
        }
        stats.resetStats()
      },
      enqueue: (id) => set((s) => (s.queue.includes(id) || s.current === id ? s : { queue: [...s.queue, id] })),
      drop: (id) =>
        set((s) =>
          s.queue.includes(id) || s.current === id
            ? { queue: s.queue.filter((x) => x !== id), ...(s.current === id && { current: null, pinned: false }) }
            : s,
        ),
      setCurrent: (current) =>
        set((s) => ({
          current,
          pinned: false,
          queue: current ? s.queue.filter((x) => x !== current) : s.queue,
          shown: current ?? s.shown,
          // the session leaving the front is remembered for "Back"
          history: current && s.shown && s.shown !== current ? [...s.history.filter((x) => x !== s.shown && x !== current), s.shown].slice(-HISTORY) : s.history,
        })),
      skip: () => set({ current: null, pinned: false }),
      back: () => {
        const s = get()
        const prev = s.history[s.history.length - 1]
        if (!prev || !showSession) return
        // its column first: the queue watcher must find it open when the state changes
        showSession(prev)
        set({
          current: prev,
          pinned: true,
          shown: prev,
          history: s.history.slice(0, -1),
          queue: [...(s.current && s.current !== prev ? [s.current] : []), ...s.queue.filter((x) => x !== prev && x !== s.current)],
        })
      },
    }),
    { name: 'mx-maxxing', partialize: (s) => ({ on: s.on, saved: s.saved }) },
  ),
)

/** Settings -> Features -> Maxxing mode (beta, off by default): the switch, the meter, the driver and Alt+M exist only
 *  when it is on. */
export function useMaxxingEnabled() {
  const { data } = useSettings()
  return !!data?.maxxing_mode
}

/** A session that, once finished, comes to the front: not archived, not a scheduled job nobody asked to hear about. */
const counts = (s: Session) => !s.archived && (s.source !== 'cron' || s.notify)
const waiting = (s: Session) => s.state !== 'running' && counts(s)

/** Someone is typing a prompt: the focus is in a composer that holds text. */
function typing() {
  const el = document.activeElement
  return el instanceof HTMLTextAreaElement && !!el.value.trim() && !!el.closest('[data-col], [data-touch-layer]')
}

/** The session in front glows as it arrives. */
export function glow(el: Element | null | undefined) {
  if (!el || reducedMotion()) return
  el.animate(
    [
      { boxShadow: '0 0 0 0 color-mix(in oklab, var(--primary) 0%, transparent)', filter: 'brightness(1.08)' },
      { boxShadow: '0 0 0 3px color-mix(in oklab, var(--primary) 55%, transparent), 0 0 32px color-mix(in oklab, var(--primary) 35%, transparent)', offset: 0.35 },
      { boxShadow: '0 0 0 0 color-mix(in oklab, var(--primary) 0%, transparent)', filter: 'none' },
    ],
    { duration: 1100, easing: EASE_OUT },
  )
}

/** Watches the sessions and brings the finished ones to the front. Mounted once by the Sessions page. */
export function useMaxxingDriver(sessions: Session[] | undefined, show: (s: Session) => void) {
  const on = useMaxxing((s) => s.on)
  const prev = React.useRef<Map<string, { state: Session['state']; plan: boolean }> | null>(null)
  const list = React.useRef(sessions)
  list.current = sessions
  const showRef = React.useRef(show)
  showRef.current = show
  React.useEffect(() => {
    showSession = (id) => {
      const s = list.current?.find((x) => x.id === id)
      if (s) showRef.current(s)
    }
    return () => {
      showSession = null
    }
  }, [])
  // a prompt was just sent: the next session comes once its send has settled on screen
  const calmUntil = React.useRef(0)

  React.useEffect(() => {
    if (!on) prev.current = null
  }, [on])

  // Each change of the list: a turn that ended queues its session, a prompt sent takes it out.
  React.useEffect(() => {
    if (!on || !sessions) return
    const m = useMaxxing.getState()
    const before = prev.current
    const now = Date.now()
    // first list since Maxxing mode is on (or since the page loaded): the sessions already finished and not read yet
    // open the queue, oldest first
    if (!before)
      for (const s of sessions.filter((s) => waiting(s) && (s.unread || s.plan_ready || s.state === 'error')).sort((a, b) => a.updated - b.updated)) {
        m.enqueue(s.id)
        stats.onFinished(s.id, now)
      }
    const next = new Map<string, { state: Session['state']; plan: boolean }>()
    for (const s of sessions) {
      next.set(s.id, { state: s.state, plan: s.plan_ready })
      const p = before?.get(s.id)
      if (!p) continue
      if (p.state !== 'running' && s.state === 'running') {
        stats.onSent(s.id, now)
        if (m.current === s.id) calmUntil.current = now + CALM_MS
        m.drop(s.id)
      } else if (counts(s) && ((p.state === 'running' && s.state !== 'running') || (s.plan_ready && !p.plan))) {
        stats.onFinished(s.id, now)
        // brought back by "Back" and now finished: it simply waits in front
        if (m.current === s.id) useMaxxing.setState({ pinned: false })
        else m.enqueue(s.id)
      }
    }
    prev.current = next
    // gone, archived or running again: out of the queue
    const byId = new Map(sessions.map((s) => [s.id, s]))
    const { queue, current, pinned } = useMaxxing.getState()
    for (const id of [...queue, ...(current ? [current] : [])]) {
      const s = byId.get(id)
      if (!s || (!waiting(s) && !(pinned && id === current && !s.archived))) m.drop(id)
    }
  }, [on, sessions])

  // The session in front: the next one comes when nobody waits in front and nobody is typing.
  React.useEffect(() => {
    if (!on) return
    let busy = false
    const prefetched = new Map<string, number>()
    const tick = () => {
      const ss = list.current
      if (!ss || busy) return
      const m = useMaxxing.getState()
      const now = Date.now()
      stats.sample(ss.filter((s) => s.state === 'running' && counts(s)).length, m.queue.length + (m.current ? 1 : 0), now)
      // the session in front was closed by the user: it no longer waits there
      // (on a phone the touch layer is always there: the session on screen is the one in the URL)
      const ui = useSessionsUI.getState()
      const onScreen = document.querySelector('[data-touch-layer]')
        ? new URLSearchParams(location.search).get('session') === m.current
        : ui.cols.some((c) => c.kind === 'session' && c.id === m.current)
      if (m.current && !onScreen) m.setCurrent(null)
      // the next one's thread loads in the background, so it shows at once when its turn comes
      const head = m.queue[0]
      if (head && now - (prefetched.get(head) || 0) > PREFETCH_EVERY_MS) {
        prefetched.set(head, now)
        prefetchTail(head)
      }
      if (useMaxxing.getState().current || !m.queue.length || now < calmUntil.current || typing()) return
      const s = ss.find((x) => x.id === m.queue[0])
      if (!s) return m.drop(m.queue[0])
      // its column first: the check above must find it open (setCurrent notifies the subscription below at once)
      busy = true
      try {
        showRef.current(s)
        m.setCurrent(s.id)
      } finally {
        busy = false
      }
    }
    tick()
    const iv = window.setInterval(tick, 500)
    let soon = 0
    const unsub = useMaxxing.subscribe((s, p) => {
      if (s.queue === p.queue && s.current === p.current) return
      tick()
      // the session in front was just answered: the next one right after the short calm
      window.clearTimeout(soon)
      soon = window.setTimeout(tick, Math.max(0, calmUntil.current - Date.now()) + 10)
    })
    return () => {
      window.clearInterval(iv)
      window.clearTimeout(soon)
      unsub()
    }
  }, [on])
}

/** Mounts the driver (the Sessions page renders it only when Maxxing mode is enabled in Settings -> Features). */
export function MaxxingDriver({ sessions, show }: { sessions: Session[] | undefined; show: (s: Session) => void }) {
  useMaxxingDriver(sessions, show)
  return null
}

/** A prompt was just sent to session `id` (the column's send, before the server answers): if it is the session in
 *  front, the next one comes at once - one frame later, once its composer has emptied (its draft is saved empty). */
export function notifySent(id: string) {
  const m = useMaxxing.getState()
  if (!m.on || m.current !== id) return
  stats.onSent(id)
  cancelAnimationFrame(pendingDrops.get(id) ?? 0)
  pendingDrops.set(
    id,
    requestAnimationFrame(() => {
      pendingDrops.delete(id)
      if (useMaxxing.getState().current === id) useMaxxing.getState().drop(id)
    }),
  )
}

/** Drops planned by notifySent, not run yet (a send refused in the same frame cancels its own). */
const pendingDrops = new Map<string, number>()

/** The send was refused (the text is back in its draft): the session goes back to the head of the queue. */
export function notifySendFailed(id: string) {
  const drop = pendingDrops.get(id)
  if (drop !== undefined) {
    // refused before the next frame: the session never left the front, it simply stays there
    cancelAnimationFrame(drop)
    pendingDrops.delete(id)
  }
  const m = useMaxxing.getState()
  if (!m.on || m.current === id || m.queue.includes(id)) return
  useMaxxing.setState({ queue: [id, ...m.queue] })
}

/** Desktop: the session takes the whole strip - the same column, so nothing shrinks or splits: the new session
 *  slides in from the right where the previous one was - the strip comes back to its start and its composer takes
 *  the focus. */
export function promoteColumn(id: string, strip: HTMLElement | null) {
  const key = useSessionsUI.getState().solo(id)
  requestAnimationFrame(() => {
    strip?.scrollTo({ left: 0, behavior: 'auto' })
    // a prompt half typed somewhere else keeps the focus (the queue waits for it to be sent, but be safe)
    if (!typing()) focusComposer(key)
    enter(strip?.querySelector(`:scope > [data-col="${CSS.escape(key)}"]`))
  })
}

/** The session arriving in front: one move, from the right, fading in, then a short glow. */
export function enter(el: Element | null | undefined) {
  if (!el || reducedMotion()) return
  el.animate(
    [
      { opacity: 0, transform: 'translateX(56px) scale(0.985)' },
      { opacity: 1, transform: 'none' },
    ],
    { duration: 260, easing: EASE_OUT },
  ).onfinish = () => glow(el)
}
