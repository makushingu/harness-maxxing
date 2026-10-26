// Server-Sent Events helpers.
// - useEventSource(url, handlers): generic, reusable (session streams). Auto-reconnects with backoff.
//   `url` may be a function: it is re-evaluated on every (re)connection, so callers can resume from
//   the latest offset (e.g. () => `/api/sessions/${id}/stream?from=${nextRef.current}`).
// - useGlobalBus(): connects /api/stream once and invalidates React Query keys by topic.
import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { BUS_KEYS, BUS_TURN_KEYS, LIVE_KEYS } from './queries/keys'
import type { BusTopic, InvalidatePayload } from './types'
import { checkForUpdate } from '@/pwa'

export type SSEStatus = 'connecting' | 'open' | 'reconnecting' | 'closed'
type Handlers = Record<string, (data: any, ev: MessageEvent) => void>

export type UseEventSourceOptions = {
  enabled?: boolean
  /** Called after a reconnection (not the first open) with how long the stream was down: refetch what may have
   *  been missed. */
  onReconnect?: (downMs: number) => void
  /** Max backoff (ms). Default 15 s. */
  maxDelay?: number
}

export function useEventSource(url: string | null | (() => string | null), handlers: Handlers, opts: UseEventSourceOptions = {}): SSEStatus {
  const { enabled = true, maxDelay = 15_000 } = opts
  const [status, setStatus] = useState<SSEStatus>('connecting')
  const handlersRef = useRef(handlers)
  const urlRef = useRef(url)
  const reconnectRef = useRef(opts.onReconnect)
  handlersRef.current = handlers
  urlRef.current = url
  reconnectRef.current = opts.onReconnect
  // Re-subscribe only when a *string* url changes (functions are read through the ref).
  const key = typeof url === 'function' ? 'fn' : url

  useEffect(() => {
    if (!enabled || key === null) {
      setStatus('closed')
      return
    }
    let es: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let attempt = 0
    let stopped = false
    let opened = false
    let lostAt = 0 // when the open stream dropped (0 = not lost since the last open)
    const names = new Set<string>()

    const connect = () => {
      if (stopped) return
      const u = urlRef.current
      const resolved = typeof u === 'function' ? u() : u
      if (!resolved) return
      setStatus(attempt === 0 ? 'connecting' : 'reconnecting')
      es = new EventSource(resolved, { withCredentials: true })
      const dispatch = (ev: MessageEvent) => {
        const h = handlersRef.current[ev.type]
        if (!h) return
        let data: unknown = ev.data
        try {
          data = JSON.parse(ev.data)
        } catch {
          /* plain text */
        }
        h(data, ev)
      }
      names.clear()
      for (const n of Object.keys(handlersRef.current)) {
        names.add(n)
        es.addEventListener(n, dispatch as EventListener)
      }
      es.onopen = () => {
        if (opened && attempt > 0) reconnectRef.current?.(lostAt ? Date.now() - lostAt : 0)
        opened = true
        lostAt = 0
        attempt = 0
        setStatus('open')
      }
      es.onerror = () => {
        // Close and retry ourselves: the native retry gives up on HTTP errors (e.g. 401/502).
        es?.close()
        es = null
        if (stopped) return
        if (!lostAt) lostAt = Date.now()
        attempt++
        setStatus('reconnecting')
        const delay = Math.min(maxDelay, 500 * 2 ** Math.min(attempt, 6)) * (0.8 + Math.random() * 0.4)
        timer = setTimeout(connect, delay)
      }
    }

    const onVisible = () => {
      // Reconnect immediately when the tab comes back and the socket was dropped meanwhile.
      if (document.visibilityState === 'visible' && !es && !stopped) {
        clearTimeout(timer)
        connect()
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    connect()
    return () => {
      stopped = true
      clearTimeout(timer)
      es?.close()
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [key, enabled, maxDelay])

  return status
}

const RECONNECT_REFRESH_MS = 5_000
/** A tab hidden that long refreshes the bus-covered data when shown again (a frozen mobile tab may have missed
 *  events without its stream dropping). Shorter absences rely on the stream (see isLiveKey). */
const HIDDEN_REFRESH_MS = 60_000

/** Mount once inside the authenticated shell. */
export function useGlobalBus(enabled: boolean): SSEStatus {
  const qc = useQueryClient()
  // A streaming turn emits many invalidations: batch them (one refetch per key per 250 ms instead of one per event).
  const pending = useRef(new Set<string>())
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  useEffect(() => {
    if (!enabled) return
    let hiddenAt = 0
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') hiddenAt = Date.now()
      else if (hiddenAt && Date.now() - hiddenAt >= HIDDEN_REFRESH_MS) {
        hiddenAt = 0
        for (const k of LIVE_KEYS) void qc.invalidateQueries({ queryKey: k })
      } else hiddenAt = 0
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [enabled, qc])
  const invalidate = (keys: readonly (readonly unknown[])[]) => {
    const seen = new Set<string>()
    for (const k of keys) {
      const id = JSON.stringify(k)
      if (seen.has(id)) continue
      seen.add(id)
      qc.invalidateQueries({ queryKey: k })
    }
  }
  return useEventSource(
    '/api/stream',
    {
      invalidate: (data: InvalidatePayload) => {
        const topics = Array.isArray(data?.topics) ? data.topics : []
        for (const t of topics) pending.current.add(t)
        if (timer.current) return
        timer.current = setTimeout(() => {
          timer.current = undefined
          const batch = [...pending.current] as BusTopic[]
          pending.current.clear()
          const keys = batch.flatMap((t) => BUS_KEYS[t] || [])
          if (batch.includes('sessions') && batch.includes('workspace')) keys.push(...BUS_TURN_KEYS)
          invalidate(keys)
        }, 250)
      },
    },
    {
      enabled,
      // We may have missed invalidations while disconnected: refresh what the bus covers (mounted queries only).
      // A blip shorter than RECONNECT_REFRESH_MS (proxy idle timeout, server reload) is not worth a refetch storm.
      onReconnect: (downMs) => {
        checkForUpdate() // the server restarted, maybe updated: the new build then loads by itself
        if (downMs >= RECONNECT_REFRESH_MS) invalidate([...Object.values(BUS_KEYS).flat(), ...BUS_TURN_KEYS])
      },
    },
  )
}
