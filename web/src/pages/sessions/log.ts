// Per-session event log, shared by every view of a session in this tab.
// - first load: GET /events?tail=100 (TAIL_EVENTS) (the server reads the log backwards: a 500 MB log opens instantly);
// - older events on demand: GET /events?before=<start> ("Show earlier messages"), prepended;
// - then live: SSE /stream?from=<next> (re-evaluated on reconnect → no gap, no duplicate);
// - `reset` (log rewritten by `maxxing sessions compact-logs`): the tail is reloaded;
// - events are folded into render *items* incrementally (tool_use + tool_result = one item), so
//   existing items keep their identity and memoised rows never re-render on append.
// The cache survives column moves / remounts (no reload, no flash).
import * as React from 'react'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { fetchBefore, fetchTail, qk, takeEarlyTail, TAIL_EVENTS, useSetSessionCache } from '@/lib/queries'
import { refreshFileStamps } from '@/lib/queries/files'
import { errorMessage } from '@/lib/api'
import { useEventSource } from '@/lib/sse'
import type { Session, SessionEvent, SessionStreamEvents } from '@/lib/types'
import { usePending } from './store'

type Ev<T extends SessionEvent['type']> = Extract<SessionEvent, { type: T }>

export type Item =
  | { kind: 'user'; key: string; ev: Ev<'user'>; /** Voice message sent directly: its transcript once it came. */ heard?: Ev<'voice_text'> }
  | { kind: 'request'; key: string; ev: Ev<'user'> } // system-sourced prompt (compact / handoff summary)
  | { kind: 'assistant'; key: string; ev: Ev<'assistant'> }
  | { kind: 'thinking'; key: string; ev: Ev<'thinking'> }
  | { kind: 'tool'; key: string; use: Ev<'tool_use'>; result: Ev<'tool_result'> | null }
  | { kind: 'init'; key: string; ev: Ev<'init'> }
  | { kind: 'result'; key: string; ev: Ev<'result'> }
  | { kind: 'note'; key: string; ev: Ev<'note'> }

export type LogState = {
  status: 'loading' | 'ready' | 'error'
  error: string | null
  items: Item[]
  next: number
  /** Number of events folded so far (stable keys). */
  count: number
  toolIdx: Record<string, number>
  lastModel: string | null
  /** `at` of the last user event (running timer). */
  lastUserAt: number | null
  deleted: boolean
  /** Byte offset of the first loaded log line; `moreBefore` = older events exist on the server. */
  start: number
  moreBefore: boolean
  loadingEarlier: boolean
  /** Number of older pages prepended (stable keys for prepended items). */
  batches: number
  /** Tool results whose tool_use is older than the loaded window (attached when it gets loaded). */
  orphans: Record<string, Ev<'tool_result'>>
  /** User messages hidden from the thread, by their `at` (`hide` events; the latest one wins). */
  hidden: Record<string, boolean>
}

const EARLIER_EVENTS = 200

const INITIAL: LogState = {
  status: 'loading',
  error: null,
  items: [],
  next: 0,
  count: 0,
  toolIdx: {},
  lastModel: null,
  lastUserAt: null,
  deleted: false,
  start: 0,
  moreBefore: false,
  loadingEarlier: false,
  batches: 0,
  orphans: {},
  hidden: {},
}

const cache = new Map<string, LogState>()
const listeners = new Map<string, Set<() => void>>()
const loading = new Map<string, Promise<void>>()

function get(id: string): LogState {
  return cache.get(id) || INITIAL
}
function put(id: string, st: LogState) {
  cache.set(id, st)
  listeners.get(id)?.forEach((l) => l())
}
/** A log nobody shows any more (its column closed) leaves memory after a while: a long session open once would
 *  otherwise stay in the tab until it is closed. Opened again, it loads its tail again. */
const EVICT_MS = 120_000
function subscribe(id: string, fn: () => void) {
  let set = listeners.get(id)
  if (!set) listeners.set(id, (set = new Set()))
  set.add(fn)
  return () => {
    set!.delete(fn)
    if (set!.size) return
    setTimeout(() => {
      if (listeners.get(id)?.size || loading.has(id)) return
      cache.delete(id)
      listeners.delete(id)
    }, EVICT_MS)
  }
}

