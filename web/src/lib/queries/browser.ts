import { useQuery } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { BrowserAsk, BrowserOwner, BrowserScope, BrowserSettings, BrowserState, BrowserStatus } from '../types'
import { useMut } from './util'

// The Harness Browser (api/browser.py). The bus topic `browser` refreshes every key below (BUS_KEYS).
export const browserKeys = {
  all: ['browser'] as const,
  status: ['browser', 'status'] as const,
  owner: (path: string) => ['browser', 'owner', path] as const,
  asks: (session: string) => ['browser', 'asks', session] as const,
}

/** `every`: refetch every N ms (the memory line of the sidebar; other changes come with the bus). */
export function useBrowserStatus(enabled = true, every?: number) {
  return useQuery({ queryKey: browserKeys.status, queryFn: () => api.get<BrowserStatus>('/api/browser'), enabled, refetchInterval: every })
}

/** A topic (`projects/<p>/topics/<t>`) or an agent and the browser: its switch, the tabs it sees. */
export function useBrowserOwner(path: string, enabled = true) {
  return useQuery({
    queryKey: browserKeys.owner(path),
    queryFn: () => api.get<BrowserOwner>('/api/browser/owner', { path }),
    enabled: enabled && !!path,
  })
}

/** May the sessions of a topic / an agent use the browser. */
export function useBrowserSwitch() {
  return useMut(
    ({ path, enabled }: { path: string; enabled: boolean }) => api.put<BrowserOwner>('/api/browser/owner', { path, enabled }),
    {
      invalidate: [browserKeys.all, ['agents', 'one'], ['workspace']],
      optimistic: ({ path, enabled }) => [
        { key: browserKeys.owner(path), update: (o?: BrowserOwner) => o && { ...o, settings: { enabled } } },
      ],
    },
  )
}

/** The browser's own settings (sites, sign-ins, asks, sleep). */
export function useSaveBrowserSettings() {
  return useMut((v: Partial<BrowserSettings>) => api.put<BrowserSettings>('/api/browser/settings', v), {
    invalidate: [browserKeys.all],
    optimistic: (v) => [{ key: browserKeys.status, update: (o?: BrowserStatus) => o && { ...o, settings: { ...o.settings, ...v } } }],
  })
}

/** open (start it for the person; `session`: show that session's tab) / stop / forget (sign-ins, tabs, journal) /
 *  sleep (every tab not shown sleeps). */
export function useBrowserAction() {
  return useMut(
    ({ action, session }: { action: 'open' | 'stop' | 'forget' | 'sleep'; session?: string }) =>
      api.post<BrowserState>(`/api/browser/${action}`, session ? { session } : {}),
    { invalidate: [browserKeys.all] },
  )
}

/** Tabs: a new one (the person's), show (wakes an asleep one), its scope, close. */
export function useBrowserTab() {
  return useMut(
    (a: { op: 'new'; url?: string; scope?: BrowserScope } | { op: 'show' | 'close'; key: string } | { op: 'scope'; key: string; scope: BrowserScope }) => {
      if (a.op === 'new') return api.post<BrowserState>('/api/browser/tabs', { url: a.url || '', ...(a.scope ? { scope: a.scope } : {}) })
      if (a.op === 'show') return api.post<BrowserState>(`/api/browser/tabs/${seg(a.key)}/show`)
      if (a.op === 'scope') return api.put<BrowserState>(`/api/browser/tabs/${seg(a.key)}`, { scope: a.scope })
      return api.del<BrowserState>(`/api/browser/tabs/${seg(a.key)}`)
    },
    { invalidate: [browserKeys.all] },
  )
}

/** Pending `ask_human` requests of a session (asked only when it has some: Session.browser_asks). */
export function useSessionBrowserAsks(sid: string, enabled = true) {
  return useQuery({
    queryKey: browserKeys.asks(sid),
    queryFn: () => api.get<{ asks: BrowserAsk[] }>('/api/browser/asks', { session: sid }),
    enabled: enabled && !!sid,
    select: (d) => d.asks,
  })
}

export function useAnswerAsk() {
  return useMut(
    ({ id, action, note }: { id: string; action: 'done' | 'skip'; note?: string }) =>
      api.post<BrowserAsk>(`/api/browser/asks/${seg(id)}`, { action, ...(note ? { note } : {}) }),
    { invalidate: [browserKeys.all, ['sessions'], ['agents', 'thread']] },
  )
}

export function useBrowserSetup() {
  return useMut(() => api.post<{ running: boolean }>('/api/browser/setup'), { invalidate: [browserKeys.all] })
}

/** A one-use token for the live view's WebSocket (30 s). */
export const browserLiveToken = () => api.post<{ token: string }>('/api/browser/live-token', {})
