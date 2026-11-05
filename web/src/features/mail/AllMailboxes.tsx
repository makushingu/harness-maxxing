// "All mailboxes" (?a=*): the newest mails of every mailbox, read from the cache of the last checks (GET /api/mail/all,
// not live: Refresh checks them all). A click opens the message in its own mailbox and folder.
import { Mail, Paperclip } from 'lucide-react'
import { Badge, Button, EmptyState, Sensitive, Skeleton } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { useMailAll } from '@/lib/queries'
import type { MailAccount, MailAllRow } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { SeenByAvatars, Verified } from './agents'
import { shortDate, who } from './shared'

export function AllMailboxes({ accounts, onOpen }: { accounts: MailAccount[]; onOpen: (r: MailAllRow) => void }) {
  const t = useT()
  const lang = useLang()
  const { data, isLoading, error, refetch } = useMailAll()
  const label = new Map(accounts.map((a) => [a.id, a.label || a.address]))
  const rows = data?.messages || []
  if (isLoading) {
    return (
      <div className="grid gap-2 p-3">
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="h-14" />
        ))}
      </div>
    )
  }
  if (error) {
    return <EmptyState compact tone="error" title={t('mail.listError')} description={errorMessage(error)} action={<Button variant="outline" size="sm" onClick={() => refetch()}>{t('common.retry')}</Button>} />
  }
  if (!rows.length) return <EmptyState compact icon={Mail} title={t('mail.all.empty')} description={t('mail.all.emptyDesc')} />
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <ul className="mx-auto max-w-4xl" data-testid="mail-all">
        {rows.map((m) => (
          <li
            key={`${m.account}/${m.folder}/${m.uid}`}
            className="relative flex cursor-pointer items-start gap-2.5 border-b px-4 py-2.5 transition-colors hover:bg-accent/40"
            onClick={() => onOpen(m)}
            data-testid="mail-all-row"
          >
            {!m.seen && <span className="absolute top-4 left-1.5 size-1.5 rounded-full bg-primary" aria-label={t('mail.unread')} />}
            <div className="grid min-w-0 flex-1 gap-0.5">
              <div className="flex items-baseline gap-2">
                <span className={cn('min-w-0 truncate text-[13px]', !m.seen ? 'font-semibold' : 'text-foreground/90')}>
                  <Sensitive length={8}>{who(m.from) || t('mail.unknownSender')}</Sensitive>
                </span>
                <Verified on={m.from_verified} className="self-center" />
                <span className="flex-1" />
                <SeenByAvatars list={m.seen_by} className="self-center" />
                {m.attachments && <Paperclip className="size-3 shrink-0 self-center text-muted-foreground" />}
                <Badge variant="muted" className="max-w-40 shrink-0 self-center truncate px-1.5 py-0 text-[10px] font-normal max-sm:max-w-24">
                  <Sensitive length={6}>{label.get(m.account) || m.address}</Sensitive>
                </Badge>
                <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums">{shortDate(m.date, lang)}</span>
              </div>
              <span className={cn('truncate text-[13px]', !m.seen ? 'font-medium' : 'text-muted-foreground')}>
                <Sensitive length={10}>{m.subject || t('mail.noSubject')}</Sensitive>
              </span>
              {m.snippet && (
                <span className="truncate text-xs text-muted-foreground">
                  <Sensitive length={14}>{m.snippet}</Sensitive>
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
