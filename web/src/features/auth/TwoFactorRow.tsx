import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { qk, useForgetBrowsers, useSetTwoFactor } from '@/lib/queries'
import { useT } from '@/i18n'
import type { TwoFactorChallenge } from '@/lib/types'
import { Button, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, Switch, toast } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { TwoFactorWait } from './TwoFactorWait'
/** Two-step sign-in: turning it on waits for an approval in Telegram (a broken bridge cannot lock anybody out). */
export function TwoFactorRow({ on, id = 'tg-2fa' }: { on: boolean; id?: string }) {
  const t = useT()
  const qc = useQueryClient()
  const setTwo = useSetTwoFactor()
  const forget = useForgetBrowsers()
  const [challenge, setChallenge] = React.useState<TwoFactorChallenge | null>(null)
  const toggle = (v: boolean) =>
    setTwo.mutate(v, {
      onSuccess: (r) => {
        if (r.two_factor) setChallenge(r.two_factor)
      },
    })
  return (
    <>
      <SettingRow label={t('twofa.setting')} description={t('twofa.settingDesc')} htmlFor={id}>
        <div className="flex items-center gap-2">
          {on && (
            <Button variant="ghost" size="sm" loading={forget.isPending} onClick={() => forget.mutate(undefined, { onSuccess: () => toast.success(t('twofa.forgotten')) })}>
              {t('twofa.forget')}
            </Button>
          )}
          <Switch id={id} checked={on || !!challenge} disabled={setTwo.isPending} onCheckedChange={toggle} />
        </div>
      </SettingRow>
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
