import { useQuery } from '@tanstack/react-query'
import { api, seg } from '../api'
import type {
  BrowserAsk, BrowserExit, BrowserExitKind, BrowserExitTest, BrowserOwner, BrowserProfile, BrowserProfileView, BrowserSettings,
  BrowserState, BrowserStatus, TailscaleStatus,
} from '../types'
import { useMut } from './util'

// The Harness Browser (api/browser.py). The bus topic `browser` refreshes every key below (BUS_KEYS).
export const browserKeys = {
  all: ['browser'] as const,
  status: ['browser', 'status'] as const,
  profile: (pid: string) => ['browser', 'profile', pid] as const,
  owner: (path: string) => ['browser', 'owner', path] as const,
  asks: (session: string) => ['browser', 'asks', session] as const,
  tailscale: (eid: string) => ['browser', 'tailscale', eid] as const,
}

/** `every`: refetch every N ms (the memory line of the sidebar; other changes come with the bus). */
export function useBrowserStatus(enabled = true, every?: number) {
  return useQuery({ queryKey: browserKeys.status, queryFn: () => api.get<BrowserStatus>('/api/browser'), enabled, refetchInterval: every })
}

/** One profile: its settings, its browser (tabs, turns...), who uses it, its journal. */
export function useBrowserProfile(pid: string | undefined, enabled = true) {
  return useQuery({
    queryKey: browserKeys.profile(pid || ''),
    queryFn: () => api.get<BrowserProfileView>(`/api/browser/profiles/${seg(pid || '')}`),
    enabled: enabled && !!pid,
  })
}

/** A project / topic / agent folder and the browser: what it sets, what it gets and where from. */
export function useBrowserOwner(path: string, enabled = true) {
  return useQuery({
    queryKey: browserKeys.owner(path),
    queryFn: () => api.get<BrowserOwner>('/api/browser/owner', { path }),
    enabled: enabled && !!path,
  })
}

/** Its own switch / profile; `inherit` gives a key back to its parent. */
export function useSaveBrowserOwner() {
  return useMut(
    (v: { path: string; enabled?: boolean; profile?: string; inherit?: ('enabled' | 'profile')[] }) => api.put<BrowserOwner>('/api/browser/owner', v),
    { invalidate: [browserKeys.all, ['agents', 'one'], ['workspace']] },
  )
}

/** Global settings (asks, downloads, sleep, profiles at once). */
export function useSaveBrowserSettings() {
  return useMut((v: Partial<BrowserSettings>) => api.put<BrowserStatus>('/api/browser/settings', v), {
    invalidate: [browserKeys.all],
    optimistic: (v) => [{ key: browserKeys.status, update: (o?: BrowserStatus) => o && { ...o, settings: { ...o.settings, ...v } } }],
  })
}

/** A new profile (no id), a change, or `remove` (its sign-ins too). */
export function useSaveBrowserProfile() {
  return useMut(
    ({ id, remove, ...v }: Partial<BrowserProfile> & { remove?: boolean }): Promise<BrowserProfile | { ok: boolean }> =>
      remove && id
        ? api.del<{ ok: boolean }>(`/api/browser/profiles/${seg(id)}`)
        : id
          ? api.put<BrowserProfile>(`/api/browser/profiles/${seg(id)}`, v)
          : api.post<BrowserProfile>('/api/browser/profiles', v),
    { invalidate: [browserKeys.all, ['workspace'], ['agents', 'one']] },
  )
}

/** open (start it for the person, with a tab in navigator `nav`) / stop / forget (sign-ins, tabs, journal) /
 *  sleep (every tab not shown sleeps). */
export function useProfileAction() {
  return useMut(
    ({ profile, action, nav }: { profile: string; action: 'open' | 'stop' | 'forget' | 'sleep'; nav?: string }) =>
      api.post<BrowserState>(`/api/browser/profiles/${seg(profile)}/${action}`, nav ? { nav } : {}),
    { invalidate: [browserKeys.all] },
  )
}

