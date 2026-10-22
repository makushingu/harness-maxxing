import * as React from 'react'
import { Link } from 'react-router'
import { LogOut } from 'lucide-react'
import { useChangePassword, useLogout, useTelegram } from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
import { useT } from '@/i18n'
import { Button, FormField, SecretInput, toast } from '@/components/ui'
import { NewPasswordFields, validatePasswords } from '@/pages/auth/PasswordFields'
import { Callout } from '@/features/common'
import { TwoFactorRow } from '@/features/auth/TwoFactorRow'
import { SettingsCard, SectionStack } from './ui'

export function SecuritySection() {
  const t = useT()
  const change = useChangePassword()
  const logout = useLogout()
  const { data: tg } = useTelegram()
  const [current, setCurrent] = React.useState('')
  const [pw, setPw] = React.useState('')
  const [confirmPw, setConfirmPw] = React.useState('')
  const [errors, setErrors] = React.useState<{ current?: string; password?: string; confirm?: string }>({})
  return (
    <SectionStack>
      <SettingsCard title={t('security.change')} description={t('security.changeDesc')}>
        <form
          className="grid max-w-md gap-5"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            const v: typeof errors = validatePasswords(t, pw, confirmPw)
            if (!current) v.current = t('security.currentRequired')
            setErrors(v)
            if (Object.keys(v).length) return
            change.mutate(
              { current, new: pw },
              {
                onSuccess: () => {
                  setCurrent('')
                  setPw('')
                  setConfirmPw('')
                  toast.success(t('security.changed'), t('security.changedDesc'))
                },
                onError: (err) =>
                  setErrors(isApiError(err, 'bad_password') ? { current: t('security.currentWrong') } : { password: errorMessage(err) }),
              },
            )
          }}
        >
          <FormField label={t('security.current')} error={errors.current}>
            <SecretInput value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
          </FormField>
          <NewPasswordFields password={pw} confirm={confirmPw} onPassword={setPw} onConfirm={setConfirmPw} errors={errors} />
          <div>
            <Button type="submit" loading={change.isPending}>
              {t('security.update')}
            </Button>
          </div>
        </form>
      </SettingsCard>
      <SettingsCard title={t('twofa.setting')}>
        {tg?.chat ? (
          <TwoFactorRow on={!!tg.settings.two_factor} id="sec-2fa" />
        ) : (
          <p className="text-sm text-muted-foreground">
            {t('twofa.needTelegram')}{' '}
            <Link to="/settings/telegram" className="font-medium text-primary hover:underline">
              {t('twofa.linkTelegram')}
            </Link>
          </p>
        )}
      </SettingsCard>
      <SettingsCard title={t('security.sessions')} description={t('security.sessionsDesc')}>
        <div className="grid gap-4">
          <Callout tone="info">{t('security.everywhere')}</Callout>
          <div>
            <Button variant="outline" onClick={() => logout.mutate()} loading={logout.isPending}>
              <LogOut /> {t('auth.signOut')}
            </Button>
          </div>
        </div>
      </SettingsCard>
    </SectionStack>
  )
}
