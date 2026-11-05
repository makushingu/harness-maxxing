// Writing a message: new, reply, reply all, forward, or a draft opened again. Plain text; the signature of the
// mailbox is already in the text it starts with, so what is sent is what is shown. Sending goes through the SMTP
// server of the mailbox, capped per day (`send_per_day`) and per message (20 recipients): not a bulk sender.
import * as React from 'react'
import { FileText, Paperclip, Send, Trash2, X } from 'lucide-react'
import { Button, Dialog, DialogContent, DialogDescription, DialogTitle, Input, Select, Textarea } from '@/components/ui'
import { toast } from '@/components/ui/toast'
import { errorMessage } from '@/lib/api'
import { fmtBytes } from '@/lib/format'
import type { MailAccount, MailAttachment, MailComposeMode, MailDraft } from '@/lib/types'
import { useMailSaveDraft, useMailSend } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'

export type ComposeInit = {
  mode: 'new' | MailComposeMode
  acc: string
  to: string[]
  cc: string[]
  bcc: string[]
  subject: string
  text: string
  in_reply_to?: string
  references?: string
  /** the message replied to (flagged "answered" once sent) */
  reply?: { folder: string; uid: number }
  /** attachments taken from an existing message (forward, or a draft opened again) */
  source?: { folder: string; uid: number; attachments: MailAttachment[] }
  /** the draft this message replaces (dropped once sent or saved again) */
  draft?: { folder: string; uid: number }
}

export const MAX_RECIPIENTS = 20
const MAX_TOTAL = 25 * 1024 * 1024

export const signatureBlock = (a: MailAccount | undefined) => (a?.signature?.trim() ? `\n\n-- \n${a.signature.trim()}` : '')

const split = (s: string) =>
  s
    .split(/[,;\n]/)
    .map((x) => x.trim())
    .filter(Boolean)
const join = (a: string[]) => a.join(', ')

function Field({ label, children, extra }: { label: string; children: React.ReactNode; extra?: React.ReactNode }) {
  return (
    <label className="flex items-center gap-2 border-b py-1.5 text-[13px]">
      <span className="w-14 shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 flex-1">{children}</span>
      {extra}
    </label>
  )
}

const bare = 'h-8 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0 dark:bg-transparent'

