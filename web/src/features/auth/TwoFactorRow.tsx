import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { qk, useForgetBrowsers, useSetTwoFactor } from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
import { useT } from '@/i18n'
import type { TwoFactorChallenge } from '@/lib/types'
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  SecretInput,
  Switch,
  toast,
} from '@/components/ui'
import { SettingRow } from '@/features/common'
import { TwoFactorWait } from './TwoFactorWait'
import { PasskeyConfirm } from './TwoStepMethods'
/** Two-step sign-in: turning it on waits for an approval in Telegram (a broken bridge cannot lock anybody out);
 *  turning it off asks for the current password (a signed-in browser alone cannot remove it). */
export function TwoFactorRow({ on, id = 'tg-2fa', label }: { on: boolean; id?: string; label?: string }) {
  const t = useT()
  const qc = useQueryClient()
  const setTwo = useSetTwoFactor()
  const forget = useForgetBrowsers()
  const [challenge, setChallenge] = React.useState<TwoFactorChallenge | null>(null)
  const [askOff, setAskOff] = React.useState(false)
  const [password, setPassword] = React.useState('')
  const [pwError, setPwError] = React.useState<string>()
  const closeOff = () => {
    setAskOff(false)
    setPassword('')
    setPwError(undefined)
  }
  const toggle = (v: boolean) => {
    if (!v) return setAskOff(true)
    setTwo.mutate(
      { enabled: true },
      {
        onSuccess: (r) => {
          if (r.two_factor) setChallenge(r.two_factor)
        },
        onError: (e) => toast.error(errorMessage(e)),
      },
    )
  }
  const turnOff = (viaPasskey = false) => {
    if (!password && !viaPasskey) return setPwError(t('security.currentRequired'))
    setTwo.mutate(
      { enabled: false, password: viaPasskey ? '' : password },
      {
        onSuccess: closeOff,
        onError: (e) => setPwError(isApiError(e, 'bad_password') ? t('security.currentWrong') : errorMessage(e)),
      },
    )
  }
  return (
    <>
      <SettingRow label={label || t('twofa.setting')} description={t('twofa.settingDesc')} htmlFor={id}>
        <div className="flex items-center gap-2">
          {on && (
            <Button variant="ghost" size="sm" loading={forget.isPending} onClick={() => forget.mutate(undefined, { onSuccess: () => toast.success(t('twofa.forgotten')) })}>
              {t('twofa.forget')}
            </Button>
          )}
          <Switch id={id} checked={on || !!challenge} disabled={setTwo.isPending} onCheckedChange={toggle} />
        </div>
      </SettingRow>
      <Dialog open={askOff} onOpenChange={(o) => !o && closeOff()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('twofa.offTitle')}</DialogTitle>
            <DialogDescription>{t('twofa.offDesc')}</DialogDescription>
          </DialogHeader>
          <form
            className="grid gap-4"
            noValidate
            onSubmit={(e) => {
              e.preventDefault()
              turnOff()
            }}
          >
            <FormField label={t('security.current')} error={pwError}>
              <SecretInput value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus />
            </FormField>
            <DialogFooter className="gap-2 sm:justify-between">
              <PasskeyConfirm onDone={() => turnOff(true)} onError={setPwError} />
              <div className="flex gap-2">
                <Button type="button" variant="outline" onClick={closeOff}>
                  {t('common.cancel')}
                </Button>
                <Button type="submit" variant="destructive" loading={setTwo.isPending}>
                  {t('twofa.offConfirm')}
                </Button>
              </div>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={!!challenge} onOpenChange={(o) => !o && setChallenge(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('twofa.enableTitle')}</DialogTitle>
            <DialogDescription>{t('twofa.enableDesc')}</DialogDescription>
          </DialogHeader>
          {challenge && (
            <TwoFactorWait
              challenge={challenge}
              onDone={(err) => {
                setChallenge(null)
                qc.invalidateQueries({ queryKey: qk.telegram.all })
                qc.invalidateQueries({ queryKey: qk.authMethods })
                if (err === null) toast.success(t('twofa.enabled'))
                else if (err) toast.error(err)
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
