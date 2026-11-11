import * as React from 'react'
import { Fingerprint, Send } from 'lucide-react'
import { passkeyPrompt, pollTwoFactor } from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
import { getPasskey, passkeyCancelled, passkeysSupported } from '@/lib/webauthn'
import { useT } from '@/i18n'
import { Button, Checkbox, CodeBlock, FormField, Input, Label, Spinner, toast } from '@/components/ui'
import type { TwoFactorChallenge, TwoFactorMethod, TwoFactorPoll } from '@/lib/types'

const POLL_MS = 1500
const RECOVERY_RE = /^[a-z0-9]{5}-?[a-z0-9]{5}$/i

/** The second step of a sign-in: a passkey, a code (authenticator app, Telegram message or recovery code) or Allow
 *  in Telegram (polling) - whatever `challenge.methods` accepts (none listed: an older server, Telegram only).
 *  `onDone(null)` = approved; `onDone(message)` = denied / expired / cancelled (message to show, or ''). */
export function TwoFactorWait({ challenge, trustOption = false, onDone }: { challenge: TwoFactorChallenge; trustOption?: boolean; onDone: (error: string | null) => void }) {
  const t = useT()
  const methods: TwoFactorMethod[] = challenge.methods?.length ? challenge.methods : ['telegram']
  const tg = methods.includes('telegram')
  const app = methods.includes('totp')
  const recovery = methods.includes('recovery')
  const passkey = methods.includes('passkey') && passkeysSupported()
  const [left, setLeft] = React.useState(challenge.expires_in)
  const [code, setCode] = React.useState('')
  const [codeError, setCodeError] = React.useState<string | null>(null)
  const [checking, setChecking] = React.useState(false)
  const [keyBusy, setKeyBusy] = React.useState(false)
  const [keyError, setKeyError] = React.useState<string | null>(null)
  const [trust, setTrust] = React.useState(true)
  const trustRef = React.useRef(trust)
  trustRef.current = trust
  const done = React.useRef(false)
  const deadline = React.useRef(Date.now() + challenge.expires_in * 1000)
  const finish = React.useCallback(
    (err: string | null) => {
      if (done.current) return
      done.current = true
      onDone(err)
    },
    [onDone],
  )
  const approved = React.useCallback(
    (r: TwoFactorPoll) => {
      if (r.status !== 'approved') return false
      if (typeof r.recovery_left === 'number') toast.info(t('twofa.recoveryUsed', { n: r.recovery_left }), t('twofa.recoveryUsedDesc'))
      finish(null)
      return true
    },
    [finish, t],
  )
  const outcome = React.useCallback(
    (e: unknown) => {
      if (isApiError(e, 'denied')) finish(t('twofa.denied'))
      else if (isApiError(e, 'expired')) finish(t('twofa.expired'))
      else return false
      return true
    },
    [finish, t],
  )

  React.useEffect(() => {
    let stop = false
    let timer: ReturnType<typeof setTimeout>
    // only an approval in Telegram happens elsewhere: poll for it; the other methods answer here
    const tick = async () => {
      try {
        const r = await pollTwoFactor(challenge.challenge, undefined, trustRef.current)
        if (approved(r)) return
        if (typeof r.expires_in === 'number') {
          setLeft(r.expires_in)
          deadline.current = Date.now() + r.expires_in * 1000
        }
      } catch (e) {
        if (outcome(e)) return
        // signed out meanwhile, or the server keeps failing past the end of the request: the wait ends
        if (isApiError(e, 'auth_required')) return finish(errorMessage(e))
        if (Date.now() > deadline.current + 2 * POLL_MS) return finish(t('twofa.expired'))
      }
      if (!stop && !done.current) timer = setTimeout(tick, POLL_MS)
    }
    if (tg) timer = setTimeout(tick, POLL_MS)
    const clock = setInterval(() => {
      setLeft((s) => Math.max(0, s - 1))
      if (!tg && Date.now() > deadline.current) finish(t('twofa.expired'))
    }, 1000)
    return () => {
      stop = true
      clearTimeout(timer)
      clearInterval(clock)
    }
  }, [challenge.challenge, finish, outcome, approved, tg, t])

  const tryPasskey = async () => {
    setKeyBusy(true)
    setKeyError(null)
    try {
      const options = await passkeyPrompt(challenge.challenge)
      const credential = await getPasskey(options)
      const r = await pollTwoFactor(challenge.challenge, undefined, trustRef.current, credential)
      approved(r)
    } catch (e) {
      if (passkeyCancelled(e)) return
      if (!outcome(e)) setKeyError(isApiError(e, 'bad_passkey') ? t('twofa.badPasskey') : errorMessage(e))
    } finally {
      setKeyBusy(false)
    }
  }

  // the passkey window opens by itself once (the button stays for a retry; Safari wants a click: it then waits)
  const asked = React.useRef(false)
  React.useEffect(() => {
    if (!passkey || asked.current) return
    asked.current = true
    void tryPasskey()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [passkey])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const c = code.trim()
    const digits = c.replace(/\s/g, '')
    const isDigits = /^\d{6}$/.test(digits)
    const isRecovery = recovery && RECOVERY_RE.test(c.replace(/\s/g, ''))
    if (!isDigits && !isRecovery) return setCodeError(t(recovery ? 'twofa.codeFormat' : 'twofa.codeLength'))
    setChecking(true)
    setCodeError(null)
    try {
      approved(await pollTwoFactor(challenge.challenge, isDigits ? digits : c, trust))
    } catch (err) {
      if (!outcome(err)) setCodeError(isApiError(err, 'bad_code') ? t('twofa.badCode') : isApiError(err, 'codes_paused') ? t('twofa.codesPaused') : errorMessage(err))
      setCode('')
    } finally {
      setChecking(false)
    }
  }

  const codeLabel = app && tg ? t('twofa.codeAppOrTelegram') : app ? t('twofa.codeApp') : tg ? t('twofa.code') : t('twofa.codeRecovery')
  const mm = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`
  const onlyTelegram = tg && !app && !recovery && !methods.includes('passkey')
  return (
    <div className="grid gap-5">
      {passkey && (
        <div className="grid gap-2">
          <Button type="button" size="lg" className="w-full" loading={keyBusy} onClick={tryPasskey} autoFocus>
            <Fingerprint /> {t('twofa.usePasskey')}
          </Button>
          {keyError && (
            <p role="alert" className="text-[13px] text-destructive">
              {keyError}
            </p>
          )}
        </div>
      )}
      {tg && (
        <div className="flex gap-3 rounded-lg border bg-muted/40 p-4 text-sm">
          <Send className="mt-0.5 size-5 shrink-0 text-primary" />
          <div className="grid gap-1">
            <p className="font-medium">{t('twofa.check')}</p>
            <p className="text-[13px] text-muted-foreground">{t('twofa.checkDesc')}</p>
            <p className="flex items-center gap-2 text-[13px] text-muted-foreground" aria-live="polite">
              <Spinner className="size-3.5" /> {t('twofa.waiting', { time: mm })}
            </p>
          </div>
        </div>
      )}
      <form onSubmit={submit} className="grid gap-3" noValidate>
        <FormField label={codeLabel} error={codeError || undefined} hint={recovery && (app || tg) ? t('twofa.recoveryHint') : undefined}>
          <Input
            value={code}
            onChange={(e) => setCode(recovery ? e.target.value.replace(/[^a-zA-Z0-9 -]/g, '').slice(0, 12) : e.target.value.replace(/[^\d ]/g, '').slice(0, 7))}
            inputMode={recovery ? 'text' : 'numeric'}
            autoComplete="one-time-code"
            autoCapitalize="off"
            spellCheck={false}
            autoFocus={!passkey}
            placeholder="123456"
            className="font-mono tracking-widest"
          />
        </FormField>
        {trustOption && (
          <Label className="gap-2 font-normal pointer-coarse:min-h-10">
            <Checkbox checked={trust} onCheckedChange={(v) => setTrust(v === true)} /> {t('twofa.trust')}
          </Label>
        )}
        <div className="flex gap-2">
          <Button type="submit" variant={passkey ? 'outline' : 'default'} loading={checking} className="flex-1">
            {t('twofa.verify')}
          </Button>
          <Button type="button" variant="ghost" onClick={() => finish('')}>
            {t('common.cancel')}
          </Button>
        </div>
        {!tg && (
          <p className="text-center text-[13px] text-muted-foreground" aria-live="polite">
            {t('twofa.expiresIn', { time: mm })}
          </p>
        )}
      </form>
      <details className="text-[13px] text-muted-foreground">
        <summary className="cursor-pointer list-none text-center hover:text-foreground pointer-coarse:flex pointer-coarse:min-h-10 pointer-coarse:items-center pointer-coarse:justify-center">
          {onlyTelegram ? t('twofa.noAnswer') : t('twofa.lostAll')}
        </summary>
        <div className="mt-3 grid gap-2">
          <p>{onlyTelegram ? t('twofa.noAnswerHelp') : t('twofa.lostAllHelp')}</p>
          <CodeBlock inline code="maxxing 2fa off" />
        </div>
      </details>
    </div>
  )
}