/** Fold raw events into items (returns a new state; untouched items keep their identity). */
export function fold(st: LogState, evs: SessionEvent[], next: number, sid: string, keyPrefix = 'e', settlePending = true): LogState {
  if (!evs.length) return next === st.next ? st : { ...st, next }
  const items = st.items.slice()
  const toolIdx = { ...st.toolIdx }
  let orphans = st.orphans
  let hidden = st.hidden
  let { count, lastModel, lastUserAt } = st
  const settle = settlePending ? usePending.getState().settle : () => {}
  for (const ev of evs) {
    const key = `${keyPrefix}${count++}`
    switch (ev.type) {
      case 'user':
        if ((ev.source as string) === 'system') items.push({ kind: 'request', key, ev })
        else {
          items.push({ kind: 'user', key, ev })
          settle(sid, ev.text)
        }
        lastUserAt = ev.at
        break
      case 'assistant':
        items.push({ kind: 'assistant', key, ev })
        break
      case 'thinking':
        items.push({ kind: 'thinking', key, ev })
        break
      case 'tool_use':
        toolIdx[ev.id] = items.length
        items.push({ kind: 'tool', key, use: ev, result: null })
        break
      case 'tool_result': {
        const i = toolIdx[ev.tool_use_id]
        const it = i != null ? items[i] : undefined
        if (it && it.kind === 'tool') items[i] = { ...it, result: ev }
        else orphans = { ...orphans, [ev.tool_use_id]: ev } // its tool_use is in an older page
        break
      }
      case 'init':
        // Only show the model row when it changes (first turn, or a different model).
        if (ev.model && ev.model !== lastModel) items.push({ kind: 'init', key, ev })
        if (ev.model) lastModel = ev.model
        break
      case 'result':
        items.push({ kind: 'result', key, ev })
        break
      case 'note':
        items.push({ kind: 'note', key, ev })
        break
      case 'hide':
        hidden = { ...hidden, [String(ev.ref)]: ev.hidden }
        break
      case 'voice_text': {
        // The transcript belongs to the last voice message (written by the runner right after it).
        for (let i = items.length - 1; i >= 0; i--) {
          const it = items[i]
          if (it.kind !== 'user') continue
          if (it.ev.voice?.length && !it.heard) items[i] = { ...it, heard: ev }
          break
        }
        break
      }
    }
  }
  return { ...st, items, toolIdx, orphans, hidden, count, lastModel, lastUserAt, next }
}

/** Prepend an older page (events strictly before `st.start`): existing items keep their identity. */
export function foldBefore(st: LogState, evs: SessionEvent[], start: number, moreBefore: boolean, sid: string): LogState {
  const base = { ...st, start, moreBefore, loadingEarlier: false }
  if (!evs.length) return base
  const older = fold({ ...INITIAL, status: 'ready' }, evs, 0, sid, `b${st.batches}-`, false)
  const orphans = { ...older.orphans }
  // Results already loaded whose tool_use only arrives now.
  const head = older.items.map((it) => {
    if (it.kind !== 'tool' || it.result) return it
    const r = st.orphans[it.use.id]
    return r ? { ...it, result: r } : it
  })
  for (const [id, r] of Object.entries(st.orphans)) if (!(id in older.toolIdx)) orphans[id] = r
  let tail = st.items
  // The model row is only shown when the model changes: drop the first one if the older page ends on it.
  const firstInit = tail.findIndex((it) => it.kind === 'init')
  if (firstInit >= 0 && older.lastModel) {
    const it = tail[firstInit]
    if (it.kind === 'init' && it.ev.model === older.lastModel) tail = tail.filter((_, i) => i !== firstInit)
  }
  const items = [...head, ...tail]
  const toolIdx: Record<string, number> = {}
  items.forEach((it, i) => {
    if (it.kind === 'tool') toolIdx[it.use.id] = i
  })
  return {
    ...base,
    items,
    toolIdx,
    orphans,
    hidden: { ...older.hidden, ...st.hidden },           // the newer hide events win
    batches: st.batches + 1,
    lastModel: st.lastModel ?? older.lastModel,
    lastUserAt: st.lastUserAt ?? older.lastUserAt,
  }
}

export function loadLog(id: string, force = false): Promise<void> {
  const cur = cache.get(id)
  if (!force && cur && cur.status !== 'error') return Promise.resolve()
  const running = loading.get(id)
  if (running) return running
  if (!cur || force) put(id, { ...INITIAL })
  const p = ((!force && takeEarlyTail(id)) || fetchTail(id, TAIL_EVENTS))
    .then((page) => {
      const st = fold({ ...INITIAL, status: 'ready' }, page.events, page.next, id)
      put(id, { ...st, status: 'ready', start: page.start, moreBefore: page.more_before })
    })
    .catch((e) => {
      put(id, { ...INITIAL, status: 'error', error: errorMessage(e), deleted: (e as { status?: number })?.status === 404 })
    })
    .finally(() => loading.delete(id))
  loading.set(id, p)
  return p
}

/** Load the previous page of events (before the first loaded line) and prepend it. */
export function loadEarlier(id: string): Promise<void> {
  const cur = get(id)
  if (cur.status !== 'ready' || !cur.moreBefore || cur.loadingEarlier) return Promise.resolve()
  put(id, { ...cur, loadingEarlier: true })
  return fetchBefore(id, cur.start, EARLIER_EVENTS)
    .then((page) => {
      const now = get(id)
      if (now.status !== 'ready' || now.start !== cur.start) return // reloaded meanwhile
      if (page.reset) return void loadLog(id, true)
      put(id, foldBefore(now, page.events, page.start, page.more_before, id))
    })
    .catch(() => {
      const now = get(id)
      if (now.loadingEarlier) put(id, { ...now, loadingEarlier: false })
    })
}

export function forgetLog(id: string) {
  cache.delete(id)
}

/** Subscribe to a session log; loads it and keeps it live while `live` is true. Re-renders on every new event:
 *  a view that only needs the stream open uses useSessionStream (+ useLogSelect for a field). */
