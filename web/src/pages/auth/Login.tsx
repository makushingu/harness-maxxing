import * as React from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Clock } from 'lucide-react'
import { qk, useLogin } from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
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

  const enter = () => {
    const next = params.get('next')
    navigate(next && next.startsWith('/') && !next.startsWith('//') ? next : '/', { replace: true })
  }

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
      <AuthLayout title={t('twofa.title')} subtitle={t('twofa.subtitle')}>
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
        {throttled && (
          <div role="alert" className="flex gap-3 rounded-lg border border-warning/30 bg-warning/10 p-3 text-[13px]">
            <Clock className="mt-0.5 size-4 shrink-0 text-warning" />
            <span>{throttled}</span>
          </div>
        )}
        <FormField label={t('login.password')} error={error || undefined}>
          <SecretInput ref={input} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus name="password" />
        </FormField>
        <Button type="submit" size="lg" loading={login.isPending} className="w-full">
          {t('login.submit')} <ArrowRight />
        </Button>
        <details className="group text-[13px] text-muted-foreground">
          <summary className="cursor-pointer list-none text-center hover:text-foreground">{t('login.forgot')}</summary>
          <div className="mt-3 grid gap-2">
            <p>{t('login.forgotHelp')}</p>
            <CodeBlock inline code="maxxing password" />
          </div>
        </details>
      </form>
    </AuthLayout>
  )
}
