import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Ok, TrashList, TrashRestoreResult } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export const trashQuery = () => ({ queryKey: qk.trash, queryFn: () => api.get<TrashList>('/api/trash') })
export function useTrash() {
  return useQuery(trashQuery())
}
const inv = [qk.trash, qk.workspace, qk.sessions.all, qk.files.all] as const
export function useTrashRestore() {
  return useMut((id: string) => api.post<TrashRestoreResult>(`/api/trash/${encodeURIComponent(id)}/restore`), { invalidate: inv })
}
export function useTrashDelete() {
  return useMut((id: string) => api.del<Ok>(`/api/trash/${encodeURIComponent(id)}`), { invalidate: [qk.trash] })
}
export function useTrashEmpty() {
  return useMut(() => api.del<Ok & { deleted: number }>('/api/trash'), { invalidate: [qk.trash] })
}
