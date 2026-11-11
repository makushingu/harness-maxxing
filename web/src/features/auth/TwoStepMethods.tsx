import * as React from 'react'
import { Download, Fingerprint, KeyRound, Pencil, Plus, Smartphone, Trash2 } from 'lucide-react'
import { reauthWithPasskey, useAddPasskey, useAuthMethods, useNewRecoveryCodes, useRemovePasskey, useRenamePasskey, useSetPasskeyLogin, useTotpConfirm, useTotpRemove, useTotpSetup } from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
import { passkeyCancelled, passkeysSupported, signalAccepted, signalSupported, signalUnknown } from '@/lib/webauthn'
import { fmtDate } from '@/lib/format'
import { useLang, useT } from '@/i18n'
import type { AuthMethods, Passkey, TotpSetup } from '@/lib/types'
import {
  Badge,
  Button,
  CopyButton,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  SecretInput,
  Switch,
  toast,
} from '@/components/ui'
import { QRCode } from '@/components/ui/qr-code'
import { resetPasskeyOffer } from './PasskeyOffer'
import { Callout, SettingRow } from '@/features/common'

/** Authenticator app (TOTP), passkeys and recovery codes: the second steps that do not need Telegram. */
export function TwoStepMethods() {
  const { data: m } = useAuthMethods()
  const [codes, setCodes] = React.useState<string[] | null>(null)
  // the password manager hides passkeys removed here (or from another browser): Signal API
  const accepted = m && m.passkey_here.ok ? JSON.stringify([m.passkey_here.rp_id, m.passkey_user, m.passkeys.filter((p) => m.passkey_here.ok && p.rp_id === m.passkey_here.rp_id).map((p) => p.id)]) : ''
  React.useEffect(() => {
    if (!accepted) return
    const [rp_id, user, ids] = JSON.parse(accepted) as [string, string | null, string[]]
    signalAccepted({ rp_id, user, ids })
  }, [accepted])
  if (!m) return null
  return (
    <>
      <AppRow m={m} onCodes={setCodes} />
      <PasskeyRows m={m} onCodes={setCodes} />
      {(m.totp.on || m.passkeys.length > 0) && <RecoveryRow left={m.recovery_left} onCodes={setCodes} />}
      <RecoveryCodesDialog codes={codes} onClose={() => setCodes(null)} />
    </>
  )
}

// ---- authenticator app ----------------------------------------------------------------------
function AppRow({ m, onCodes }: { m: AuthMethods; onCodes: (c: string[]) => void }) {
  const t = useT()
  const setup = useTotpSetup()
  const remove = useTotpRemove()
  const [pending, setPending] = React.useState<TotpSetup | null>(null)
  const [askOff, setAskOff] = React.useState(false)
  return (
    <>
      <SettingRow
        label={
          <span className="inline-flex items-center gap-2">
            <Smartphone className="size-4 text-muted-foreground" /> {t('twofa.app')}
            {m.totp.on && <Badge variant="success">{t('twofa.on')}</Badge>}
          </span>
        }
        description={t('twofa.appDesc')}
      >
        {m.totp.on ? (
          <Button variant="outline" size="sm" onClick={() => setAskOff(true)}>
            {t('twofa.remove')}
          </Button>
        ) : (
          <Button size="sm" loading={setup.isPending} onClick={() => setup.mutate(undefined, { onSuccess: setPending, onError: (e) => toast.error(errorMessage(e)) })}>
            {t('twofa.appSetup')}
          </Button>
        )}
      </SettingRow>
      <TotpSetupDialog
        setup={pending}
        onClose={(codes) => {
          setPending(null)
          if (codes?.length) onCodes(codes)
        }}
      />
      <PasswordDialog
        open={askOff}
        title={t('twofa.appOffTitle')}
        description={t('twofa.appOffDesc')}
        confirm={t('twofa.remove')}
        busy={remove.isPending}
        onClose={() => setAskOff(false)}
        onConfirm={(password, fail) =>
          remove.mutate(password, {
            onSuccess: () => {
              setAskOff(false)
              toast.success(t('twofa.appRemoved'))
            },
            onError: fail,
          })
        }
      />
    </>
  )
}

