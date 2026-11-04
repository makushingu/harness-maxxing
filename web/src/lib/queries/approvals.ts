import { useQuery } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { Approval } from '../types'
import { useMut } from './util'

// Approvals: the tool calls an agent with `approvals` waits on. The bus topic `approvals` refreshes them (BUS_KEYS).
export const approvalKeys = {
  all: ['approvals'] as const,
  session: (sid: string) => ['approvals', 'session', sid] as const,
  pending: ['approvals', 'pending'] as const,
}

/** Pending requests of a session. Only asked when the session may have some (an agent folder). */
export function useSessionApprovals(sid: string, enabled = true) {
  return useQuery({
    queryKey: approvalKeys.session(sid),
    queryFn: () => api.get<{ approvals: Approval[] }>('/api/approvals', { session: sid }),
    enabled: enabled && !!sid,
    select: (d) => d.approvals,
  })
}

/** Every request waiting now, of every agent (the thread of an agent, the Office). */
export function usePendingApprovals(enabled = true) {
  return useQuery({
    queryKey: approvalKeys.pending,
    queryFn: () => api.get<{ approvals: Approval[] }>('/api/approvals'),
    enabled,
    select: (d) => d.approvals,
  })
}

export function useDecideApproval() {
  return useMut(
    ({ id, decision, message }: { id: string; decision: 'allow' | 'deny'; message?: string }) =>
      api.post<Approval>(`/api/approvals/${seg(id)}`, { decision, ...(message ? { message } : {}) }),
    { invalidate: [approvalKeys.all, ['agents']] },
  )
}