export function Compose({ init, accounts, onClose }: { init: ComposeInit; accounts: MailAccount[]; onClose: () => void }) {
  const t = useT()
  const [acc, setAcc] = React.useState(init.acc)
  const [to, setTo] = React.useState(join(init.to))
  const [cc, setCc] = React.useState(join(init.cc))
  const [bcc, setBcc] = React.useState(join(init.bcc))
  const [showCc, setShowCc] = React.useState(!!(init.cc.length || init.bcc.length))
  const [subject, setSubject] = React.useState(init.subject)
  const [text, setText] = React.useState(init.text)
  const [kept, setKept] = React.useState<MailAttachment[]>(init.source?.attachments || [])
  const [files, setFiles] = React.useState<File[]>([])
  const [draft, setDraft] = React.useState(init.draft)
  const [error, setError] = React.useState<string | null>(null)
  const fileInput = React.useRef<HTMLInputElement>(null)
  const body = React.useRef<HTMLTextAreaElement>(null)
  // attachments of the source message can only be read from the mailbox they are in
  const sourceAcc = init.acc
  const account = accounts.find((a) => a.id === acc)
  const send = useMailSend(acc)
  const save = useMailSaveDraft(acc)
  const busy = send.isPending || save.isPending
  const dirty = React.useRef(false)

  const toInput = React.useRef<HTMLInputElement>(null)
  // a new message or a forward starts in To; a reply or a draft in the text, above the quoted message
  const focusFirst = (e: Event) => {
    e.preventDefault()
    if (init.mode === 'new' || init.mode === 'forward' || !split(join(init.to)).length) {
      toInput.current?.focus()
      return
    }
    const el = body.current
    if (!el) return
    el.focus()
    const end = init.mode === 'draft' ? el.value.search(/\n\n-- \n|\n\n[^\n]*:\n>|$/) : 0
    el.setSelectionRange(end, end)
    el.scrollTop = 0
  }

  const recipients = split(to).length + split(cc).length + split(bcc).length
  const total = kept.reduce((n, a) => n + a.size, 0) + files.reduce((n, f) => n + f.size, 0)
  const left = account?.send_per_day != null ? Math.max(0, account.send_per_day - (account.sent_today || 0)) : null

  const build = (): MailDraft => ({
    to: split(to),
    cc: showCc ? split(cc) : [],
    bcc: showCc ? split(bcc) : [],
    subject,
    text,
    in_reply_to: init.in_reply_to,
    references: init.references,
    reply: init.reply,
    forward: init.source && kept.length && acc === sourceAcc ? { folder: init.source.folder, uid: init.source.uid, indexes: kept.map((a) => a.index) } : undefined,
    draft: acc === init.acc ? draft : undefined,
  })

  const doSend = () => {
    setError(null)
    if (!recipients) return setError(t('mail.compose.noRecipient'))
    if (recipients > MAX_RECIPIENTS) return setError(t('mail.compose.tooMany', { max: MAX_RECIPIENTS }))
    if (total > MAX_TOTAL) return setError(t('mail.compose.tooLarge'))
    if (!subject.trim() && !window.confirm(t('mail.compose.noSubjectConfirm'))) return
    send.mutate(
      { draft: build(), files },
      {
        onSuccess: (r) => {
          toast.success(r.refused.length ? t('mail.compose.sentPartly', { list: r.refused.join(', ') }) : t('mail.compose.sent'))
          onClose()
        },
        onError: (e) => setError(errorMessage(e)),
      },
    )
  }
  const doSave = (close: boolean) => {
    setError(null)
    save.mutate(
      { draft: build(), files },
      {
        onSuccess: (r) => {
          dirty.current = false
          setDraft(r)
          // the attachments are in the draft now: the next save reads them from there
          setFiles([])
          if (close) onClose()
          else toast.success(t('mail.compose.saved'))
        },
        onError: (e) => setError(errorMessage(e)),
      },
    )
  }
  const tryClose = () => {
    if (busy) return
    if (dirty.current && !window.confirm(t('mail.compose.discardConfirm'))) return
    onClose()
  }
  const touch = <T,>(set: (v: T) => void) => (v: T) => {
    dirty.current = true
    set(v)
  }

  const title = { new: t('mail.compose.new'), reply: t('mail.compose.reply'), replyall: t('mail.compose.reply'), forward: t('mail.compose.forward'), draft: t('mail.compose.draft') }[init.mode]

  return (
    <Dialog open onOpenChange={(o) => !o && tryClose()}>
      <DialogContent
        className="gap-0 md:max-w-3xl md:p-0"
        onInteractOutside={(e) => e.preventDefault()}
        onOpenAutoFocus={focusFirst}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault()
            doSend()
          }
        }}
        data-testid="mail-compose"
      >
        <div className="flex items-center gap-2 px-1 pb-2 md:border-b md:px-5 md:py-3">
          <DialogTitle className="flex-1 text-base">{title}</DialogTitle>
          <DialogDescription className="sr-only">{t('mail.compose.desc')}</DialogDescription>
        </div>
        <div className="flex min-h-0 flex-1 flex-col px-1 md:px-5">
          {accounts.length > 1 && (
            <Field label={t('mail.compose.from')}>
              <Select
                className="h-8 border-0 px-0 shadow-none"
                aria-label={t('mail.compose.from')}
                value={acc}
                onValueChange={setAcc}
                options={accounts.map((a) => ({ value: a.id, label: a.name ? `${a.name} <${a.address}>` : a.address }))}
              />
            </Field>
          )}
          <Field
            label={t('mail.to')}
            extra={
              !showCc && (
                <button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setShowCc(true)}>
                  {t('mail.compose.ccBcc')}
                </button>
              )
            }
          >
            <Input ref={toInput} className={bare} value={to} onChange={(e) => touch(setTo)(e.target.value)} aria-label={t('mail.to')} placeholder="name@example.com" />
          </Field>
          {showCc && (
            <>
              <Field label={t('mail.cc')}>
                <Input className={bare} value={cc} onChange={(e) => touch(setCc)(e.target.value)} aria-label={t('mail.cc')} />
              </Field>
              <Field label={t('mail.compose.bcc')}>
                <Input className={bare} value={bcc} onChange={(e) => touch(setBcc)(e.target.value)} aria-label={t('mail.compose.bcc')} />
              </Field>
            </>
          )}
          <Field label={t('mail.compose.subject')}>
            <Input className={cn(bare, 'font-medium')} value={subject} onChange={(e) => touch(setSubject)(e.target.value)} aria-label={t('mail.compose.subject')} />
          </Field>
          <Textarea
            ref={body}
            className="mt-2 min-h-[14rem] flex-1 resize-none border-0 px-0 font-sans text-sm leading-relaxed shadow-none focus-visible:ring-0 dark:bg-transparent"
            autosize
            minRows={10}
            maxRows={22}
            value={text}
            onChange={(e) => touch(setText)(e.target.value)}
            aria-label={t('mail.compose.body')}
          />
          {(kept.length > 0 || files.length > 0) && (
            <div className="flex flex-wrap gap-2 py-2">
              {kept.map((a) => (
                <span key={`k${a.index}`} className="flex max-w-64 items-center gap-1.5 rounded-lg border bg-card px-2 py-1 text-xs">
                  <Paperclip className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate">{a.filename}</span>
                  <span className="shrink-0 text-muted-foreground">{fmtBytes(a.size)}</span>
                  <button type="button" aria-label={t('common.remove')} onClick={() => touch(setKept)(kept.filter((x) => x.index !== a.index))} className="text-muted-foreground hover:text-foreground">
                    <X className="size-3.5" />
                  </button>
                </span>
              ))}
              {files.map((f, i) => (
                <span key={`f${i}`} className="flex max-w-64 items-center gap-1.5 rounded-lg border bg-card px-2 py-1 text-xs">
                  <Paperclip className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate">{f.name}</span>
                  <span className="shrink-0 text-muted-foreground">{fmtBytes(f.size)}</span>
                  <button type="button" aria-label={t('common.remove')} onClick={() => touch(setFiles)(files.filter((_, j) => j !== i))} className="text-muted-foreground hover:text-foreground">
                    <X className="size-3.5" />
                  </button>
                </span>
              ))}
            </div>
          )}
          {error && <p className="py-2 text-xs text-destructive" role="alert">{error}</p>}
        </div>
        <div className="flex items-center gap-2 px-1 pt-3 md:border-t md:px-5 md:py-3">
          <Button onClick={doSend} disabled={busy} data-testid="mail-send">
            <Send /> {send.isPending ? t('mail.compose.sending') : t('mail.compose.send')}
          </Button>
          <Button variant="ghost" size="icon" onClick={() => fileInput.current?.click()} aria-label={t('mail.compose.attach')} title={t('mail.compose.attach')} disabled={busy}>
            <Paperclip />
          </Button>
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              const picked = Array.from(e.target.files || [])
              if (picked.length) touch(setFiles)([...files, ...picked])
              e.target.value = ''
            }}
          />
          <Button variant="ghost" size="sm" onClick={() => doSave(false)} disabled={busy} title={t('mail.compose.saveDraft')}>
            <FileText /> <span className="max-sm:sr-only">{save.isPending ? t('mail.compose.saving') : t('mail.compose.saveDraft')}</span>
          </Button>
          <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
            {total > 0 && <span className={cn(total > MAX_TOTAL && 'text-destructive')}>{fmtBytes(total)} · </span>}
            {left != null && t('mail.compose.left', { count: left })}
          </span>
          <Button variant="ghost" size="icon" onClick={tryClose} aria-label={t('mail.compose.discard')} title={t('mail.compose.discard')} disabled={busy}>
            <Trash2 />
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
