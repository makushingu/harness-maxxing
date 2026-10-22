import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { McpAddBody, McpView, Ok } from '../types'
import { useMut } from './util'

// Settings -> MCP (server/maxxing/mcp.py): the states come from a background `claude mcp list`; the bus topic `mcp` says when.
export const mcpKeys = { all: ['mcp'] as const }

export function useMcp() {
  return useQuery({
    queryKey: mcpKeys.all,
    queryFn: () => api.get<McpView>('/api/mcp'),
    refetchInterval: (q) => (q.state.data?.checking ? 2000 : false),
  })
}
export function useMcpCheck() {
  return useMut(() => api.post('/api/mcp/check', {}), { invalidate: [mcpKeys.all] })
}
export function useMcpAdd() {
  return useMut((b: McpAddBody) => api.post<{ id: string; exposed: string[] }>('/api/mcp', b), { invalidate: [mcpKeys.all], errorToast: false })
}
export function useMcpRemove() {
  return useMut((id: string) => api.del<Ok>(`/api/mcp?id=${encodeURIComponent(id)}`), { invalidate: [mcpKeys.all] })
}
export const mcpLoginStart = (id: string) => api.post<{ login: string; url: string }>('/api/mcp/login', { id })
export const mcpLoginFinish = (login: string, redirect: string) => api.post<{ ok: boolean; message: string }>(`/api/mcp/login/${login}`, { redirect })
export const mcpLoginCancel = (login: string) => api.del<Ok>(`/api/mcp/login/${login}`)
