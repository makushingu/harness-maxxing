import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Copy, Download, KeyRound, Plus, Smartphone, Trash2 } from 'lucide-react'
import { passkeyAdd, qk, passkeyAddOptions, useNewRecoveryCodes, usePasskeyRemove, useTotpConfirm, useTotpOff, useTotpSetup, useTwoFactorMethods } from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
import { fmtRelative } from '@/lib/format'
import { copyText } from '@/lib/utils'
import { createPasskey, passkeyCancelled, passkeysSupported } from '@/lib/webauthn'
import { useLang, useT } from '@/i18n'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, FormField, Input, SecretInput, Skeleton, toast } from '@/components/ui'
import { QRCode } from '@/components/ui/qr-code'
import { Callout, SettingRow } from '@/features/common'
import type { TotpSetup } from '@/lib/types'

type Ask = { kind: 'totp-on' | 'totp-off' | 'passkey-add' | 'codes' } | { kind: 'passkey-remove'; id: string; name: string }

/** Settings -> Security: authenticator app, passkeys and recovery codes. Every change asks for the current password
 *  (a signed-in browser alone cannot change the second step). */
export function TwoFactorAppsCard() {
  const t = useT()
  const lang = useLang()
  const { data: m } = useTwoFactorMethods()
  const [ask, setAsk] = React.useState<Ask | null>(null)
  const [totp, setTotp] = React.useState<TotpSetup | null>(null)
  const [codes, setCodes] = React.useState<string[] | null>(null)
  const supported = passkeysSupported()
  if (!m) return <Skeleton className="h-40" />
  const hasOne = m.totp || m.passkeys.length > 0
  return (
    <div className="grid gap-4" data-tour="twofa-apps">
      <SettingRow label={t('twofa.app')} description={t('twofa.appDesc')}>
        {m.totp ? (
          <Button variant="outline" size="sm" onClick={() => setAsk({ kind: 'totp-off' })}>
            {t('twofa.remove')}
          </Button>
        ) : (
          <Button variant="outline" size="sm" onClick={() => setAsk({ kind: 'totp-on' })}>
            <Smartphone /> {t('twofa.appSetup')}
          </Button>
        )}
      </SettingRow>
      <SettingRow label={t('twofa.passkeys')} description={supported ? t('twofa.passkeysDesc') : t('twofa.passkeysHttps')}>
        <Button variant="outline" size="sm" disabled={!supported} onClick={() => setAsk({ kind: 'passkey-add' })}>
          <Plus /> {t('twofa.passkeyAdd')}
        </Button>
      </SettingRow>
      {m.passkeys.length > 0 && (
        <ul className="grid gap-2">
          {m.passkeys.map((k) => (
            <li key={k.id} className="flex items-center gap-3 rounded-lg border px-3 py-2 text-sm">
              <KeyRound className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{k.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {k.rp_id}
                  {k.rp_id !== m.rp_id && ` · ${t('twofa.passkeyOtherAddress')}`} ·{' '}
                  {k.last_used ? t('twofa.passkeyUsed', { when: fmtRelative(k.last_used, lang) }) : t('twofa.passkeyNeverUsed')}
                </p>
              </div>
              <Button variant="ghost" size="icon" aria-label={t('twofa.remove')} onClick={() => setAsk({ kind: 'passkey-remove', id: k.id, name: k.name })}>
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}
      {hasOne && (
        <SettingRow label={t('twofa.recovery')} description={t('twofa.recoveryDesc', { n: m.recovery_left })}>
          <Button variant="outline" size="sm" onClick={() => setAsk({ kind: 'codes' })}>
            {t('twofa.recoveryNew')}
          </Button>
        </SettingRow>
      )}
      {hasOne && m.recovery_left <= 2 && <Callout tone="warning">{t('twofa.recoveryLow', { n: m.recovery_left })}</Callout>}
      <PasswordDialog ask={ask} onClose={() => setAsk(null)} onTotp={setTotp} onCodes={setCodes} />
      <TotpDialog setup={totp} onClose={() => setTotp(null)} onCodes={setCodes} />
      <CodesDialog codes={codes} onClose={() => setCodes(null)} />
    </div>
  )
}

/** The current password, then the action of `ask`. */
function PasswordDialog({ ask, onClose, onTotp, onCodes }: { ask: Ask | null; onClose: () => void; onTotp: (s: TotpSetup) => void; onCodes: (c: string[]) => void }) {
  const t = useT()
  const [password, setPassword] = React.useState('')
  const [name, setName] = React.useState('')
  const [error, setError] = React.useState<string>()
  const [busy, setBusy] = React.useState(false)
  const setup = useTotpSetup()
  const off = useTotpOff()
  const remove = usePasskeyRemove()
  const newCodes = useNewRecoveryCodes()
  const qc = useQueryClient()
  React.useEffect(() => {
    setPassword('')
    setName('')
    setError(undefined)
  }, [ask])
  if (!ask) return null
  const texts = {
    'totp-on': [t('twofa.appSetup'), t('twofa.appSetupDesc'), t('common.continue')],
    'totp-off': [t('twofa.appOffTitle'), t('twofa.appOffDesc'), t('twofa.remove')],
    'passkey-add': [t('twofa.passkeyAdd'), t('twofa.passkeyAddDesc'), t('common.continue')],
    'passkey-remove': [t('twofa.passkeyRemoveTitle', { name: ask.kind === 'passkey-remove' ? ask.name : '' }), t('twofa.passkeyRemoveDesc'), t('twofa.remove')],
    codes: [t('twofa.recoveryNew'), t('twofa.recoveryNewDesc'), t('common.continue')],
  }[ask.kind]
  const danger = ask.kind === 'totp-off' || ask.kind === 'passkey-remove'
  const run = async () => {
    if (!password) return setError(t('security.currentRequired'))
    setBusy(true)
    setError(undefined)
    try {
      if (ask.kind === 'totp-on') onTotp(await setup.mutateAsync({ password }))
      else if (ask.kind === 'totp-off') await off.mutateAsync({ password })
      else if (ask.kind === 'passkey-remove') await remove.mutateAsync({ id: ask.id, password })
      else if (ask.kind === 'codes') {
        const r = await newCodes.mutateAsync({ password })
        if (r.recovery_codes) onCodes(r.recovery_codes)
      } else {
        const { setup: sid, options } = await passkeyAddOptions(password)
        const credential = await createPasskey(options)
        const r = await passkeyAdd(sid, credential, name)
        void qc.invalidateQueries({ queryKey: qk.twoFactorMethods })
        toast.success(t('twofa.passkeyAdded'))
        if (r.recovery_codes) onCodes(r.recovery_codes)
      }
      onClose()
    } catch (e) {
      setError(isApiError(e, 'bad_password') ? t('security.currentWrong') : passkeyCancelled(e) ? t('twofa.passkeyCancelled') : errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{texts[0]}</DialogTitle>
          <DialogDescription>{texts[1]}</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            void run()
          }}
        >
          {ask.kind === 'passkey-add' && (
            <FormField label={t('twofa.passkeyName')}>
              <Input value={name} onChange={(e) => setName(e.target.value.slice(0, 60))} placeholder={t('twofa.passkeyNamePlaceholder')} />
            </FormField>
          )}
          <FormField label={t('security.current')} error={error}>
            <SecretInput value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus={ask.kind !== 'passkey-add'} />
          </FormField>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" variant={danger ? 'destructive' : 'default'} loading={busy}>
              {texts[2]}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Scan the QR code (or type the key), then the first code turns it on. */
function TotpDialog({ setup, onClose, onCodes }: { setup: TotpSetup | null; onClose: () => void; onCodes: (c: string[]) => void }) {
  const t = useT()
  const [code, setCode] = React.useState('')
  const [error, setError] = React.useState<string>()
  const confirm = useTotpConfirm()
  React.useEffect(() => {
    setCode('')
    setError(undefined)
  }, [setup])
  if (!setup) return null
  const key = setup.secret.replace(/(.{4})/g, '$1 ').trim()
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('twofa.appScan')}</DialogTitle>
          <DialogDescription>{t('twofa.appScanDesc')}</DialogDescription>
        </DialogHeader>
        <div className="grid justify-items-center gap-3">
          <QRCode value={setup.uri} className="size-48" label={t('twofa.appScan')} />
          <details className="w-full text-[13px] text-muted-foreground">
            <summary className="cursor-pointer list-none text-center hover:text-foreground pointer-coarse:min-h-10">{t('twofa.appNoScan')}</summary>
            <p className="mt-2 break-all text-center font-mono text-foreground">{key}</p>
          </details>
        </div>
        <form
          className="grid gap-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            const c = code.replace(/\D/g, '')
            if (c.length !== 6) return setError(t('twofa.codeLength'))
            confirm.mutate(
              { setup: setup.setup, code: c },
              {
                onSuccess: (r) => {
                  toast.success(t('twofa.appOn'))
                  onClose()
                  if (r.recovery_codes) onCodes(r.recovery_codes)
                },
                onError: (err) => setError(isApiError(err, 'bad_code') ? t('twofa.appBadFirstCode') : errorMessage(err)),
              },
            )
          }}
        >
          <FormField label={t('twofa.appCode')} error={error}>
            <Input value={code} onChange={(e) => setCode(e.target.value.replace(/[^\d ]/g, '').slice(0, 7))} inputMode="numeric" autoComplete="one-time-code" placeholder="123456" className="font-mono tracking-widest" autoFocus />
          </FormField>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={confirm.isPending}>
              {t('twofa.appTurnOn')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Shown once: the recovery codes, to copy or download. */
function CodesDialog({ codes, onClose }: { codes: string[] | null; onClose: () => void }) {
  const t = useT()
  if (!codes) return null
  const text = codes.join('\n')
  const download = () => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([`${t('twofa.recovery')} - Harness Maxxing\n\n${text}\n`], { type: 'text/plain' }))
    a.download = 'harness-maxxing-recovery-codes.txt'
    a.click()
    setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  }
  return (
    <Dialog open onOpenChange={() => undefined}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('twofa.recoverySave')}</DialogTitle>
          <DialogDescription>{t('twofa.recoverySaveDesc')}</DialogDescription>
        </DialogHeader>
        <ul className="grid grid-cols-2 gap-x-6 gap-y-1.5 rounded-lg border bg-muted/40 p-4 font-mono text-sm">
          {codes.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => void copyText(text).then((ok) => ok && toast.success(t('twofa.recoveryCopied')))}>
            <Copy /> {t('common.copy')}
          </Button>
          <Button variant="outline" onClick={download}>
            <Download /> {t('twofa.recoveryDownload')}
          </Button>
          <Button onClick={onClose}>{t('twofa.recoverySaved')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
