import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { LicenseState, Ok, Profile, RegisterState, Settings } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export const settingsQuery = () => ({ queryKey: qk.settings, queryFn: () => api.get<Settings>('/api/settings') })
export function useSettings(enabled = true) {
  return useQuery({ ...settingsQuery(), enabled })
}

/** Optimistic: PUT the merged object, write it to the cache immediately. */
export function useSaveSettings() {
  const qc = useQueryClient()
  return useMut(
    (patch: Partial<Settings>) => {
      const cur = qc.getQueryData<Settings>(qk.settings)
      return api.put<Ok>('/api/settings', { ...(cur || {}), ...patch })
    },
    {
      onMutate: async (patch) => {
        await qc.cancelQueries({ queryKey: qk.settings })
        const prev = qc.getQueryData<Settings>(qk.settings)
        if (prev) qc.setQueryData<Settings>(qk.settings, { ...prev, ...patch })
        return { prev }
      },
      onError: (_e, _v, ctx) => {
        const c = ctx as { prev?: Settings } | undefined
        if (c?.prev) qc.setQueryData(qk.settings, c.prev)
      },
      invalidate: [qk.settings, qk.authState],
    },
  )
}

export const profileQuery = () => ({ queryKey: qk.profile, queryFn: () => api.get<Profile>('/api/settings/profile'), staleTime: 5 * 60_000 })
/** The user's pseudo (empty name: none). */
export function useProfile() {
  return useQuery(profileQuery())
}
/** Optimistic: the pseudo changes everywhere at once; rolled back on error. */
export function useSaveProfile() {
  const qc = useQueryClient()
  return useMut((p: Profile) => api.put<Profile>('/api/settings/profile', p), {
    onMutate: async (p) => {
      await qc.cancelQueries({ queryKey: qk.profile })
      const prev = qc.getQueryData<Profile>(qk.profile)
      qc.setQueryData<Profile>(qk.profile, p)
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      const c = ctx as { prev?: Profile } | undefined
      if (c?.prev) qc.setQueryData(qk.profile, c.prev)
    },
    onSuccess: (p) => {
      qc.setQueryData(qk.profile, p)
    },
  })
}

/** Saying hello to the authors (Settings -> Profile, onboarding step Profile). */
export function useRegister() {
  return useQuery({ queryKey: qk.register, queryFn: () => api.get<RegisterState>('/api/settings/register') })
}
export function useSaveRegister() {
  return useMut((b: Partial<Pick<RegisterState, 'count' | 'email' | 'news' | 'asked'>>) => api.put<RegisterState>('/api/settings/register', b), {
    invalidate: [qk.register, qk.onboarding],
  })
}

// optional Enterprise key (Settings -> License, onboarding step "About you")
export function useLicense() {
  return useQuery({ queryKey: qk.license, queryFn: () => api.get<LicenseState>('/api/settings/license') })
}
export function useSaveLicense() {
  return useMut((key: string) => api.put<LicenseState>('/api/settings/license', { key }), { invalidate: [qk.license, ['system']], errorToast: false })
}
export function useRemoveLicense() {
  return useMut(() => api.del<LicenseState>('/api/settings/license'), { invalidate: [qk.license, ['system']] })
}
