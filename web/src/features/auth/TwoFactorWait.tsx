import * as React from 'react'
import { Send } from 'lucide-react'
import { pollTwoFactor } from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
import { useT } from '@/i18n'
import { Button, Checkbox, CodeBlock, FormField, Input, Label, Spinner } from '@/components/ui'
import type { TwoFactorChallenge } from '@/lib/types'

const POLL_MS = 1500

/** Waits for Allow in Telegram (polling) or the code of the message typed by hand.
 *  `onDone(null)` = approved; `onDone(message)` = denied / expired / cancelled (message to show, or ''). */
export function TwoFactorWait({ challenge, trustOption = false, onDone }: { challenge: TwoFactorChallenge; trustOption?: boolean; onDone: (error: string | null) => void }) {
  const t = useT()
  const [left, setLeft] = React.useState(challenge.expires_in)
  const [code, setCode] = React.useState('')
  const [codeError, setCodeError] = React.useState<string | null>(null)
  const [checking, setChecking] = React.useState(false)
  const [trust, setTrust] = React.useState(true)
  const trustRef = React.useRef(trust)
  trustRef.current = trust
  const done = React.useRef(false)
  const finish = React.useCallback(
    (err: string | null) => {
      if (done.current) return
      done.current = true
      onDone(err)
    },
    [onDone],
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
    const tick = async () => {
      try {
        const r = await pollTwoFactor(challenge.challenge, undefined, trustRef.current)
        if (r.status === 'approved') return finish(null)
        if (typeof r.expires_in === 'number') setLeft(r.expires_in)
      } catch (e) {
        if (outcome(e)) return
      }
      if (!stop && !done.current) timer = setTimeout(tick, POLL_MS)
    }
    timer = setTimeout(tick, POLL_MS)
    const clock = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000)
    return () => {
      stop = true
      clearTimeout(timer)
      clearInterval(clock)
    }
  }, [challenge.challenge, finish, outcome])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const c = code.replace(/\D/g, '')
    if (c.length !== 6) return setCodeError(t('twofa.codeLength'))
    setChecking(true)
    setCodeError(null)
    try {
      const r = await pollTwoFactor(challenge.challenge, c, trust)
      if (r.status === 'approved') finish(null)
    } catch (err) {
      if (!outcome(err)) setCodeError(isApiError(err, 'bad_code') ? t('twofa.badCode') : isApiError(err, 'codes_paused') ? t('twofa.codesPaused') : errorMessage(err))
      setCode('')
    } finally {
      setChecking(false)
    }
  }

  const mm = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`
  return (
    <div className="grid gap-5">
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
      <form onSubmit={submit} className="grid gap-3" noValidate>
        <FormField label={t('twofa.code')} error={codeError || undefined}>
          <Input value={code} onChange={(e) => setCode(e.target.value.replace(/[^\d ]/g, '').slice(0, 7))} inputMode="numeric" autoComplete="one-time-code" placeholder="123456" className="font-mono tracking-widest" />
        </FormField>
        {trustOption && (
          <Label className="gap-2 font-normal">
            <Checkbox checked={trust} onCheckedChange={(v) => setTrust(v === true)} /> {t('twofa.trust')}
          </Label>
        )}
        <div className="flex gap-2">
          <Button type="submit" loading={checking} className="flex-1">
            {t('twofa.verify')}
          </Button>
          <Button type="button" variant="ghost" onClick={() => finish('')}>
            {t('common.cancel')}
          </Button>
        </div>
      </form>
      <details className="text-[13px] text-muted-foreground">
        <summary className="cursor-pointer list-none text-center hover:text-foreground">{t('twofa.noAnswer')}</summary>
        <div className="mt-3 grid gap-2">
          <p>{t('twofa.noAnswerHelp')}</p>
          <CodeBlock inline code="maxxing 2fa off" />
        </div>
      </details>
    </div>
  )
}
