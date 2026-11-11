import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { forgetAllDrafts } from '../drafts'
import { createPasskey, getPasskey } from '../webauthn'
import type { AuthMethods, AuthState, ChangePasswordBody, LoginBody, LoginResult, Ok, Passkey, RecoveryCodes, SetupBody, TotpSetup, TwoFactorPoll } from '../types'
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
export const pollTwoFactor = (challenge: string, code?: string, trust = true, passkey?: Record<string, unknown>) =>
  api.post<TwoFactorPoll>('/api/auth/two-factor', { challenge, code: code || undefined, passkey, trust }, { noAuthRedirect: true })

/** The options of navigator.credentials.get() for a waiting sign-in request. */
export const passkeyPrompt = (challenge: string) =>
  api.post<Record<string, unknown>>('/api/auth/two-factor/passkey', { challenge }, { noAuthRedirect: true })

/** Sign-in with a passkey alone: the prompt, then the answer (sets the cookie). */
export const passkeyLoginOptions = () => api.post<Record<string, unknown>>('/api/auth/passkey-login/options', undefined, { noAuthRedirect: true })
export const passkeyLogin = (credential: Record<string, unknown>, trust = true) =>
  api.post<{ ok: boolean; accepted?: { rp_id: string; user: string | null; ids: string[] } }>('/api/auth/passkey-login', { credential, trust }, { noAuthRedirect: true })

/** Confirms a sensitive action with a passkey: the next requests of this session skip the current password a few
 *  minutes (send an empty password). */
export async function reauthWithPasskey() {
  const options = await api.post<Record<string, unknown>>('/api/auth/reauth/options')
  const credential = await getPasskey(options)
  return api.post<{ ok: boolean; expires_in: number }>('/api/auth/reauth', { credential })
}

export function useSetPasskeyLogin() {
  return useMut((b: { enabled: boolean; password?: string }) => api.put<{ ok: boolean; enabled: boolean }>('/api/auth/passkey-login', b), {
    invalidate: [qk.authMethods, qk.authState],
    errorToast: false,
  })
}

// ---- authenticator app, passkeys, recovery codes (Settings -> Security) ----
export function useAuthMethods(enabled = true) {
  return useQuery({ queryKey: qk.authMethods, queryFn: () => api.get<AuthMethods>('/api/auth/methods'), enabled })
}

const methodsMut = { invalidate: [qk.authMethods, qk.authState], errorToast: false } as const

export function useTotpSetup() {
  return useMut(() => api.post<TotpSetup>('/api/auth/totp/setup'), { errorToast: false })
}

export function useTotpConfirm() {
  return useMut((code: string) => api.post<RecoveryCodes>('/api/auth/totp/confirm', { code }), methodsMut)
}

export function useTotpRemove() {
  return useMut((password: string) => api.del<Ok>('/api/auth/totp', { body: { password } }), methodsMut)
}

/** Asks the server for options, lets the browser (or the password manager) make the passkey, sends it back. */
export function useAddPasskey() {
  return useMut(
    async (name: string) => {
      const options = await api.post<Record<string, unknown>>('/api/auth/passkeys/options')
      const credential = await createPasskey(options)
      return api.post<RecoveryCodes & { passkey: Passkey }>('/api/auth/passkeys', { credential, name })
    },
    methodsMut,
  )
}

export function useRenamePasskey() {
  return useMut((b: { id: string; name: string }) => api.patch<Ok>(`/api/auth/passkeys/${encodeURIComponent(b.id)}`, { name: b.name }), methodsMut)
}

export function useRemovePasskey() {
  return useMut((b: { id: string; password: string }) => api.del<Ok>(`/api/auth/passkeys/${encodeURIComponent(b.id)}`, { body: { password: b.password } }), methodsMut)
}

export function useNewRecoveryCodes() {
  return useMut((password: string) => api.post<RecoveryCodes>('/api/auth/recovery-codes', { password }), methodsMut)
}

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
