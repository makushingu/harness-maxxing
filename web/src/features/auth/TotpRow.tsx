import * as React from 'react'
import { useNewRecoveryCodes, useSecondFactor, useTotpBegin, useTotpConfirm, useTotpOff } from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
import { useT } from '@/i18n'
import type { TotpEnrol } from '@/lib/types'
import { Button, CodeBlock, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, FormField, Input, SecretInput, Sensitive, Switch, toast } from '@/components/ui'
import { QRCode } from '@/components/ui/qr-code'
import { SettingRow } from '@/features/common'

type Step = null | 'password' | 'scan' | 'off' | 'renew'

/** The authenticator app as a second sign-in step, and the recovery codes: turning the app on is password ->
 *  secret (QR + text) -> one code typed; turning it off asks for the password and a code. */
export function TotpRow() {
  const t = useT()
  const { data: state } = useSecondFactor()
  const begin = useTotpBegin()
  const confirm = useTotpConfirm()
  const off = useTotpOff()
  const renew = useNewRecoveryCodes()
  const [step, setStep] = React.useState<Step>(null)
  const [password, setPassword] = React.useState('')
  const [code, setCode] = React.useState('')
  const [error, setError] = React.useState<string>()
  const [enrol, setEnrol] = React.useState<TotpEnrol | null>(null)
  const [codes, setCodes] = React.useState<string[] | null>(null)
  const close = () => {
    setStep(null)
    setPassword('')
    setCode('')
    setError(undefined)
    setEnrol(null)
  }
  const fail = (e: unknown) =>
    setError(isApiError(e, 'bad_password') ? t('security.currentWrong') : isApiError(e, 'bad_code') ? t('security.appBadCode') : errorMessage(e))
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(undefined)
    if (step !== 'scan' && !password) return setError(t('security.currentRequired'))
    if (step === 'password')
      begin.mutate(password, {
        onSuccess: (r) => {
          setEnrol(r)
          setPassword('')
          setStep('scan')
        },
        onError: fail,
      })
    else if (step === 'scan')
      confirm.mutate(code, {
        onSuccess: (r) => {
          close()
          setCodes(r.recovery_codes)
          toast.success(t('security.appOn'))
        },
        onError: (err) => {
          setCode('')
          fail(err)
        },
      })
    else if (step === 'off')
      off.mutate(
        { password, code },
        {
          onSuccess: () => {
            close()
            toast.success(t('security.appOff'))
          },
          onError: fail,
        },
      )
    else if (step === 'renew')
      renew.mutate(password, {
        onSuccess: (r) => {
          close()
          setCodes(r.recovery_codes)
        },
        onError: fail,
      })
  }
  const busy = begin.isPending || confirm.isPending || off.isPending || renew.isPending
  const codeField = (label: string) => (
    <FormField label={label} error={step === 'scan' || !isPwError(error, t) ? error : undefined}>
      <Input value={code} onChange={(e) => setCode(e.target.value.replace(/[^a-z\d -]/gi, '').slice(0, 24))} autoCapitalize="off" autoCorrect="off" spellCheck={false} autoComplete="one-time-code" placeholder="123456" className="font-mono tracking-widest" autoFocus={step === 'scan'} />
    </FormField>
  )
  const passwordField = (
    <FormField label={t('security.current')} error={isPwError(error, t) || step !== 'off' ? error : undefined}>
      <SecretInput value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus />
    </FormField>
  )
  return (
    <>
      <SettingRow label={t('security.app')} description={t('security.appDesc')} htmlFor="sec-totp">
        <Switch id="sec-totp" checked={!!state?.totp || step === 'password' || step === 'scan'} disabled={!state} onCheckedChange={(v) => setStep(v ? 'password' : 'off')} />
      </SettingRow>
      {(state?.totp || state?.telegram) && (
        <SettingRow label={t('security.recovery')} description={t('security.recoveryDesc', { n: state.recovery_left })}>
          <Button variant="outline" size="sm" onClick={() => setStep('renew')}>
            {t('security.recoveryNew')}
          </Button>
        </SettingRow>
      )}
      <Dialog open={!!step} onOpenChange={(o) => !o && close()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(step === 'off' ? 'security.appOffTitle' : step === 'renew' ? 'security.recovery' : 'security.app')}</DialogTitle>
            <DialogDescription>{t(step === 'off' ? 'security.appOffDesc' : step === 'renew' ? 'security.recoveryNewDesc' : step === 'scan' ? 'security.appScan' : 'security.appPwDesc')}</DialogDescription>
          </DialogHeader>
          <form className="grid gap-4" noValidate onSubmit={submit}>
            {step === 'scan' && enrol ? (
              <>
                <div className="grid justify-items-center gap-3">
                  <Sensitive placeholder={<div className="size-44 rounded-lg bg-muted" />}>
                    <QRCode value={enrol.uri} className="size-44 p-1" label={t('security.app')} />
                  </Sensitive>
                  <a href={enrol.uri} className="text-[13px] font-medium text-primary hover:underline">
                    {t('security.appOpen')}
                  </a>
                </div>
                <FormField label={t('security.appKey')}>
                  <Sensitive placeholder={<div className="h-9 rounded-lg bg-muted" />}>
                    <CodeBlock inline code={enrol.secret.replace(/(.{4})/g, '$1 ').trim()} />
                  </Sensitive>
                </FormField>
                {codeField(t('security.appCode'))}
              </>
            ) : (
              <>
                {passwordField}
                {step === 'off' && codeField(t('security.appOffCode'))}
              </>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={close}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" variant={step === 'off' ? 'destructive' : 'default'} loading={busy}>
                {t(step === 'off' ? 'twofa.offConfirm' : step === 'scan' ? 'security.appTurnOn' : 'security.appContinue')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={!!codes} onOpenChange={(o) => !o && setCodes(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('security.recoveryTitle')}</DialogTitle>
            <DialogDescription>{t('security.recoverySave')}</DialogDescription>
          </DialogHeader>
          {codes && <CodeBlock code={codes.join('\n')} />}
          <DialogFooter>
            <Button onClick={() => setCodes(null)}>{t('security.recoverySaved')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

/** The error belongs to the password field (not to the code one). */
function isPwError(error: string | undefined, t: ReturnType<typeof useT>) {
  return !!error && (error === t('security.currentWrong') || error === t('security.currentRequired'))
}
