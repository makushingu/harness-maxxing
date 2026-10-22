import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { Ok, OnboardingState } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export function useOnboarding() {
  return useQuery({ queryKey: qk.onboarding, queryFn: () => api.get<OnboardingState>('/api/onboarding') })
}

export function useCompleteOnboarding() {
  const qc = useQueryClient()
  return useMut(() => api.post<Ok>('/api/onboarding/complete'), {
    invalidate: [qk.onboarding],
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.authState }),
  })
}
