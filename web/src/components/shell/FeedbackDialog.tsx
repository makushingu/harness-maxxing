import * as React from 'react'
import { Bug, CheckCircle2, Lightbulb, MessageSquare } from 'lucide-react'
import { useT } from '@/i18n'
import { ApiError } from '@/lib/api'
import { type FeedbackType, useFeedbackDefaults, useSendFeedback } from '@/lib/queries'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, FormField, Input, Segmented, Spinner, Textarea } from '@/components/ui'
import { DonationLine } from '@/features/donation/Donation'
import { useFeedbackDialog } from './feedback-store'

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const MAX = 4000

/** Feedback to the authors: bug, idea or anything, with the user's email (required, against abuse; they answer
 *  there). Sent by the server to api.harness-maxxing.com with the version, nothing else (docs/user/23-license.md). */
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

  React.useEffect(() => {
    if (open && defaults.data && !email) setEmail(defaults.data.email)
  }, [open, defaults.data]) // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => {
    if (open) return
    const id = setTimeout(() => { setSent(false); setTried(false); setMessage(''); send.reset() }, 200)   // after the close animation
    return () => clearTimeout(id)
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const emailBad = !EMAIL.test(email.trim())
  const msgBad = message.trim().length < 3
  const err = send.error instanceof ApiError ? send.error : null
  const errText = err
    ? ({ rate: t('feedback.err.rate'), unreachable: t('feedback.err.unreachable'), offline: t('feedback.err.offline'), invalid_email: t('feedback.err.email'), bad_email: t('feedback.err.email') } as Record<string, string>)[err.code] || err.message
    : send.error ? t('feedback.err.unreachable') : ''

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setTried(true)
    if (emailBad || msgBad || send.isPending) return
    send.mutate({ email: email.trim(), type, message: message.trim() }, { onSuccess: () => setSent(true) })
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
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
  )
}
