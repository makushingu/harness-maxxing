// The open sessions are the same on every device of the user: a session opened on the computer is a tab on the phone,
// and closing it anywhere closes it everywhere (server: sessions/opened.py, ids only). Each browser keeps its own
// layout - widths, stacks, the session in front, columns or tabs. A new session not sent yet stays where it is typed.
//
// Three-way: `base` is the list this browser and the server last agreed on (kept in localStorage). What the browser
// has and `base` has not, it opened: sent. What the server has and `base` has not, another device opened: shown.
// The same for what was closed. No base yet (first time): a computer adds its sessions to the shared ones (and starts
// the list when there is none); a phone takes the shared ones and keeps only the session on screen of its own.
// A phone shares only in tabs view: without it, it shows one session at a time and has no bar to close the others.
import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { qk } from '@/lib/queries/keys'
import { normalizeCols, useSessionsUI, type Col } from './store'

type Shared = { ids: string[] | null; rev: number }
const BASE_KEY = 'mx-open-sync'

const isSession = (c: Col): c is Extract<Col, { kind: 'session' }> => c.kind === 'session'
const localIds = () => useSessionsUI.getState().cols.filter(isSession).map((c) => c.id)

function readBase(): string[] | null {
  try {
    const v = JSON.parse(localStorage.getItem(BASE_KEY) || 'null')
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : null
  } catch {
    return null
  }
}
function writeBase(ids: string[] | null) {
  try {
    if (ids) localStorage.setItem(BASE_KEY, JSON.stringify(ids))
    else localStorage.removeItem(BASE_KEY)
  } catch {
    /* private mode */
  }
}

/** Phone: the tabs in the order of the shared list (a computer keeps its own: its columns are a layout). */
function reorder(ids: string[]) {
  useSessionsUI.setState((s) => {
    const rank = new Map(ids.map((x, i) => [x, i]))
    const known = s.cols.filter((c) => isSession(c) && rank.has(c.id)) as Extract<Col, { kind: 'session' }>[]
    const sorted = [...known].sort((a, b) => rank.get(a.id)! - rank.get(b.id)!)
    if (sorted.every((c, i) => c === known[i])) return s
    let i = 0
    return { cols: normalizeCols(s.cols.map((c) => (isSession(c) && rank.has(c.id) ? sorted[i++] : c))) }
  })
}

// One Sessions page per browser tab: its state lives here (an answer that comes after the page was left and shown
// again still meets the right base).
const sync = {
  mobile: false,
  /** the list agreed on last; null: not yet (first time, or a phone that just turned the tabs on) */
  base: null as string[] | null,
  /** the newest answer applied: an older one (a GET that crossed a POST) is dropped */
  rev: 0,
  /** a computer: its own order, sent when it changes (a column was moved) */
  order: '',
}

/** Browser -> server: what was opened, closed or (a computer) moved here since `base`. */
function flush() {
  const b = sync.base
  if (b === null) return
  const local = localIds()
  const open = local.filter((x) => !b.includes(x))
  const close = b.filter((x) => !local.includes(x))
  const mine = local.join(' ')
  const moved = !sync.mobile && sync.order !== mine && [...local].sort().join(' ') === sync.order.split(' ').sort().join(' ')
  sync.order = mine
  if (!open.length && !close.length && !moved) return
  api
    .post<Shared>('/api/sessions/open', { open, close, order: moved ? local : [] })
    .then(pull)
    .catch(() => {})                      // offline: sent again with the next change, or when the list comes back
}

/** Server -> browser: what the other devices opened and closed since `base`. */
function pull(s: Shared) {
  const st = useSessionsUI.getState()
  const local = localIds()
  if (s.ids === null) {
    // nothing shared yet: a computer starts the list with its own sessions
    if (!sync.mobile) api.post<Shared>('/api/sessions/open', { open: local }).then(pull).catch(() => {})
    return
  }
  if (s.rev < sync.rev) return
  sync.rev = s.rev
  const ids = s.ids
  const b = sync.base
  const shown = st.cols.find((c) => c.key === st.focused)
  const keep = shown && isSession(shown) ? shown.id : null
  const toOpen = ids.filter((x) => !local.includes(x) && !(b || []).includes(x))
  const toClose = b === null ? (sync.mobile ? local.filter((x) => !ids.includes(x) && x !== keep) : []) : b.filter((x) => !ids.includes(x) && local.includes(x))
  sync.base = ids
  writeBase(ids)
  for (const id of toClose) st.closeSession(id)
  for (const id of toOpen) st.openSession(id, { focus: false })
  if (sync.mobile) reorder(ids)
  const now = useSessionsUI.getState()
  if (!now.focused && now.cols[0]) now.focus(now.cols[0].key)
  flush()
}

export function useOpenSync(mobile: boolean) {
  const tabs = useSessionsUI((s) => s.tabs)
  const active = !mobile || tabs
  const { data } = useQuery({
    queryKey: qk.openSessions,
    queryFn: ({ signal }) => api.get<Shared>('/api/sessions/open', undefined, { signal }),
    enabled: active,
    refetchOnWindowFocus: 'always',
  })
  React.useEffect(() => {
    sync.mobile = mobile
    sync.rev = 0
    if (!active) {
      sync.base = null
      writeBase(null)
      return
    }
    sync.base = readBase()
    sync.order = localIds().join(' ')
    let timer: ReturnType<typeof setTimeout> | undefined
    const unsub = useSessionsUI.subscribe((s, prev) => {
      if (s.cols === prev.cols) return
      clearTimeout(timer)
      timer = setTimeout(flush, 150)
    })
    return () => {
      unsub()
      clearTimeout(timer)
    }
  }, [active, mobile])
  React.useEffect(() => {
    if (active && data) pull(data)
  }, [active, mobile, data])
}
