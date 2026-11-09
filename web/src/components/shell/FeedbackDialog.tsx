import * as React from 'react'
import { Bug, CheckCircle2, Crop, Lightbulb, MessageSquare, X } from 'lucide-react'
import { useT } from '@/i18n'
import { ApiError } from '@/lib/api'
import { type FeedbackType, useFeedbackDefaults, useSendFeedback } from '@/lib/queries'
import { Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, FormField, Input, Segmented, Spinner, Textarea } from '@/components/ui'
import { DonationLine } from '@/features/donation/Donation'
import { useUI } from '@/stores/ui'
import { useFeedbackDialog } from './feedback-store'
import { type Shot, type Zone, ZoneSelect, blobBase64, shootZone } from './zoneShot'

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const MAX = 4000

/** Feedback to the authors: bug, idea or anything, with the user's email (required, against abuse; they answer
 *  there), and optionally a screenshot of a zone of the page (presentation mode on while it is taken = data hidden).
 *  Sent by the server to api.harness-maxxing.com with the version, nothing else (docs/user/23-license.md). */
export function FeedbackDialog() {
  const t = useT()
  const { open, setOpen } = useFeedbackDialog()
  const defaults = useFeedbackDefaults(open)
  const send = useSendFeedback()
  const [type, setType] = React.useState<FeedbackType>('bug')
  const [email, setEmail] = React.useState('')
  const [message, setMessage] = React.useState('')
  const [tried, setTried] = React.useState(false)
  const [sent, setSent] = React.useState(false)
  const presenting = useUI((s) => s.presentation)
  const [blur, setBlur] = React.useState(true)
  const [picking, setPicking] = React.useState(false)
  const [shooting, setShooting] = React.useState(false)
  const [shot, setShot] = React.useState<Shot | null>(null)
  const [shotErr, setShotErr] = React.useState(false)
  const sending = React.useRef(false)      // the image is read before mutate(): a 2nd click in between must not send twice
  const setShotUrl = (s: Shot | null) => setShot((old) => { if (old) URL.revokeObjectURL(old.url); return s })

  React.useEffect(() => {
    if (open && defaults.data && !email) setEmail(defaults.data.email)
  }, [open, defaults.data]) // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => {
    if (open) return
    if (picking || shooting) return
    const id = setTimeout(() => { setSent(false); setTried(false); setMessage(''); setShotUrl(null); setShotErr(false); send.reset() }, 200)   // after the close animation
    return () => clearTimeout(id)
  }, [open, picking, shooting]) // eslint-disable-line react-hooks/exhaustive-deps

  const pick = () => { setShotErr(false); setPicking(true) }
  const picked = React.useCallback(async (z: Zone | null) => {
    setPicking(false)
    if (!z) return
    setShooting(true)
    const ui = useUI.getState()
    const hide = blur && !ui.presentation          // presentation mode only for the shot, then back as it was
    if (hide) ui.setPresentation(true)
    try {
      await new Promise((ok) => setTimeout(ok, 120))   // the dialog's close animation, the masks rendered
      setShotUrl(await shootZone(z, useUI.getState().presentation))
    } catch {
      setShotErr(true)
    } finally {
      if (hide) useUI.getState().setPresentation(false)
      setShooting(false)
    }
  }, [blur]) // eslint-disable-line react-hooks/exhaustive-deps

  const emailBad = !EMAIL.test(email.trim())
  const msgBad = message.trim().length < 3
  const err = send.error instanceof ApiError ? send.error : null
  const errText = err
    ? ({ rate: t('feedback.err.rate'), unreachable: t('feedback.err.unreachable'), offline: t('feedback.err.offline'), invalid_email: t('feedback.err.email'), bad_email: t('feedback.err.email'), bad_image: t('feedback.err.image'), image_refused: t('feedback.err.image') } as Record<string, string>)[err.code] || err.message
    : send.error ? t('feedback.err.unreachable') : ''

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setTried(true)
    if (emailBad || msgBad || send.isPending || sending.current) return
    sending.current = true
    const go = async () => {
      const image = shot ? { mime: shot.mime, data: await blobBase64(shot.blob), width: shot.width, height: shot.height } : undefined
      send.mutate({ email: email.trim(), type, message: message.trim(), image }, { onSuccess: () => setSent(true), onSettled: () => { sending.current = false } })
    }
    go().catch(() => { sending.current = false })
  }

  return (
    <>
    {picking && <ZoneSelect onDone={picked} />}
    {shooting && <div data-capture-skip className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-full bg-popover px-4 py-2 text-sm shadow-lg"><Spinner /> {t('feedback.zoneTaking')}</div>}
    <Dialog open={open && !picking && !shooting} onOpenChange={setOpen}>
      <DialogContent className="md:max-w-lg">
        {sent ? (
          <div className="grid justify-items-center gap-3 py-4 text-center">
            <CheckCircle2 className="size-10 text-success" />
            <DialogTitle>{t('feedback.sentTitle')}</DialogTitle>
            <DialogDescription>{t('feedback.sentBody', { email: email.trim() })}</DialogDescription>
            <DonationLine text="donation.feedback" className="justify-center" />
            <Button className="mt-2" onClick={() => setOpen(false)}>{t('common.close')}</Button>
          </div>
        ) : (
          <form onSubmit={submit} className="grid gap-4" noValidate>
            <DialogHeader>
              <DialogTitle>{t('feedback.title')}</DialogTitle>
              <DialogDescription>{t('feedback.description')}</DialogDescription>
            </DialogHeader>
            <Segmented
              value={type}
              onChange={setType}
              options={[
                { value: 'bug', label: t('feedback.type.bug'), icon: <Bug /> },
                { value: 'idea', label: t('feedback.type.idea'), icon: <Lightbulb /> },
                { value: 'other', label: t('feedback.type.other'), icon: <MessageSquare /> },
              ]}
            />
            <FormField label={t('feedback.message')} error={tried && msgBad ? t('feedback.err.message') : undefined} aside={message.length > MAX * 0.9 ? <span className="text-xs text-muted-foreground">{message.length}/{MAX}</span> : undefined}>
              <Textarea
                value={message}
                onChange={(e) => setMessage(e.target.value.slice(0, MAX))}
                placeholder={t(`feedback.placeholder.${type}`)}
                minRows={5}
                maxRows={14}
                autoFocus
              />
            </FormField>
            <div className="grid gap-2">
              {shot ? (
                <div className="flex items-start gap-3">
                  <a href={shot.url} target="_blank" rel="noopener" className="block shrink-0 overflow-hidden rounded-md border">
                    <img src={shot.url} alt={t('feedback.zoneAlt')} className="max-h-28 max-w-48 object-contain" />
                  </a>
                  <div className="grid gap-1.5">
                    <Button type="button" size="sm" variant="outline" onClick={pick}><Crop />{t('feedback.zoneRedo')}</Button>
                    <Button type="button" size="sm" variant="ghost" onClick={() => setShotUrl(null)}><X />{t('feedback.zoneRemove')}</Button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                  <Button type="button" size="sm" variant="outline" onClick={pick}><Crop />{t('feedback.zone')}</Button>
                  <label className="flex cursor-pointer items-center gap-2 text-sm">
                    <Checkbox checked={presenting || blur} disabled={presenting} onCheckedChange={(v) => setBlur(v === true)} />
                    {t('feedback.zoneBlur')}
                  </label>
                </div>
              )}
              {shotErr && <p className="text-xs text-destructive">{t('feedback.zoneFailed')}</p>}
            </div>
            <FormField label={t('feedback.email')} hint={t('feedback.emailHint')} error={tried && emailBad ? t('feedback.err.email') : undefined}>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" autoComplete="email" inputMode="email" />
            </FormField>
            {errText && <p className="text-sm text-destructive" role="alert">{errText}</p>}
            <DialogFooter className="items-center">
              <span className="mr-auto text-xs text-muted-foreground">{defaults.data?.version ? t('feedback.sentWith', { version: defaults.data.version }) : ''}</span>
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>{t('common.cancel')}</Button>
              <Button type="submit" disabled={send.isPending}>{send.isPending && <Spinner />}{t('feedback.send')}</Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
    </>
  )
}
