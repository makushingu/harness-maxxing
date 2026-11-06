// Writing a message: new, reply, reply all, forward, or a draft opened again. Plain text; the signature of the
// mailbox is already in the text it starts with, so what is sent is what is shown. Sending goes through the SMTP
// server of the mailbox, capped per day (`send_per_day`) and per message (20 recipients): not a bulk sender.
import * as React from 'react'
import { useBlocker } from 'react-router'
import { FileText, Paperclip, Send, Trash2, X } from 'lucide-react'
import { Button, Dialog, DialogContent, DialogDescription, DialogTitle, Input, Select, Textarea } from '@/components/ui'
import { toast } from '@/components/ui/toast'
import { errorMessage, isApiError } from '@/lib/api'
import { fmtBytes } from '@/lib/format'
import type { MailAccount, MailAttachment, MailComposeMode, MailDraft } from '@/lib/types'
import { fetchMailCompose, useMailSaveDraft, useMailSend } from '@/lib/queries'
import { busyEnd, busyStart } from '@/lib/busy'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { forgetCompose, forgetReply, rememberReply, saveCompose, saveFiles } from './localDraft'

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
  /** attachments taken from an existing message (forward, or a draft opened again); `acc` when not `acc` above */
  source?: { folder: string; uid: number; attachments: MailAttachment[]; acc?: string }
  /** the draft this message replaces (dropped once sent or saved again); `acc` when not `acc` above */
  draft?: { folder: string; uid: number; acc?: string }
  /** a message this browser kept (localStorage + IndexedDB) and opens again after a reload */
  restored?: { showCc: boolean; kept: MailAttachment[]; files: File[] }
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
  const [showCc, setShowCc] = React.useState(init.restored ? init.restored.showCc : !!(init.cc.length || init.bcc.length))
  const [subject, setSubject] = React.useState(init.subject)
  const [text, setText] = React.useState(init.text)
  // attachments read from a message on the server (`source`): the forwarded one, the draft opened again, or the
  // draft this dialog saved last (a saved file lives in that draft from then on)
  const [source, setSource] = React.useState(init.source ? { ...init.source, acc: init.source.acc || init.acc } : undefined)
  const [kept, setKept] = React.useState<MailAttachment[]>(init.restored ? init.restored.kept : init.source?.attachments || [])
  const [files, setFiles] = React.useState<File[]>(init.restored?.files || [])
  const [draft, setDraft] = React.useState(init.draft ? { ...init.draft, acc: init.draft.acc || init.acc } : undefined)
  const [error, setError] = React.useState<string | null>(null)
  // the server could not tell whether the last send went out: sending again asks first
  const [unsure, setUnsure] = React.useState(false)
  const fileInput = React.useRef<HTMLInputElement>(null)
  const body = React.useRef<HTMLTextAreaElement>(null)
  const account = accounts.find((a) => a.id === acc)
  const send = useMailSend(acc)
  const save = useMailSaveDraft(acc)
  // one send or save at a time: the state of the mutations lags one render behind a fast double Ctrl+Enter
  const inFlight = React.useRef(false)
  const busy = send.isPending || save.isPending
  const [dirty, setDirty] = React.useState(!!init.restored)
  const closed = React.useRef(false)

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
    const end = init.mode === 'draft' || init.restored ? el.value.search(/\n\n-- \n|\n\n[^\n]*:\n>|$/) : 0
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
    // the message replied to is in the mailbox the dialog was opened from
    reply: acc === init.acc ? init.reply : undefined,
    forward: source && kept.length && acc === source.acc ? { folder: source.folder, uid: source.uid, indexes: kept.map((a) => a.index) } : undefined,
    draft: draft && acc === draft.acc ? { folder: draft.folder, uid: draft.uid } : undefined,
  })

  // ---- the copy kept in this browser (a reload, a closed tab or Back does not lose the message)
  const snapshot = React.useRef<() => void>(() => {})
  snapshot.current = () => {
    if (closed.current || !dirty) return
    saveCompose({
      mode: init.mode, acc, to: split(to), cc: split(cc), bcc: split(bcc), subject, text,
      in_reply_to: init.in_reply_to, references: init.references, reply: init.reply, source, draft,
      showCc, kept, files: files.length,
    })
  }
  React.useEffect(() => {
    if (!dirty) return
    const id = window.setTimeout(() => snapshot.current(), 400)
    return () => window.clearTimeout(id)
  }, [dirty, acc, to, cc, bcc, showCc, subject, text, kept, source, draft])
  React.useEffect(() => {
    if (dirty && !closed.current) void saveFiles(files)
  }, [dirty, files])
  React.useEffect(() => {
    const flush = () => snapshot.current()
    window.addEventListener('pagehide', flush)
    return () => {
      window.removeEventListener('pagehide', flush)
      flush()
    }
  }, [])
  // leaving with unsaved text: the browser asks on a reload / tab close, the app on a link to another page; the
  // update reload waits until the dialog is closed
  React.useEffect(() => {
    if (!dirty) return
    const h = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', h)
    busyStart()
    return () => {
      window.removeEventListener('beforeunload', h)
      busyEnd()
    }
  }, [dirty])
  const blocker = useBlocker(
    React.useCallback(
      ({ currentLocation: a, nextLocation: b }: { currentLocation: { pathname: string }; nextLocation: { pathname: string } }) => dirty && a.pathname !== b.pathname,
      [dirty],
    ),
  )
  React.useEffect(() => {
    if (blocker.state !== 'blocked') return
    if (window.confirm(t('mail.compose.leaveConfirm'))) blocker.proceed()
    else blocker.reset()
  }, [blocker, t])

  /** The dialog is done with this message (sent, saved and closed, or thrown away): no copy stays in the browser. */
  const finish = () => {
    closed.current = true
    forgetCompose()
    onClose()
  }

  const doSend = () => {
    if (inFlight.current || busy) return
    setError(null)
    if (!recipients) return setError(t('mail.compose.noRecipient'))
    if (recipients > MAX_RECIPIENTS) return setError(t('mail.compose.tooMany', { max: MAX_RECIPIENTS }))
    if (total > MAX_TOTAL) return setError(t('mail.compose.tooLarge'))
    if (unsure && !window.confirm(t('mail.compose.resendConfirm'))) return
    if (!subject.trim() && !window.confirm(t('mail.compose.noSubjectConfirm'))) return
    inFlight.current = true
    busyStart()
    const sent = draft
    send.mutate(
      { draft: build(), files },
      {
        onSuccess: (r) => {
          if (sent) forgetReply(sent.acc, sent)
          toast.success(r.refused.length ? t('mail.compose.sentPartly', { list: r.refused.join(', ') }) : t('mail.compose.sent'))
          finish()
        },
        onError: (e) => {
          // the connection dropped after the message was handed over: it probably left, never send it again by itself
          if (isApiError(e, 'sent_unknown')) {
            setUnsure(true)
            setError(t('mail.compose.sentUnknown'))
          } else if (isApiError(e, 'mail_busy')) setError(t('mail.busy'))
          else setError(errorMessage(e))
        },
        onSettled: () => {
          inFlight.current = false
          busyEnd()
        },
      },
    )
  }
  const doSave = (close: boolean) => {
    if (inFlight.current || busy) return
    setError(null)
    inFlight.current = true
    busyStart()
    const previous = draft && draft.acc === acc ? draft : undefined
    const saved = files
    save.mutate(
      { draft: build(), files },
      {
        onSuccess: async (r) => {
          const next = { folder: r.folder, uid: r.uid, acc }
          setDraft(next)
          if (init.reply && acc === init.acc && r.uid) rememberReply(acc, next, init.reply, previous)
          // every attachment is in the new draft now (the files sent, the kept ones read from `source`): read them
          // from there from now on, the previous draft is gone. Without its uid (no UIDPLUS) or its list, the new
          // files stay here and go again with the next save or the send.
          if (r.uid) {
            try {
              const c = await fetchMailCompose(acc, 'draft', r.folder, r.uid)
              setSource({ folder: r.folder, uid: r.uid, attachments: c.attachments, acc })
              setKept(c.attachments)
              setFiles((f) => f.filter((x) => !saved.includes(x)))
            } catch {
              /* keep them here */
            }
          }
          setDirty(false)
          forgetCompose()
          if (close) finish()
          else toast.success(t('mail.compose.saved'))
        },
        onError: (e) => setError(isApiError(e, 'mail_busy') ? t('mail.busy') : errorMessage(e)),
        onSettled: () => {
          inFlight.current = false
          busyEnd()
        },
      },
    )
  }
  const tryClose = () => {
    if (busy || inFlight.current) return
    if (dirty && !window.confirm(t('mail.compose.discardConfirm'))) return
    finish()
  }
  const touch = <T,>(set: (v: T) => void) => (v: T) => {
    setDirty(true)
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
                onValueChange={touch(setAcc)}
                options={accounts.map((a) => ({ value: a.id, label: a.name ? `${a.name} <${a.address}>` : a.address }))}
              />
            </Field>
          )}
          <Field
            label={t('mail.to')}
            extra={
              !showCc && (
                <button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={() => touch(setShowCc)(true)}>
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
