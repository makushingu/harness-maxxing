// The open sessions are the same on every device of the user: a session opened on the computer is a tab on the phone,
// and closing it anywhere closes it everywhere (server: sessions/opened.py, ids only). Each browser keeps its own
// layout - widths, stacks. The mode (Tabs or Zones) and the session in front follow the last device they were chosen
// on: going from the computer to the phone (or back) shows the same view. A new session not sent yet stays where it is.
//
// Three-way: `base` is the list this browser and the server last agreed on (kept in localStorage). What the browser
// has and `base` has not, it opened: sent. What the server has and `base` has not, another device opened: shown.
// The same for what was closed. No base yet (first time): a computer adds its sessions to the shared ones (and starts
// the list when there is none); a phone takes the shared ones and keeps only the session on screen of its own.
// Every browser shares its sessions in both modes (a phone in Zones too: it follows the mode of the computer, and a
// session opened there must still reach the computer).
import * as React from 'react'
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { qk } from '@/lib/queries/keys'
import { normalizeCols, useSessionsUI, type Col } from './store'

type Shared = { ids: string[] | null; rev: number; tabs?: boolean; front?: string }
const BASE_KEY = 'mx-open-sync'

const isSession = (c: Col): c is Extract<Col, { kind: 'session' }> => c.kind === 'session'
const localIds = () => useSessionsUI.getState().cols.filter(isSession).map((c) => c.id)
/** The session in front here (null: none, or a new session not sent yet). */
function frontId(): string | null {
  const st = useSessionsUI.getState()
  const c = st.cols.find((x) => x.key === st.focused)
  return c && isSession(c) ? c.id : null
}

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
  /** the mode and the session in front the server had last (undefined: not yet); a change here is sent, one there shown */
  tabs: undefined as boolean | null | undefined,
  front: undefined as string | null | undefined,
  /** the session in front here after the last answer (undefined: not yet): only a change made here since is sent - a
   *  session in front on another device that is not open here does not send this one back (it would undo a link) */
  mine: undefined as string | null | undefined,
  /** the session in front when the page opened: a link that brought another one in front is not undone */
  start: null as string | null,
}

let cache: QueryClient | null = null
/** The answer to a change sent here: applied, and kept as the shared list (a Sessions page shown again starts from the
 *  cached one: an older one would bring back the session in front from before). */
function sent(s: Shared) {
  cache?.setQueryData<Shared>(qk.openSessions, (old) => (old && old.rev > s.rev ? old : s))
  pull(s)
}

/** Browser -> server: what was opened, closed or (a computer) moved here since `base`. */
function flush() {
  const body: { open?: string[]; close?: string[]; order?: string[]; tabs?: boolean; front?: string } = {}
  const b = sync.base
  if (b !== null) {
    const local = localIds()
    const open = local.filter((x) => !b.includes(x))
    const close = b.filter((x) => !local.includes(x))
    const mine = local.join(' ')
    const moved = !sync.mobile && sync.order !== mine && [...local].sort().join(' ') === sync.order.split(' ').sort().join(' ')
    sync.order = mine
    if (open.length) body.open = open
    if (close.length) body.close = close
    if (moved) body.order = local
  }
  const st = useSessionsUI.getState()
  if (sync.tabs !== undefined && st.tabs !== sync.tabs) body.tabs = st.tabs
  const f = frontId()
  if (sync.mine !== undefined && f && f !== sync.mine && f !== sync.front) body.front = f
  if (!Object.keys(body).length) return
  api
    .post<Shared>('/api/sessions/open', body)
    .then(sent)
    .catch(() => {})                      // offline: sent again with the next change, or when the list comes back
}

/** Server -> browser: what the other devices opened and closed since `base`. */
function pull(s: Shared) {
  const st = useSessionsUI.getState()
  const local = localIds()
  if (s.ids === null) {
    // nothing shared yet: a computer starts the list with its own sessions (and its view)
    if (!sync.mobile) api.post<Shared>('/api/sessions/open', { open: local, tabs: st.tabs, front: frontId() ?? undefined }).then(sent).catch(() => {})
    return
  }
  if (s.rev < sync.rev) return
  sync.rev = s.rev
  const front = frontId()          // before the sessions opened below (the first one opened comes in front by itself)
  // The mode chosen on another device, unless it was just changed here too (then this one is sent).
  const before = sync.tabs ?? st.tabs
  if (typeof s.tabs === 'boolean' && st.tabs === before && s.tabs !== st.tabs) st.setTabs(s.tabs)
  sync.tabs = typeof s.tabs === 'boolean' ? s.tabs : null   // none shared yet: ours is sent
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
  view(s, front)
  const now = useSessionsUI.getState()
  if (!now.focused && now.cols[0]) now.focus(now.cols[0].key)
  flush()
}

/** The session in front on another device comes in front here, unless another one was just brought in front here. */
function view(s: Shared, here: string | null) {
  const st = useSessionsUI.getState()
  const before = sync.mine === undefined ? sync.start : sync.mine
  if (s.front && here === before && s.front !== frontId()) {
    const c = st.cols.find((x) => isSession(x) && x.id === s.front)
    if (c) st.focus(c.key)
  }
  sync.front = s.front ?? null
  // brought in front here since (a click, a link): still to send; else the one shown now is the agreed one, even when
  // the other device's could not come in front (not open here)
  sync.mine = here === before || here === s.front ? frontId() : before
}

/** The shared list and view (one request for every reader). */
export const useShared = () =>
  useQuery({
    queryKey: qk.openSessions,
    queryFn: ({ signal }) => api.get<Shared>('/api/sessions/open', undefined, { signal }),
    refetchOnWindowFocus: 'always',
  })

export function useOpenSync(mobile: boolean) {
  const { data } = useShared()
  cache = useQueryClient()
  React.useEffect(() => {
    sync.mobile = mobile
    sync.rev = 0
    sync.base = readBase()
    sync.order = localIds().join(' ')
    let timer: ReturnType<typeof setTimeout> | undefined
    const unsub = useSessionsUI.subscribe((s, prev) => {
      if (s.cols === prev.cols && s.tabs === prev.tabs && s.focused === prev.focused) return
      clearTimeout(timer)
      timer = setTimeout(flush, 150)
    })
    return () => {
      unsub()
      clearTimeout(timer)
    }
  }, [mobile])
  React.useEffect(() => {
    // a new page: the mode and the session in front start from what the other devices chose last
    sync.tabs = undefined
    sync.front = undefined
    sync.mine = undefined
    sync.start = frontId()
  }, [mobile])
  React.useEffect(() => {
    if (data) pull(data)
  }, [mobile, data])
}