export function useSessionLog(id: string | null, live = true): LogState {
  const st = React.useSyncExternalStore(
    React.useCallback((fn) => (id ? subscribe(id, fn) : () => {}), [id]),
    () => (id ? get(id) : INITIAL),
  )
  useSessionStream(live ? id : null)
  React.useEffect(() => {
    if (id) void loadLog(id)
  }, [id])
  return st
}

/** One value derived from a session log (a primitive): re-renders only when it changes. */
export function useLogSelect<T>(id: string | null, select: (st: LogState) => T): T {
  return React.useSyncExternalStore(
    React.useCallback((fn) => (id ? subscribe(id, fn) : () => {}), [id]),
    () => select(id ? get(id) : INITIAL),
  )
}

let refreshTimer = 0
function refreshSoon(qc: QueryClient) {
  if (refreshTimer) return
  refreshTimer = window.setTimeout(() => {
    refreshTimer = 0
    void refreshFileStamps(qc)
  }, 800)
}

/** Loads a session log and keeps it live (SSE), without re-rendering the caller on each event. */
export function useSessionStream(id: string | null) {
  React.useEffect(() => {
    if (id) void loadLog(id)
  }, [id])
  const setSession = useSetSessionCache()
  const qc = useQueryClient()
  const ready = useLogSelect(id, (st) => st.status === 'ready' && !st.deleted)
  useEventSource(
    id && ready ? () => `/api/sessions/${encodeURIComponent(id!)}/stream?from=${get(id!).next}` : null,
    {
      events: (data: SessionStreamEvents) => {
        if (!id || !data || typeof data.next !== 'number') return
        const cur = get(id)
        if (data.next <= cur.next) return // already have it (reconnect overlap)
        put(id, fold(cur, data.events || [], data.next, id))
        // A tool result or the end of a turn: files may have been written - previews on screen re-check theirs.
        // The end of a turn also refreshes the folder listings on screen (Files page, folder in the viewer).
        const evs = data.events || []
        if (evs.some((e) => e?.type === 'result')) void qc.invalidateQueries({ queryKey: ['files', 'list'] })
        if (evs.some((e) => e?.type === 'tool_result' || e?.type === 'result')) refreshSoon(qc)
      },
      // The log was rewritten under us (compact-logs) or our offset is stale: reload the tail.
      reset: () => {
        if (id) void loadLog(id, true)
      },
      state: (s: Session | null) => {
        if (!id) return
        if (s === null) {
          put(id, { ...get(id), deleted: true })
          qc.invalidateQueries({ queryKey: qk.sessions.all })
          return
        }
        setSession(s)
      },
    },
  )
}

/** A brand-new session has an empty log: mark it ready so its column renders without a skeleton. */
export function seedEmptyLog(id: string) {
  if (!cache.has(id)) put(id, { ...INITIAL, status: 'ready' })
}

/** Hide (or show again) a user message at once, before the server's `hide` event comes back. */
export function setHiddenLocal(sid: string, at: number, hidden: boolean) {
  const st = cache.get(sid)
  if (st) put(sid, { ...st, hidden: { ...st.hidden, [String(at)]: hidden } })
}

/** The thread without its hidden messages: a hidden user message takes its whole turn with it (the rows up to the
 *  next message). */
export function withoutHidden(items: Item[], hidden: Record<string, boolean>): Item[] {
  if (!Object.values(hidden).some(Boolean)) return items
  const out: Item[] = []
  let skipping = false
  for (const it of items) {
    if (it.kind === 'user' || it.kind === 'request') skipping = it.kind === 'user' && !!hidden[String(it.ev.at)]
    if (!skipping) out.push(it)
  }
  return out
}

/** Keys of the user messages that got no answer (their turn was stopped or failed before Claude wrote anything):
 *  those can be deleted from the thread. While the session runs, nothing after the last finished turn (the running
 *  turn may still answer them, a steered message included). */
export function unanswered(items: Item[], running: boolean): Set<string> {
  const out = new Set<string>()
  let end = items.length
  if (running) {
    end = 0
    for (let i = items.length - 1; i >= 0; i--)
      if (items[i].kind === 'result') {
        end = i + 1
        break
      }
  }
  let cur: string | null = null
  let answered = false
  for (let i = 0; i < end; i++) {
    const it = items[i]
    if (it.kind === 'user' || it.kind === 'request') {
      if (cur && !answered) out.add(cur)
      cur = it.kind === 'user' ? it.key : null
      answered = false
    } else if (it.kind === 'assistant' || it.kind === 'thinking' || it.kind === 'tool') answered = true
  }
  if (cur && !answered) out.add(cur)
  return out
}

/** The keys of a message's turn (the message and the rows up to the next message). */
export function turnKeys(items: Item[], key: string): string[] {
  const i = items.findIndex((it) => it.key === key)
  if (i < 0) return []
  const out = [key]
  for (let j = i + 1; j < items.length && items[j].kind !== 'user' && items[j].kind !== 'request'; j++) out.push(items[j].key)
  return out
}