/** Tabs of a profile: a new one (the person's, in navigator `nav`), show (wakes an asleep one), close. */
export function useBrowserTab() {
  return useMut(
    (a: { profile: string } & ({ op: 'new'; url?: string; nav?: string } | { op: 'show' | 'close'; key: string })) => {
      const base = `/api/browser/profiles/${seg(a.profile)}/tabs`
      if (a.op === 'new') return api.post<BrowserState>(base, { url: a.url || '', ...(a.nav ? { nav: a.nav } : {}) })
      if (a.op === 'show') return api.post<BrowserState>(`${base}/${seg(a.key)}/show`)
      return api.del<BrowserState>(`${base}/${seg(a.key)}`)
    },
    { invalidate: [browserKeys.all] },
  )
}

export type ExitInput = { name?: string; type?: BrowserExitKind; url?: string; user?: string; secret?: string; node?: string; login_server?: string }

/** A new exit (no id), a change, or `remove`. `secret` (a password, a WireGuard config, an auth key) goes to the vault. */
export function useSaveExit() {
  return useMut(
    ({ id, remove, ...v }: ExitInput & { id?: string; remove?: boolean }): Promise<BrowserExit | { ok: boolean }> =>
      remove && id
        ? api.del<{ ok: boolean }>(`/api/browser/exits/${seg(id)}`)
        : id
          ? api.put<BrowserExit>(`/api/browser/exits/${seg(id)}`, v)
          : api.post<BrowserExit>('/api/browser/exits', v),
    { invalidate: [browserKeys.all] },
  )
}

/** The address the sites see through an exit ("direct": the server's own), its kind, delay and speed. */
export function useTestExit() {
  return useMut((id: string) => api.post<BrowserExitTest>(`/api/browser/exits/${seg(id)}/test`), { invalidate: [browserKeys.all] })
}

/** A Tailscale exit: signed in?, the sign-in address, the devices offered as exit node (polled while the wizard is open). */
export function useTailscale(eid: string | undefined, every?: number) {
  return useQuery({
    queryKey: browserKeys.tailscale(eid || ''),
    queryFn: () => api.get<TailscaleStatus>(`/api/browser/exits/${seg(eid || '')}/tailscale`),
    enabled: !!eid,
    refetchInterval: every,
  })
}

export function useTailscaleSet() {
  return useMut(
    ({ id, ...v }: { id: string; node?: string; action?: 'login' | 'logout' }) => api.post<TailscaleStatus>(`/api/browser/exits/${seg(id)}/tailscale`, v),
    { invalidate: [browserKeys.all] },
  )
}

/** A turn stopped by its exit: go on when it is back / test again now / forget the card. */
export function useExitWait() {
  return useMut(
    ({ session, action }: { session: string; action: 'resume' | 'retry' | 'dismiss' }) => api.post<{ ok: boolean }>(`/api/browser/waiting/${seg(session)}`, { action }),
    { invalidate: [browserKeys.all, ['sessions']] },
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

/** Install what is missing (`exits`: Tailscale and wireproxy too). */
export function useBrowserSetup() {
  return useMut((v?: { exits?: boolean }) => api.post<{ running: boolean }>('/api/browser/setup', v || {}), { invalidate: [browserKeys.all] })
}

/** A one-use token for the live view's WebSocket (30 s). */
export const browserLiveToken = () => api.post<{ token: string }>('/api/browser/live-token', {})
/** The files the person picked for the page that asked for some. */
export function giveBrowserFiles(profile: string, nav: string, files: File[]) {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  return api.post<BrowserState>(`/api/browser/profiles/${seg(profile)}/files?nav=${encodeURIComponent(nav)}`, form)
}

/** The person's browser on another profile (its tabs move there, asleep). */
export function useBrowserNavigator() {
  return useMut(({ profile }: { profile: string }): Promise<unknown> => api.put('/api/browser/navigators/me', { profile }), {
    invalidate: [browserKeys.all],
  })
}
