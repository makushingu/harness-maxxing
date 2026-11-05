// One message: headers, actions, attachments, body. An HTML body renders in a sandboxed iframe (no script, no
// form, no same origin) with a CSP that blocks every network request: remote images (trackers) only load after
// a click on "Show images".
import * as React from 'react'
import {
  Archive, ArrowLeft, Download, Flag, FolderInput, Forward, ImageOff, Inbox, MailOpen, Paperclip, Pencil, Reply, ReplyAll, ShieldAlert, Trash2,
} from 'lucide-react'
import {
  Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, EmptyState, Skeleton, Tooltip,
} from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { fmtBytes, fmtDate } from '@/lib/format'
import type { MailAction, MailComposeMode, MailFolder } from '@/lib/types'
import { mailAttachmentUrl, useMailMessage } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { avatarTone, folderIcon, folderLabel, initials, whoFull } from './shared'

function srcdoc(html: string, images: boolean): string {
  const csp = `default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:${images ? ' https: http:' : ''}; media-src data:`
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank">`
    + '<style>html,body{margin:0;background:#fff;color:#111}body{padding:16px;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;overflow-wrap:anywhere}img{max-width:100%;height:auto}table{max-width:100%}pre{white-space:pre-wrap}</style>'
    + `</head><body>${html}</body></html>`
}

function IconAction({ label, onClick, children, disabled }: { label: string; onClick: () => void; children: React.ReactNode; disabled?: boolean }) {
  return (
    <Tooltip content={label}>
      <Button variant="ghost" size="icon-sm" onClick={onClick} aria-label={label} disabled={disabled}>
        {children}
      </Button>
    </Tooltip>
  )
}

