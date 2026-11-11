import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { forgetAllDrafts } from '../drafts'
import type { AuthState, ChangePasswordBody, LoginBody, LoginResult, Ok, PasskeyInfo, RecoveryCodes, SetupBody, TotpSetup, TwoFactorMethods, TwoFactorPoll } from '../types'
import type { PublicKeyCredentialCreationOptionsJSON, PublicKeyCredentialRequestOptionsJSON } from '../webauthn'
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
  // turning it off needs the current password
  return useMut((b: { enabled: boolean; password?: string }) => api.put<LoginResult>('/api/auth/two-factor', b), {
    invalidate: [qk.telegram.all, qk.authState],
    errorToast: false,
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
      forgetAllDrafts()
      window.location.assign('/login')
    },
  })
}

export function useChangePassword() {
  return useMut((b: ChangePasswordBody) => api.post<Ok>('/api/auth/password', b, { noAuthRedirect: true }), { errorToast: false })
}

/* ---- second step without Telegram: authenticator app, passkeys, recovery codes ---- */
/** Sign-in: an authenticator code or a recovery code for the ticket; `approved` sets the cookie. */
export const sendTwoFactorCode = (ticket: string, code: string, trust: boolean) =>
  api.post<TwoFactorPoll>('/api/auth/two-factor/code', { ticket, code, trust }, { noAuthRedirect: true })

export const passkeySignInOptions = (ticket: string) =>
  api.post<{ options: PublicKeyCredentialRequestOptionsJSON }>('/api/auth/two-factor/passkey/options', { ticket }, { noAuthRedirect: true })

export const sendPasskey = (ticket: string, credential: unknown, trust: boolean) =>
  api.post<TwoFactorPoll>('/api/auth/two-factor/passkey', { ticket, credential, trust }, { noAuthRedirect: true })

export function useTwoFactorMethods() {
  return useQuery({ queryKey: qk.twoFactorMethods, queryFn: () => api.get<TwoFactorMethods>('/api/auth/two-factor/methods') })
}

// every change below needs the current password (a signed-in browser alone cannot change the second step)
export function useTotpSetup() {
  return useMut((b: { password: string }) => api.post<TotpSetup>('/api/auth/two-factor/totp/setup', b, { noAuthRedirect: true }), { errorToast: false })
}

export function useTotpConfirm() {
  return useMut((b: { setup: string; code: string }) => api.post<RecoveryCodes>('/api/auth/two-factor/totp', b), {
    invalidate: [qk.twoFactorMethods],
    errorToast: false,
  })
}

export function useTotpOff() {
  return useMut((b: { password: string }) => api.post<Ok>('/api/auth/two-factor/totp/off', b, { noAuthRedirect: true }), {
    invalidate: [qk.twoFactorMethods],
    errorToast: false,
  })
}

export const passkeyAddOptions = (password: string) =>
  api.post<{ setup: string; options: PublicKeyCredentialCreationOptionsJSON }>('/api/auth/two-factor/passkeys/options', { password }, { noAuthRedirect: true })

export const passkeyAdd = (setup: string, credential: unknown, name: string) =>
  api.post<RecoveryCodes & { passkey: PasskeyInfo }>('/api/auth/two-factor/passkeys', { setup, credential, name })

export function usePasskeyRemove() {
  return useMut((b: { id: string; password: string }) => api.post<Ok>('/api/auth/two-factor/passkeys/remove', b, { noAuthRedirect: true }), {
    invalidate: [qk.twoFactorMethods],
    errorToast: false,
  })
}

export function useNewRecoveryCodes() {
  return useMut((b: { password: string }) => api.post<RecoveryCodes>('/api/auth/two-factor/recovery-codes', b, { noAuthRedirect: true }), {
    invalidate: [qk.twoFactorMethods],
    errorToast: false,
  })
}
