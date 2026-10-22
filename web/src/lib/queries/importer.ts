import { useQuery } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { ImportAgent, ImportPlan, ImportResult, Ok } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export function useImportPrompt(agent: ImportAgent) {
  return useQuery({
    queryKey: ['import', 'prompt', agent],
    queryFn: () => api.get<{ agent: ImportAgent; prompt: string }>('/api/import/prompt', { agent }),
    staleTime: Infinity,
  })
}
export function useImportUpload() {
  return useMut((file: File) => api.upload<ImportPlan>('/api/import/upload', [file]), { errorToast: false })
}
export function useImportApply() {
  return useMut((id: string) => api.post<ImportResult>(`/api/import/${seg(id)}/apply`), {
    invalidate: [qk.workspace, qk.onboarding, qk.files.all],
    errorToast: false,
  })
}
export function useImportDiscard() {
  return useMut((id: string) => api.del<Ok>(`/api/import/${seg(id)}`), { errorToast: false })
}