export function TotpSetupDialog({ setup, onClose }: { setup: TotpSetup | null; onClose: (codes?: string[]) => void }) {
  const t = useT()
  const confirm = useTotpConfirm()
  const [code, setCode] = React.useState('')
  const [error, setError] = React.useState<string>()
  React.useEffect(() => {
    setCode('')
    setError(undefined)
  }, [setup])
  const grouped = setup?.secret.replace(/(.{4})/g, '$1 ').trim() || ''
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const c = code.replace(/\s/g, '')
    if (!/^\d{6}$/.test(c)) return setError(t('twofa.codeLength'))
    confirm.mutate(c, {
      onSuccess: (r) => {
        toast.success(t('twofa.appAdded'))
        onClose(r.recovery_codes)
      },
      onError: (err) => {
        setCode('')
        setError(isApiError(err, 'bad_code') ? t('twofa.appBadCode') : isApiError(err, 'expired') ? t('twofa.setupExpired') : errorMessage(err))
      },
    })
  }
  return (
    <Dialog open={!!setup} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('twofa.appSetupTitle')}</DialogTitle>
          <DialogDescription>{t('twofa.appSetupDesc')}</DialogDescription>
        </DialogHeader>
        {setup && (
          <form className="grid gap-4" noValidate onSubmit={submit}>
            <div className="flex flex-wrap items-center gap-4">
              <a href={setup.uri} aria-label={t('twofa.appOpen')} className="shrink-0">
                <QRCode value={setup.uri} className="size-44" label={t('twofa.appQr')} />
              </a>
              <div className="grid min-w-0 flex-1 gap-1.5 text-[13px]">
                <p className="text-muted-foreground">{t('twofa.appManual')}</p>
                <div className="flex items-center gap-1">
                  <code className="rounded bg-muted px-2 py-1 font-mono text-[12px] break-all">{grouped}</code>
                  <CopyButton text={setup.secret} />
                </div>
                <p className="text-muted-foreground">{t('twofa.appManualHint')}</p>
              </div>
            </div>
            <FormField label={t('twofa.appCode')} error={error}>
              <Input value={code} onChange={(e) => setCode(e.target.value.replace(/[^\d ]/g, '').slice(0, 7))} inputMode="numeric" autoComplete="one-time-code" placeholder="123456" className="font-mono tracking-widest" autoFocus />
            </FormField>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onClose()}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" loading={confirm.isPending}>
                {t('twofa.appConfirm')}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

// ---- passkeys -----------------------------------------------------------------------------------
function PasskeyRows({ m, onCodes }: { m: AuthMethods; onCodes: (c: string[]) => void }) {
  const t = useT()
  const lang = useLang()
  const add = useAddPasskey()
  const remove = useRemovePasskey()
  const [rename, setRename] = React.useState<Passkey | null>(null)
  const [drop, setDrop] = React.useState<Passkey | null>(null)
  const [gone, setGone] = React.useState<{ passkey: Passkey; signaled: boolean } | null>(null)
  const here = m.passkey_here
  const supported = passkeysSupported()
  // one click: the browser (or the password manager) asks at once; the server names it after the provider
  const create = () =>
    add.mutate('', {
      onSuccess: (r) => {
        resetPasskeyOffer()
        toast.success(t('twofa.passkeyAdded', { name: r.passkey.name }))
        if (r.recovery_codes?.length) onCodes(r.recovery_codes)
      },
      onError: (err) => {
        if (passkeyCancelled(err)) return
        if (err instanceof DOMException && err.name === 'InvalidStateError') return toast.error(t('twofa.passkeyExists'))
        toast.error(isApiError(err, 'bad_passkey') ? t('twofa.passkeyRefused') : errorMessage(err))
      },
    })
  return (
    <>
      <SettingRow
        label={
          <span className="inline-flex items-center gap-2">
            <Fingerprint className="size-4 text-muted-foreground" /> {t('twofa.passkeys')}
            {m.passkeys.length > 0 && <Badge variant="success">{m.passkeys.length}</Badge>}
          </span>
        }
        description={t('twofa.passkeysDesc')}
      >
        <Button
          size="sm"
          variant={m.passkeys.length ? 'outline' : 'default'}
          disabled={!here.ok || !supported}
          loading={add.isPending}
          onClick={create}
        >
          <Plus /> {t('twofa.passkeyAdd')}
        </Button>
      </SettingRow>
      {!here.ok ? (
        <Callout tone="info">{here.reason === 'ip' ? t('twofa.passkeyNeedsName') : t('twofa.passkeyNeedsHttps')}</Callout>
      ) : (
        !supported && <Callout tone="info">{t('twofa.passkeyUnsupported')}</Callout>
      )}
      {m.passkeys.length > 0 && (
        <ul className="grid gap-1.5 pb-2">
          {m.passkeys.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2 text-sm">
              <KeyRound className="size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate font-medium">{p.name}</span>
              <span className="text-[12px] text-muted-foreground">
                {p.rp_id}
                {' · '}
                {p.last_used ? t('twofa.passkeyUsed', { date: fmtDate(p.last_used, lang, undefined, { timeStyle: undefined }) }) : t('twofa.passkeyNever')}
              </span>
              <span className="flex gap-1">
                <Button variant="ghost" size="icon-sm" aria-label={t('twofa.rename')} title={t('twofa.rename')} onClick={() => setRename(p)}>
                  <Pencil />
                </Button>
                <Button variant="ghost" size="icon-sm" aria-label={t('twofa.remove')} title={t('twofa.remove')} onClick={() => setDrop(p)}>
                  <Trash2 />
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {m.passkeys.length > 0 && <PasskeyLoginRow on={m.passkey_login} />}
      <RenameDialog passkey={rename} onClose={() => setRename(null)} />
      <Dialog open={!!gone} onOpenChange={(o) => !o && setGone(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('twofa.goneTitle', { name: gone?.passkey.name || '' })}</DialogTitle>
            <DialogDescription>{gone?.signaled ? t('twofa.goneSignaled') : t('twofa.goneManual')}</DialogDescription>
          </DialogHeader>
          <ol className="grid list-decimal gap-1.5 pl-5 text-sm">
            <li>{t('twofa.goneStep1')}</li>
            <li>{t('twofa.goneStep2', { host: gone?.passkey.rp_id || '' })}</li>
            <li>{t('twofa.goneStep3')}</li>
          </ol>
          <DialogFooter>
            <Button onClick={() => setGone(null)}>{t('common.ok')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <PasswordDialog
        open={!!drop}
        title={t('twofa.passkeyOffTitle', { name: drop?.name || '' })}
        description={t('twofa.passkeyOffDesc')}
        confirm={t('twofa.remove')}
        busy={remove.isPending}
        onClose={() => setDrop(null)}
        onConfirm={(password, fail) =>
          drop &&
          remove.mutate(
            { id: drop.id, password },
            {
              onSuccess: () => {
                // the server forgot it; the password manager still holds it: tell it (Signal API) when the browser can,
                // and always say where to delete it by hand
                const signaled = signalSupported()
                if (signaled) signalUnknown(drop.rp_id, drop.id)
                setGone({ passkey: drop, signaled })
                setDrop(null)
              },
              onError: fail,
            },
          )
        }
      />
    </>
  )
}

/** Sign-in with a passkey alone: on by default with a passkey; off at once, back on with the current password. */
function PasskeyLoginRow({ on }: { on: boolean }) {
  const t = useT()
  const set = useSetPasskeyLogin()
  const [ask, setAsk] = React.useState(false)
  return (
    <>
      <SettingRow label={t('twofa.passkeyLogin')} description={t('twofa.passkeyLoginDesc')} htmlFor="sec-passkey-login">
        <Switch
          id="sec-passkey-login"
          checked={on}
          disabled={set.isPending}
          onCheckedChange={(v) => (v ? setAsk(true) : set.mutate({ enabled: false }, { onError: (e) => toast.error(errorMessage(e)) }))}
        />
      </SettingRow>
      <PasswordDialog
        open={ask}
        title={t('twofa.passkeyLoginOnTitle')}
        description={t('twofa.passkeyLoginOnDesc')}
        confirm={t('twofa.appConfirm')}
        destructive={false}
        busy={set.isPending}
        onClose={() => setAsk(false)}
        onConfirm={(password, fail) => set.mutate({ enabled: true, password }, { onSuccess: () => setAsk(false), onError: fail })}
      />
    </>
  )
}

function RenameDialog({ passkey, onClose }: { passkey: Passkey | null; onClose: () => void }) {
  const t = useT()
  const rename = useRenamePasskey()
  const [name, setName] = React.useState('')
  React.useEffect(() => setName(passkey?.name || ''), [passkey])
  return (
    <Dialog open={!!passkey} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('twofa.rename')}</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            if (passkey && name.trim()) rename.mutate({ id: passkey.id, name: name.trim() }, { onSuccess: onClose, onError: (err) => toast.error(errorMessage(err)) })
          }}
        >
          <FormField label={t('twofa.passkeyName')}>
            <Input value={name} onChange={(e) => setName(e.target.value.slice(0, 60))} autoFocus />
          </FormField>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={rename.isPending}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---- recovery codes -----------------------------------------------------------------------------
function RecoveryRow({ left, onCodes }: { left: number; onCodes: (c: string[]) => void }) {
  const t = useT()
  const renew = useNewRecoveryCodes()
  const [ask, setAsk] = React.useState(false)
  return (
    <>
      <SettingRow
        label={
          <span className="inline-flex items-center gap-2">
            <KeyRound className="size-4 text-muted-foreground" /> {t('twofa.recovery')}
            <Badge variant={left <= 2 ? 'warning' : 'muted'}>{t('twofa.recoveryLeft', { n: left })}</Badge>
          </span>
        }
        description={t('twofa.recoveryDesc')}
      >
        <Button variant="outline" size="sm" onClick={() => setAsk(true)}>
          {t('twofa.recoveryNew')}
        </Button>
      </SettingRow>
      <PasswordDialog
        open={ask}
        title={t('twofa.recoveryNewTitle')}
        description={t('twofa.recoveryNewDesc')}
        confirm={t('twofa.recoveryNew')}
        destructive={false}
        busy={renew.isPending}
        onClose={() => setAsk(false)}
        onConfirm={(password, fail) =>
          renew.mutate(password, {
            onSuccess: (r) => {
              setAsk(false)
              if (r.recovery_codes?.length) onCodes(r.recovery_codes)
            },
            onError: fail,
          })
        }
      />
    </>
  )
}

export function RecoveryCodesDialog({ codes, onClose }: { codes: string[] | null; onClose: () => void }) {
  const t = useT()
  const text = (codes || []).join('\n')
  const download = () => {
    const url = URL.createObjectURL(new Blob([`${t('twofa.recoveryFileHead')}\n\n${text}\n`], { type: 'text/plain' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'recovery-codes.txt'
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return (
    <Dialog open={!!codes} onOpenChange={() => undefined}>
      <DialogContent hideClose onEscapeKeyDown={(e) => e.preventDefault()} onInteractOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>{t('twofa.recoveryTitle')}</DialogTitle>
          <DialogDescription>{t('twofa.recoveryShownOnce')}</DialogDescription>
        </DialogHeader>
        <ul className="grid grid-cols-2 gap-x-6 gap-y-1.5 rounded-lg border bg-muted/40 p-4 font-mono text-sm tracking-wider">
          {(codes || []).map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1 text-[13px] text-muted-foreground">
            <CopyButton text={text} label={t('twofa.recoveryCopy')} /> {t('twofa.recoveryCopy')}
          </span>
          <Button variant="ghost" size="sm" onClick={download}>
            <Download /> {t('twofa.recoveryDownload')}
          </Button>
        </div>
        <DialogFooter>
          <Button onClick={onClose}>{t('twofa.recoverySaved')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---- current password, or a passkey ---------------------------------------------------------------
/** "Confirm with a passkey" instead of typing the password, when this address has one of your passkeys.
 *  `onDone()` runs once confirmed: send the request with an empty password. */
export function PasskeyConfirm({ onDone, onError }: { onDone: () => void; onError: (message: string) => void }) {
  const t = useT()
  const { data: m } = useAuthMethods()
  const [busy, setBusy] = React.useState(false)
  const here = m?.passkey_here
  if (!here?.ok || !passkeysSupported() || !m?.passkeys.some((p) => p.rp_id === here.rp_id)) return null
  return (
    <Button
      type="button"
      variant="outline"
      loading={busy}
      onClick={async () => {
        setBusy(true)
        try {
          await reauthWithPasskey()
          onDone()
        } catch (e) {
          if (!passkeyCancelled(e)) onError(isApiError(e, 'bad_passkey') ? t('twofa.badPasskey') : errorMessage(e))
        } finally {
          setBusy(false)
        }
      }}
    >
      <Fingerprint /> {t('twofa.confirmPasskey')}
    </Button>
  )
}

function PasswordDialog({
  open,
  title,
  description,
  confirm,
  busy,
  destructive = true,
  onClose,
  onConfirm,
}: {
  open: boolean
  title: string
  description: string
  confirm: string
  busy: boolean
  destructive?: boolean
  onClose: () => void
  onConfirm: (password: string, fail: (e: Error) => void) => void
}) {
  const t = useT()
  const [password, setPassword] = React.useState('')
  const [error, setError] = React.useState<string>()
  React.useEffect(() => {
    if (!open) {
      setPassword('')
      setError(undefined)
    }
  }, [open])
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            if (!password) return setError(t('security.currentRequired'))
            onConfirm(password, (err) => setError(isApiError(err, 'bad_password') ? t('security.currentWrong') : errorMessage(err)))
          }}
        >
          <FormField label={t('security.current')} error={error}>
            <SecretInput value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus />
          </FormField>
          <DialogFooter className="gap-2 sm:justify-between">
            <PasskeyConfirm
              onDone={() => onConfirm('', (err) => setError(errorMessage(err)))}
              onError={setError}
            />
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={onClose}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" variant={destructive ? 'destructive' : 'default'} loading={busy}>
                {confirm}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
