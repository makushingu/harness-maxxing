import * as React from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { ArrowRight, ShieldCheck } from 'lucide-react'
import { useSetup } from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
import { useT } from '@/i18n'
import { Button, CodeBlock, FormField, Input } from '@/components/ui'
import { AuthLayout } from './AuthLayout'
import { NewPasswordFields, validatePasswords } from './PasswordFields'

export default function SetupPage() {
  const t = useT()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const urlToken = params.get('token') || ''
  const [token, setToken] = React.useState(urlToken)
  const [password, setPassword] = React.useState('')
  const [confirm, setConfirm] = React.useState('')
  const [errors, setErrors] = React.useState<{ password?: string; confirm?: string; token?: string; form?: string }>({})
  const setup = useSetup()

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const v = validatePasswords(t, password, confirm)
    if (!token.trim()) Object.assign(v, { token: t('setup.tokenRequired') })
    setErrors(v)
    if (Object.keys(v).length) return
    setup.mutate(
      { token: token.trim(), password },
      {
        onSuccess: () => navigate('/welcome', { replace: true }),
        onError: (err) =>
          setErrors(isApiError(err, 'bad_token') ? { token: t('setup.badToken') } : isApiError(err, 'invalid') ? { password: errorMessage(err) } : { form: errorMessage(err) }),
      },
    )
  }

  return (
    <AuthLayout
      title={t('setup.title')}
      subtitle={t('setup.subtitle')}
      footer={
        <span className="inline-flex items-center gap-1.5">
          <ShieldCheck className="size-3.5" /> {t('setup.footer')}
        </span>
      }
    >
      <form onSubmit={submit} className="grid gap-5" noValidate>
        {!urlToken && (
          <FormField label={t('setup.token')} error={errors.token} hint={t('setup.tokenHint')}>
            <Input value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" spellCheck={false} className="font-mono" />
          </FormField>
        )}
        {urlToken && errors.token && (
          <div className="grid gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-[13px]">
            <p className="text-destructive">{errors.token}</p>
            <p className="text-muted-foreground">{t('setup.newLink')}</p>
            <CodeBlock inline code="maxxing setup-link" />
          </div>
        )}
        <NewPasswordFields password={password} confirm={confirm} onPassword={setPassword} onConfirm={setConfirm} errors={errors} autoFocus={!!urlToken} />
        {errors.form && (
          <p role="alert" className="text-[13px] text-destructive">
            {errors.form}
          </p>
        )}
        <Button type="submit" size="lg" loading={setup.isPending} className="w-full">
          {t('setup.submit')} <ArrowRight />
        </Button>
      </form>
    </AuthLayout>
  )
}
