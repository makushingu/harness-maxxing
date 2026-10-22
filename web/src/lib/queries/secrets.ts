import { useQuery } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { Ok, Secret, SecretPutBody } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export const secretsQuery = () => ({ queryKey: qk.secrets, queryFn: () => api.get<Secret[]>('/api/secrets') })
export function useSecrets() {
  return useQuery(secretsQuery())
}
/** Not cached on purpose: a revealed value never stays in the query cache. */
export const revealSecret = (name: string) => api.get<{ value: string }>(`/api/secrets/${seg(name)}/reveal`)

export function usePutSecret() {
  return useMut(({ name, ...b }: SecretPutBody & { name: string }) => api.put<Ok>(`/api/secrets/${seg(name)}`, b), {
    // Only the switch / note change instantly; a new value waits for the server (its preview comes from there).
    optimistic: ({ name, value, ...b }) =>
      value === undefined ? [{ key: qk.secrets, update: (l: Secret[]) => l.map((x) => (x.name === name ? { ...x, ...b } : x)) }] : [],
    invalidate: [qk.secrets],
  })
}
export function useDeleteSecret() {
  return useMut((name: string) => api.del<Ok>(`/api/secrets/${seg(name)}`), { invalidate: [qk.secrets] })
}
