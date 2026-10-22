import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { AuthState, ChangePasswordBody, LoginBody, LoginResult, Ok, SetupBody, TwoFactorPoll } from '../types'
import { qk } from './keys'
import { useMut } from './util'

declare global {
  interface Window {
    /** Auth check started by index.html before the bundle loaded (consumed once). */
    __mxAuth?: Promise<AuthState | null>
  }
}

export const fetchAuthState = async () => {
  const early = window.__mxAuth
  window.__mxAuth = undefined
  const state = await early
  return state ?? api.get<AuthState>('/api/auth/state', undefined, { noAuthRedirect: true })
}

export function useAuthState() {
  return useQuery({ queryKey: qk.authState, queryFn: fetchAuthState, staleTime: 60_000, retry: 1 })
}

export function useSetup() {
  const qc = useQueryClient()
  return useMut((b: SetupBody) => api.post<Ok>('/api/auth/setup', b, { noAuthRedirect: true }), {
    errorToast: false,
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.authState }),
  })
}

export function useLogin() {
  const qc = useQueryClient()
  return useMut((b: LoginBody) => api.post<LoginResult>('/api/auth/login', b, { noAuthRedirect: true }), {
    errorToast: false,
    onSuccess: (r) => {
      if (r.ok) qc.invalidateQueries({ queryKey: qk.authState })
    },
  })
}

/** One poll of a two-step challenge (or its code typed by hand); `approved` sets the cookie. */
export const pollTwoFactor = (challenge: string, code?: string, trust = true) =>
  api.post<TwoFactorPoll>('/api/auth/two-factor', { challenge, code: code || undefined, trust }, { noAuthRedirect: true })

export function useSetTwoFactor() {
  return useMut((enabled: boolean) => api.put<LoginResult>('/api/auth/two-factor', { enabled }), {
    invalidate: [qk.telegram.all, qk.authState],
  })
}

export function useForgetBrowsers() {
  return useMut(() => api.post<Ok>('/api/auth/two-factor/forget-browsers'), {})
}

export function useLogout() {
  const qc = useQueryClient()
  return useMut(() => api.post<Ok>('/api/auth/logout', undefined, { noAuthRedirect: true }), {
    onSuccess: () => {
      qc.clear()
      window.location.assign('/login')
    },
  })
}

export function useChangePassword() {
  return useMut((b: ChangePasswordBody) => api.post<Ok>('/api/auth/password', b, { noAuthRedirect: true }), { errorToast: false })
}
