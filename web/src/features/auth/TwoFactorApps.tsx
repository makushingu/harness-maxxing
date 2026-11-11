import * as React from 'react'
import { KeyRound, Send } from 'lucide-react'
import { passkeySignInOptions, sendPasskey, sendTwoFactorCode } from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
import { passkeyCancelled, passkeysSupported, signWithPasskey } from '@/lib/webauthn'
import { useT } from '@/i18n'
import { Button, Checkbox, CodeBlock, FormField, Input, Label } from '@/components/ui'
import type { TwoFactorChallenge } from '@/lib/types'
import { TwoFactorWait } from './TwoFactorWait'

/** Sign-in, second step with an authenticator app, a passkey or a recovery code (and Telegram when it is on too).
 *  `onDone(null)` = signed in; `onDone(message)` = back to the password (message to show, or ''). */
export function TwoFactorApps({ tf, onDone }: { tf: TwoFactorChallenge & { ticket: string }; onDone: (error: string | null) => void }) {
  const t = useT()
  const methods = tf.methods ?? []
  const canPasskey = methods.includes('passkey') && passkeysSupported()
  const [code, setCode] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState<'code' | 'passkey' | null>(null)
  const [trust, setTrust] = React.useState(true)
  const done = React.useRef(false)
  const finish = React.useCallback(
    (err: string | null) => {
      if (done.current) return
      done.current = true
      onDone(err)
    },
    [onDone],
  )
  const failed = (e: unknown) => {
    if (isApiError(e, 'expired')) return finish(errorMessage(e) || t('twofa.expired'))
    setError(isApiError(e, 'bad_code') ? t('twofa.badCode') : isApiError(e, 'codes_paused') ? t('twofa.appCodesPaused') : errorMessage(e))
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const c = code.trim()
    if (!c) return setError(t('twofa.appCodeRequired'))
    setBusy('code')
    setError(null)
    try {
      const r = await sendTwoFactorCode(tf.ticket, c, trust)
      if (r.status === 'approved') finish(null)
    } catch (err) {
      failed(err)
      setCode('')
    } finally {
      setBusy(null)
    }
  }

  const passkey = async () => {
    setBusy('passkey')
    setError(null)
    try {
      const { options } = await passkeySignInOptions(tf.ticket)
      const credential = await signWithPasskey(options)
      const r = await sendPasskey(tf.ticket, credential, trust)
      if (r.status === 'approved') finish(null)
    } catch (err) {
      if (passkeyCancelled(err)) setError(t('twofa.passkeyCancelled'))
      else failed(err)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="grid gap-5">
      {canPasskey && (
        <Button type="button" size="lg" className="w-full" loading={busy === 'passkey'} onClick={passkey}>
          <KeyRound /> {t('twofa.passkey')}
        </Button>
      )}
      <form onSubmit={submit} className="grid gap-3" noValidate>
        <FormField
          label={methods.includes('totp') ? t('twofa.appCode') : t('twofa.recoveryCode')}
          hint={methods.includes('totp') ? t('twofa.recoveryHint') : undefined}
          error={error || undefined}
        >
          <Input
            value={code}
            onChange={(e) => setCode(e.target.value.slice(0, 16))}
            autoComplete="one-time-code"
            autoFocus={!canPasskey}
            autoCapitalize="none"
            spellCheck={false}
            placeholder={methods.includes('totp') ? '123456' : 'abcde-fghjk'}
            className="font-mono tracking-widest"
          />
        </FormField>
        <Label className="gap-2 font-normal pointer-coarse:min-h-10">
          <Checkbox checked={trust} onCheckedChange={(v) => setTrust(v === true)} /> {t('twofa.trust')}
        </Label>
        <div className="flex gap-2">
          <Button type="submit" variant={canPasskey ? 'outline' : 'default'} loading={busy === 'code'} className="flex-1">
            {t('twofa.verify')}
          </Button>
          <Button type="button" variant="ghost" onClick={() => finish('')}>
            {t('common.cancel')}
          </Button>
        </div>
      </form>
      {tf.challenge && (
        // mounted while folded: Allow in Telegram still signs in
        <details className="group rounded-lg border p-3 text-[13px]">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-muted-foreground hover:text-foreground pointer-coarse:min-h-10">
            <Send className="size-4" /> {t('twofa.orTelegram')}
          </summary>
          <div className="mt-3">
            <TwoFactorWait challenge={{ challenge: tf.challenge, expires_in: tf.expires_in }} trustOption onDone={(err) => (err === null ? finish(null) : undefined)} />
          </div>
        </details>
      )}
      <details className="text-[13px] text-muted-foreground">
        <summary className="cursor-pointer list-none text-center hover:text-foreground pointer-coarse:flex pointer-coarse:min-h-10 pointer-coarse:items-center pointer-coarse:justify-center">{t('twofa.lost')}</summary>
        <div className="mt-3 grid gap-2">
          <p>{t('twofa.noAnswerHelp')}</p>
          <CodeBlock inline code="maxxing 2fa off" />
        </div>
      </details>
    </div>
  )
}
