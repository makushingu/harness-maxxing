import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { forgetAllDrafts } from '../drafts'
import type { AuthState, ChangePasswordBody, LoginBody, LoginResult, Ok, RecoveryCodes, SecondFactor, SetupBody, SignedInBrowsers, TotpEnrol, TwoFactorPoll } from '../types'
import { qk } from './keys'
import { useMut } from './util'

declare global {
  interface Window {
    /** Auth check started by index.html before the bundle loaded (consumed once). */
    __mxAuth?: Promise<AuthState | null>
  }
}

const fetchAuthState = async () => {
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
  // turning it off needs the current password
  return useMut((b: { enabled: boolean; password?: string }) => api.put<LoginResult>('/api/auth/two-factor', b), {
    invalidate: [qk.telegram.all, qk.authState, secondFactorKey],
    errorToast: false,
  })
}

export function useForgetBrowsers() {
  return useMut(() => api.post<Ok>('/api/auth/two-factor/forget-browsers'), {})
}

const secondFactorKey = ['auth', 'second-factor'] as const
const browsersKey = ['auth', 'devices'] as const

export function useSecondFactor() {
  return useQuery({ queryKey: secondFactorKey, queryFn: () => api.get<SecondFactor>('/api/auth/second-factor') })
}

/** Authenticator app: `begin` gives the secret once, `confirm` turns it on (and gives the recovery codes). */
export function useTotpBegin() {
  return useMut((password: string) => api.post<TotpEnrol>('/api/auth/totp', { password }), { errorToast: false })
}

export function useTotpConfirm() {
  return useMut((code: string) => api.post<Ok & RecoveryCodes>('/api/auth/totp/confirm', { code }), { invalidate: [secondFactorKey], errorToast: false })
}

export function useTotpOff() {
  return useMut((b: { password: string; code: string }) => api.post<Ok>('/api/auth/totp/off', b), { invalidate: [secondFactorKey], errorToast: false })
}

export function useNewRecoveryCodes() {
  return useMut((password: string) => api.post<RecoveryCodes>('/api/auth/recovery-codes', { password }), { invalidate: [secondFactorKey], errorToast: false })
}

export function useSignedInBrowsers() {
  return useQuery({ queryKey: browsersKey, queryFn: () => api.get<SignedInBrowsers>('/api/auth/devices') })
}

export function useDisconnectBrowser() {
  return useMut((id: string) => api.del<Ok>(`/api/auth/devices/${encodeURIComponent(id)}`), { invalidate: [browsersKey] })
}

export function useDisconnectOthers() {
  return useMut(() => api.post<Ok>('/api/auth/devices/disconnect-others'), { invalidate: [browsersKey] })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMut(() => api.post<Ok>('/api/auth/logout', undefined, { noAuthRedirect: true }), {
    onSuccess: () => {
      qc.clear()
      forgetAllDrafts()
      window.location.assign('/login')
    },
  })
}

export function useChangePassword() {
  return useMut((b: ChangePasswordBody) => api.post<Ok>('/api/auth/password', b, { noAuthRedirect: true }), { invalidate: [browsersKey], errorToast: false })
}
