import * as React from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Clock, Fingerprint } from 'lucide-react'
import { passkeyLogin, passkeyLoginOptions, qk, useAuthState, useLogin } from '@/lib/queries'
import { autofillSupported, getPasskey, passkeyCancelled, passkeysSupported, signalAccepted, signalUnknown } from '@/lib/webauthn'
import { markPasskeyOffer } from '@/features/auth/PasskeyOffer'
import { errorMessage, isApiError } from '@/lib/api'
import { safeNext } from '@/lib/utils'
import { useT } from '@/i18n'
import { Button, CodeBlock, FormField, SecretInput } from '@/components/ui'
import { TwoFactorWait } from '@/features/auth/TwoFactorWait'
import type { TwoFactorChallenge } from '@/lib/types'
import { AuthLayout } from './AuthLayout'

export default function LoginPage() {
  const t = useT()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [password, setPassword] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const [throttled, setThrottled] = React.useState<string | null>(null)
  const [challenge, setChallenge] = React.useState<TwoFactorChallenge | null>(null)
  const login = useLogin()
  const qc = useQueryClient()
  const input = React.useRef<HTMLInputElement>(null)
  const { data: auth } = useAuthState()
  const keyLogin = !!auth?.passkey_login && passkeysSupported()
  const [keyBusy, setKeyBusy] = React.useState(false)
  const autofill = React.useRef<AbortController | null>(null)

  const enter = () => {
    navigate(safeNext(params.get('next')), { replace: true })
  }

  // a passkey alone: the button opens the browser's window; the password field also offers it (autofill)
  const withPasskey = React.useCallback(
    async (conditional: boolean) => {
      const ctrl = new AbortController()
      autofill.current?.abort()
      if (conditional) autofill.current = ctrl
      else setKeyBusy(true)
      let options: Record<string, unknown> = {}
      let credential: Record<string, unknown> | null = null
      try {
        options = await passkeyLoginOptions()
        credential = await getPasskey(options, { conditional, signal: ctrl.signal })
        const r = await passkeyLogin(credential)
        signalAccepted(r.accepted)
        await qc.invalidateQueries({ queryKey: qk.authState })
        enter()
      } catch (e) {
        if (ctrl.signal.aborted || passkeyCancelled(e)) return
        if (isApiError(e, 'unknown_passkey') && credential && typeof options.rpId === 'string') {
          signalUnknown(options.rpId, String(credential.id))
          return setError(t('login.passkeyGone'))
        }
        setError(isApiError(e, 'bad_passkey') ? t('login.passkeyBad') : isApiError(e) && e.status === 429 ? t('login.throttled') : errorMessage(e))
      } finally {
        if (!conditional) setKeyBusy(false)
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [qc, t],
  )
  React.useEffect(() => {
    if (!keyLogin || challenge) return
    let live = true
    void autofillSupported().then((ok) => {
      if (ok && live) void withPasskey(true)
    })
    return () => {
      live = false
      autofill.current?.abort()
    }
  }, [keyLogin, challenge, withPasskey])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!password) {
      setError(t('login.required'))
      input.current?.focus()
      return
    }
    setError(null)
    setThrottled(null)
    login.mutate(
      { password },
      {
        onSuccess: (r) => {
          markPasskeyOffer()
          if (r.two_factor) {
            setPassword('')
            setChallenge(r.two_factor)
          } else enter()
        },
        onError: (err) => {
          if (isApiError(err) && err.status === 429) setThrottled(err.message && err.message !== 'throttled' ? err.message : t('login.throttled'))
          else if (isApiError(err, 'bad_password')) setError(t('login.bad'))
          else setError(errorMessage(err))
          setPassword('')
          requestAnimationFrame(() => input.current?.focus())
        },
      },
    )
  }

  if (challenge)
    return (
      <AuthLayout
        title={!challenge.methods || challenge.methods.join() === 'telegram' ? t('twofa.title') : t('twofa.titleAny')}
        subtitle={!challenge.methods || challenge.methods.join() === 'telegram' ? t('twofa.subtitle') : t('twofa.subtitleAny')}
      >
        <TwoFactorWait
          challenge={challenge}
          trustOption
          onDone={async (err) => {
            if (err === null) {
              await qc.invalidateQueries({ queryKey: qk.authState })
              return enter()
            }
            setChallenge(null)
            setError(err || null)
            requestAnimationFrame(() => input.current?.focus())
          }}
        />
      </AuthLayout>
    )

  return (
    <AuthLayout title={t('login.title')} subtitle={t('login.subtitle')}>
      <form onSubmit={submit} className="grid gap-5" noValidate>
        {keyLogin && (
          <>
            <Button type="button" size="lg" className="w-full" loading={keyBusy} onClick={() => withPasskey(false)}>
              <Fingerprint /> {t('login.passkey')}
            </Button>
            <div className="flex items-center gap-3 text-[12px] text-muted-foreground">
              <span className="h-px flex-1 bg-border" />
              {t('login.orPassword')}
              <span className="h-px flex-1 bg-border" />
            </div>
          </>
        )}
        {throttled && (
          <div role="alert" className="flex gap-3 rounded-lg border border-warning/30 bg-warning/10 p-3 text-[13px]">
            <Clock className="mt-0.5 size-4 shrink-0 text-warning" />
            <span>{throttled}</span>
          </div>
        )}
        <FormField label={t('login.password')} error={error || undefined}>
          <SecretInput ref={input} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={keyLogin ? 'current-password webauthn' : 'current-password'} autoFocus={!keyLogin} name="password" />
        </FormField>
        <Button type="submit" size="lg" variant={keyLogin ? 'outline' : 'default'} loading={login.isPending} className="w-full">
          {t('login.submit')} <ArrowRight />
        </Button>
        <details className="group text-[13px] text-muted-foreground">
          <summary className="cursor-pointer list-none text-center hover:text-foreground pointer-coarse:flex pointer-coarse:min-h-10 pointer-coarse:items-center pointer-coarse:justify-center">{t('login.forgot')}</summary>
          <div className="mt-3 grid gap-2">
            <p>{t('login.forgotHelp')}</p>
            <CodeBlock inline code="maxxing password" />
          </div>
        </details>
      </form>
    </AuthLayout>
  )
}
