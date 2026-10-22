import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { ClaudeAuthBody, ClaudeAuthResult, ClaudeSettingsBody, ClaudeStatus, ClaudeTestResult, Ok } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export const claudeStatusQuery = () => ({ queryKey: qk.claude, queryFn: () => api.get<ClaudeStatus>('/api/claude/status') })
export function useClaudeStatus() {
  return useQuery(claudeStatusQuery())
}

export function useClaudeAuth() {
  return useMut((b: ClaudeAuthBody) => api.post<ClaudeAuthResult>('/api/claude/auth', b), {
    invalidate: [qk.claude, qk.onboarding, qk.health],
    errorToast: false,
  })
}

export function useClaudeAuthRemove() {
  return useMut(() => api.del<Ok>('/api/claude/auth'), { invalidate: [qk.claude, qk.onboarding, qk.health] })
}

export function useClaudeTest() {
  return useMut(() => api.post<ClaudeTestResult>('/api/claude/test'), { invalidate: [qk.claude], errorToast: false })
}

export function useClaudeSettings() {
  return useMut((b: ClaudeSettingsBody) => api.put<Ok>('/api/claude/settings', b), {
    optimistic: (b) => [
      {
        key: qk.claude,
        update: (s: ClaudeStatus) => {
          const { claude_auto_update: on, ...rest } = b
          return { ...s, ...rest, ...(on !== undefined && s.auto_update ? { auto_update: { ...s.auto_update, enabled: on } } : {}) }
        },
      },
    ],
    invalidate: [qk.claude],
  })
}