export function MessageView({ acc, folder, uid, folders, currentRole, onBack, onAction, onCompose }: {
  acc: string
  folder: string
  uid: number
  folders: MailFolder[]
  currentRole: string | null
  onBack?: () => void
  onAction: (action: MailAction, target?: string) => void
  onCompose: (mode: MailComposeMode) => void
}) {
  const t = useT()
  const lang = useLang()
  const { data: m, isLoading, error } = useMailMessage(acc, folder, uid)
  const [images, setImages] = React.useState(false)
  React.useEffect(() => setImages(false), [uid, folder, acc])

  if (isLoading) {
    return (
      <div className="grid gap-3 p-5">
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-64" />
      </div>
    )
  }
  if (error || !m) return <EmptyState compact tone="error" title={t('mail.msg.error')} description={error ? errorMessage(error) : undefined} />

  const inTrash = currentRole === 'trash'
  const inJunk = currentRole === 'junk'
  const moveTargets = folders.filter((f) => f.name !== folder)

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-0.5 border-b px-2 py-1.5">
        {onBack && (
          <Button variant="ghost" size="icon-sm" onClick={onBack} aria-label={t('common.back')}>
            <ArrowLeft />
          </Button>
        )}
        {currentRole === 'drafts' ? (
          <Button size="sm" variant="outline" className="mr-1" onClick={() => onCompose('draft')} data-testid="mail-edit-draft">
            <Pencil /> {t('mail.compose.editDraft')}
          </Button>
        ) : (
          <>
            <IconAction label={t('mail.compose.reply')} onClick={() => onCompose('reply')}>
              <Reply />
            </IconAction>
            {m.to.length + m.cc.length > 1 && (
              <IconAction label={t('mail.compose.replyAll')} onClick={() => onCompose('replyall')}>
                <ReplyAll />
              </IconAction>
            )}
            <IconAction label={t('mail.compose.forward')} onClick={() => onCompose('forward')}>
              <Forward />
            </IconAction>
          </>
        )}
        <span className="mx-1 h-5 w-px bg-border" />
        {currentRole !== 'archive' && (
          <IconAction label={t('mail.act.archive')} onClick={() => onAction('archive')}>
            <Archive />
          </IconAction>
        )}
        {inTrash || inJunk ? (
          <IconAction label={t('mail.act.inbox')} onClick={() => onAction('inbox')}>
            <Inbox />
          </IconAction>
        ) : (
          <IconAction label={t('mail.act.junk')} onClick={() => onAction('junk')}>
            <ShieldAlert />
          </IconAction>
        )}
        <IconAction label={inTrash || inJunk ? t('mail.act.deleteForever') : t('mail.act.trash')} onClick={() => onAction(inTrash || inJunk ? 'delete' : 'trash')}>
          <Trash2 className={cn((inTrash || inJunk) && 'text-destructive')} />
        </IconAction>
        <span className="mx-1 h-5 w-px bg-border" />
        <IconAction label={t('mail.act.unread')} onClick={() => onAction('unseen')}>
          <MailOpen />
        </IconAction>
        <IconAction label={m.flagged ? t('mail.act.unflag') : t('mail.act.flag')} onClick={() => onAction(m.flagged ? 'unflag' : 'flag')}>
          <Flag className={cn(m.flagged && 'fill-amber-400 text-amber-500')} />
        </IconAction>
        <DropdownMenu>
          <Tooltip content={t('mail.act.move')}>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={t('mail.act.move')}>
                <FolderInput />
              </Button>
            </DropdownMenuTrigger>
          </Tooltip>
          <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto">
            {moveTargets.map((f) => {
              const Icon = folderIcon(f)
              return (
                <DropdownMenuItem key={f.name} onSelect={() => onAction('move', f.name)}>
                  <Icon /> {folderLabel(f, t)}
                </DropdownMenuItem>
              )
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <div className="grid gap-3 px-5 pt-4 pb-3">
          <h2 className="text-lg leading-snug font-semibold break-words">{m.subject || t('mail.noSubject')}</h2>
          <div className="flex items-start gap-3">
            <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold', avatarTone(m.from))}>{initials(m.from)}</span>
            <div className="grid min-w-0 flex-1 gap-0.5 text-[13px]">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="truncate font-medium">
                  {m.from.name || m.from.email}
                  {m.from.name && <span className="ml-1.5 font-normal text-muted-foreground">{m.from.email}</span>}
                </span>
                {m.date && <span className="shrink-0 text-xs text-muted-foreground">{fmtDate(m.date, lang)}</span>}
              </div>
              {!!m.to.length && (
                <span className="truncate text-muted-foreground">
                  {t('mail.to')} {m.to.map(whoFull).join(', ')}
                </span>
              )}
              {!!m.cc.length && (
                <span className="truncate text-muted-foreground">
                  {t('mail.cc')} {m.cc.map(whoFull).join(', ')}
                </span>
              )}
            </div>
          </div>
          {!!m.attachments.length && (
            <div className="flex flex-wrap gap-2">
              {m.attachments.map((a) => {
                const viewable = (a.content_type.startsWith('image/') && a.content_type !== 'image/svg+xml') || a.content_type === 'application/pdf'
                return (
                  <a
                    key={a.index}
                    href={mailAttachmentUrl(acc, folder, uid, a.index, viewable)}
                    target={viewable ? '_blank' : undefined}
                    rel="noopener noreferrer"
                    download={viewable ? undefined : a.filename}
                    className="flex max-w-64 items-center gap-2 rounded-lg border bg-card px-2.5 py-1.5 text-xs hover:bg-accent/60"
                  >
                    <Paperclip className="size-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate">{a.filename}</span>
                    <span className="shrink-0 text-muted-foreground">{fmtBytes(a.size)}</span>
                    {!viewable && <Download className="size-3.5 shrink-0 text-muted-foreground" />}
                  </a>
                )
              })}
            </div>
          )}
          {m.html && m.remote_images && !images && (
            <div className="flex items-center gap-2 rounded-lg bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
              <ImageOff className="size-4 shrink-0" />
              <span className="flex-1">{t('mail.msg.imagesBlocked')}</span>
              <Button size="sm" variant="outline" onClick={() => setImages(true)}>
                {t('mail.msg.showImages')}
              </Button>
            </div>
          )}
        </div>
        {m.html ? (
          <div className="mx-3 mb-3 flex min-h-[24rem] flex-1 overflow-hidden rounded-lg border bg-white">
            <iframe
              key={`${uid}-${images}`}
              title={m.subject || 'message'}
              sandbox="allow-popups allow-popups-to-escape-sandbox"
              referrerPolicy="no-referrer"
              srcDoc={srcdoc(m.html, images)}
              className="min-h-[24rem] w-full flex-1"
            />
          </div>
        ) : (
          <pre className="px-5 pb-6 font-sans text-sm leading-relaxed break-words whitespace-pre-wrap">{m.text || t('mail.msg.empty')}</pre>
        )}
      </div>
    </div>
  )
}
