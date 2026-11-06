import { useQuery } from '@tanstack/react-query'
import { api, request, seg } from '../api'
import type { Ok, Secret, SecretFile, SecretFilePutBody, SecretPutBody } from '../types'
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

/** Files of the vault (`/api/secret-files`): the list never holds a content. */
export function useSecretFiles() {
  return useQuery({ queryKey: qk.secretFiles, queryFn: () => api.get<SecretFile[]>('/api/secret-files') })
}
/** Raw-body upload; without `file` (empty body) only the note / switch change and the stored file is kept.
 *  `errorToast: false` for a form that shows the error itself. */
export function usePutSecretFile({ errorToast = true }: { errorToast?: boolean } = {}) {
  return useMut(
    ({ name, file, ...q }: SecretFilePutBody & { name: string }) =>
      request<Ok>(`/api/secret-files/${seg(name)}`, {
        method: 'PUT',
        query: { ...q, filename: file?.name },
        body: file ?? new Blob([]),
      }),
    {
      optimistic: ({ name, file, ...b }) =>
        file ? [] : [{ key: qk.secretFiles, update: (l: SecretFile[]) => l.map((x) => (x.name === name ? { ...x, ...b } : x)) }],
      invalidate: [qk.secretFiles],
      errorToast,
    },
  )
}
export function useDeleteSecretFile() {
  return useMut((name: string) => api.del<Ok>(`/api/secret-files/${seg(name)}`), { invalidate: [qk.secretFiles] })
}
