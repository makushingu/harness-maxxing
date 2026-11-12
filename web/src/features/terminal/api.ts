// Terminals of the web app (server: maxxing/terminal.py, api/term.py). Off by default (Settings -> Features ->
// Terminal, password asked again); a drawer under a session's conversation (TermDrawer.tsx), never for agents.
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export type TermInfo = { id: string; cwd: string; title: string; started: number; last: number; alive: boolean; clients: number }
export type TermState = { enabled: boolean; terms: TermInfo[]; max: number }

export const termKey = ['term'] as const

export function useTermState(enabled = true) {
  return useQuery({ queryKey: termKey, queryFn: () => api.get<TermState>('/api/term'), enabled, staleTime: 5_000 })
}

export const termApi = {
  enable: (password: string) => api.post<{ enabled: boolean }>('/api/term/enable', { password }),
  disable: () => api.post<{ enabled: boolean; closed: number }>('/api/term/disable', {}),
  open: (cwd: string, cols: number, rows: number) => api.post<TermInfo & { token: string }>('/api/term', { cwd, cols, rows }),
  token: (id: string) => api.post<{ token: string }>(`/api/term/${id}/token`, {}),
  close: (id: string) => api.del<{ ok: boolean }>(`/api/term/${id}`),
}

export function termSocketUrl(id: string, token: string): string {
  const u = new URL(`/api/term/${id}/ws`, window.location.href)
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:'
  u.searchParams.set('token', token)
  return u.toString()
}

/** Agents never get a terminal: their sessions live in an agent folder. */
export const isAgentPath = (path: string) => /(^|\/)agents\//.test(path)
